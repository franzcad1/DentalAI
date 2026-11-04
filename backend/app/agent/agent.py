"""DentalAI LangChain-style Agent.

Uses the OpenAI function-calling API directly (no tiktoken dependency) while
keeping LangChain's @tool decorator for tool definitions.  This makes the
function-calling mechanics explicit and easy to follow — a stronger portfolio
demo than hiding them inside a third-party executor.

═══════════════════════════════════════════════════════════════
TOOL SIGNATURES
═══════════════════════════════════════════════════════════════

check_available_slots(date_from, date_to, provider_id=0)
    Returns every unbooked AvailableSlot in [date_from, date_to].
    date_from / date_to : "YYYY-MM-DD"
    provider_id         : optional int — 0 means "any provider"
    → JSON list of slot objects {slot_id, provider_id, provider_name,
      location_id, start_time, end_time}

book_appointment(patient_id, slot_id, appointment_type_id, notes="")
    1. Verifies the slot exists and is not already booked.
    2. Creates an Appointment row linked to slot provider/location.
    3. Marks AvailableSlot.is_booked = True.
    4. Fires appointment.booked event through the event bus.
    → Confirmation string with appointment_id and slot details

delete_appointment(appointment_id)
    Permanently removes the appointment row from the database.
    Frees the associated slot. Use when user says "delete" or "remove".
    → Confirmation string with patient name and time.

cancel_appointment(appointment_id)
    Sets appointment status to "cancelled" (record is kept).
    Use when user says "cancel". → Confirmation string with patient name and old time.

update_appointment_status(appointment_id, status)
    Sets appointment status to any valid value:
    confirmed | completed | pending | no_show | cancelled
    → Confirmation string showing the status transition.

reschedule_appointment(appointment_id, new_slot_id)
    Frees the old slot and moves the appointment to a new slot.
    Enforces 5 PM closing time on the new slot.
    → Confirmation string with old and new times.

get_patient_context(patient_id)
    Returns a compact patient summary: demographics, most recent
    appointment (status, date, provider), and current recall status.
    → JSON object with keys: patient, last_appointment, recall

get_recall_queue()
    Returns all patients with pending overdue recalls, sorted by
    days_overdue descending so the agent prioritises the worst cases.
    → JSON list {patient_id, name, recall_type, due_date, days_overdue}

draft_recall_message(patient_id)
    Generates a ready-to-send recall outreach message personalised with
    the patient's name, recall type, and days overdue. Tone escalates
    with how overdue the patient is (gentle → moderate → urgent).
    → Plain-text message string

═══════════════════════════════════════════════════════════════
AGENT LOOP ARCHITECTURE
═══════════════════════════════════════════════════════════════

  run_agent(message, session_id)
    │
    ├─ Build messages list (system + history + user turn)
    │
    └─ Loop (up to MAX_ITERATIONS):
         │
         ├─ POST /chat/completions  with tools=OPENAI_TOOL_SCHEMAS
         │
         ├─ If finish_reason == "tool_calls":
         │     → execute each called tool
         │     → append assistant message + tool results to messages
         │     → log tool call for response
         │
         └─ If finish_reason == "stop":
               → return final answer + accumulated tool_call log

Conversation memory: in-process dict {session_id: messages_list}.
Swap for Redis-backed storage for multi-instance deployments.
"""

import inspect
import json
import logging
import os
import re
import time
from datetime import datetime, date, timedelta
from typing import Any, Callable, Dict, List, Optional

from dotenv import load_dotenv
from langchain_core.tools import tool
from groq import Groq
from openai.types.chat import ChatCompletionMessageParam

from app.db.session import SessionLocal
from app.events.bus import emit_event
from app.models.orm import (
    Appointment,
    AppointmentType,
    AvailableSlot,
    Patient,
    PatientRecall,
    Provider,
)

load_dotenv()

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 6  # safety cap: prevents infinite tool-call loops

# ---------------------------------------------------------------------------
# Per-session retry status — surfaced to the frontend via GET /agent/status
# ---------------------------------------------------------------------------

# { session_id: {"retry_in": int, "set_at": float} | None }
_retry_status: Dict[str, Optional[Dict[str, Any]]] = {}


def set_retry_status(session_id: str, retry_in: float) -> None:
    _retry_status[session_id] = {"retry_in": int(retry_in), "set_at": time.time()}


def clear_retry_status(session_id: str) -> None:
    _retry_status.pop(session_id, None)


def get_retry_status(session_id: str) -> Optional[Dict[str, Any]]:
    """Return remaining retry seconds, or None if not retrying."""
    entry = _retry_status.get(session_id)
    if not entry:
        return None
    elapsed = time.time() - entry["set_at"]
    remaining = entry["retry_in"] - elapsed
    if remaining <= 0:
        _retry_status.pop(session_id, None)
        return None
    return {"retry_in": entry["retry_in"], "remaining": int(remaining) + 1}

# ---------------------------------------------------------------------------
# In-memory session store  {session_id: [message_dict, ...]}
# ---------------------------------------------------------------------------

_session_histories: Dict[str, List[Dict[str, Any]]] = {}


def _get_history(session_id: str) -> List[Dict[str, Any]]:
    if session_id not in _session_histories:
        _session_histories[session_id] = []
    return _session_histories[session_id]


# ---------------------------------------------------------------------------
# Shared date parser
# ---------------------------------------------------------------------------


def _parse_date(s: str) -> date:
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(f"Date '{s}' must be in YYYY-MM-DD format")


# ---------------------------------------------------------------------------
# Tool definitions  (LangChain @tool for schema introspection)
# ---------------------------------------------------------------------------


@tool
def check_available_slots(date_from: str, date_to: str, provider_id: int = 0) -> str:
    """Return unbooked slots in [date_from, date_to] (YYYY-MM-DD). provider_id=0 means any provider."""
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)

    db = SessionLocal()
    try:
        from_dt = datetime(d_from.year, d_from.month, d_from.day)
        to_dt = datetime(d_to.year, d_to.month, d_to.day) + timedelta(days=1)
        # Strip timezone from stored datetimes for comparison (SQLite stores as naive)
        q = (
            db.query(AvailableSlot)
            .filter(AvailableSlot.is_booked == False)  # noqa: E712
            .filter(AvailableSlot.start_time >= from_dt)
            .filter(AvailableSlot.start_time < to_dt)
        )
        if provider_id and provider_id != 0:
            q = q.filter(AvailableSlot.provider_id == provider_id)

        slots = q.order_by(AvailableSlot.start_time).limit(200).all()

        # Exclude slots whose start time is at or after 17:00 (nothing can finish by 5 PM)
        slots = [s for s in slots if s.start_time.hour < 17]

        total_available = len(slots)
        result = []
        for s in slots[:10]:
            provider = db.get(Provider, s.provider_id)
            provider_name = (
                f"Dr. {provider.first_name} {provider.last_name}"
                if provider
                else "Unknown"
            )
            result.append(
                {
                    "slot_id": s.id,
                    "provider_name": provider_name,
                    "start_time": s.start_time.isoformat(),
                    "end_time": s.end_time.isoformat(),
                }
            )

        if not result:
            return "No available slots found for the requested date range and provider."
        if total_available > 10:
            return json.dumps({
                "slots": result,
                "truncated": True,
                "total": total_available,
                "note": f"Showing first 10 of {total_available} slots. Narrow the date range to see more.",
            })
        return json.dumps(result)
    finally:
        db.close()


@tool
def book_appointment(
    patient_id: int,
    slot_id: int,
    appointment_type_id: int,
    notes: str = "",
) -> str:
    """Book a patient into an available slot. Verifies the slot is free, enforces 5 PM close, fires booking event."""
    db = SessionLocal()
    try:
        slot = db.get(AvailableSlot, slot_id)
        if not slot:
            return f"Error: slot {slot_id} does not exist."
        if slot.is_booked:
            return f"Error: slot {slot_id} is already booked. Please choose another slot."

        patient = db.get(Patient, patient_id)
        if not patient:
            return f"Error: patient {patient_id} not found."

        appt_type = db.get(AppointmentType, appointment_type_id)
        if not appt_type:
            return f"Error: appointment type {appointment_type_id} not found."

        end_time = slot.start_time + timedelta(minutes=appt_type.duration_minutes)
        cutoff = slot.start_time.replace(hour=17, minute=0, second=0, microsecond=0)
        if end_time > cutoff:
            return (
                f"Error: this appointment would end at {end_time.strftime('%I:%M %p')}, "
                f"which is after the 5:00 PM closing time. "
                f"Please choose an earlier slot."
            )

        # Check for overlapping appointments with the same provider
        overlap = (
            db.query(Appointment)
            .filter(
                Appointment.provider_id == slot.provider_id,
                Appointment.status.notin_(["cancelled"]),
                Appointment.start_time < end_time,
                Appointment.end_time > slot.start_time,
            )
            .first()
        )
        if overlap:
            prov = db.get(Provider, slot.provider_id)
            prov_name = f"Dr. {prov.last_name}" if prov else f"Provider #{slot.provider_id}"
            return (
                f"Error: {prov_name} already has an appointment from "
                f"{overlap.start_time.strftime('%I:%M %p')} to {overlap.end_time.strftime('%I:%M %p')} "
                f"that overlaps with this time slot. Please choose a different slot."
            )

        appt = Appointment(
            patient_id=patient_id,
            provider_id=slot.provider_id,
            location_id=slot.location_id,
            appointment_type_id=appointment_type_id,
            start_time=slot.start_time,
            end_time=end_time,
            status="confirmed",
            notes=notes or None,
        )
        db.add(appt)
        slot.is_booked = True
        db.commit()
        db.refresh(appt)

        # Fires via the shared event bus (opens its own session)
        emit_event(
            "appointment.booked",
            {
                "appointment_id": appt.id,
                "patient_id": patient_id,
                "provider_id": slot.provider_id,
                "start_time": slot.start_time.isoformat(),
                "appointment_type": appt_type.name,
                "booked_via": "agent",
            },
        )

        provider = db.get(Provider, slot.provider_id)
        provider_name = (
            f"Dr. {provider.first_name} {provider.last_name}" if provider else "Provider"
        )
        return (
            f"Appointment booked successfully!\n"
            f"  Appointment ID : {appt.id}\n"
            f"  Patient        : {patient.first_name} {patient.last_name}\n"
            f"  Provider       : {provider_name}\n"
            f"  Type           : {appt_type.name} ({appt_type.duration_minutes} min)\n"
            f"  Time           : {slot.start_time.strftime('%A, %B %d at %I:%M %p')}\n"
            f"  Status         : confirmed"
        )
    finally:
        db.close()


@tool
def get_patient_context(patient_id: int) -> str:
    """Return a patient summary: demographics, most recent appointment, and current recall status."""
    db = SessionLocal()
    try:
        patient = db.get(Patient, patient_id)
        if not patient:
            return json.dumps({"error": f"Patient {patient_id} not found"})

        last_appt = (
            db.query(Appointment)
            .filter(Appointment.patient_id == patient_id)
            .order_by(Appointment.start_time.desc())
            .first()
        )
        last_appt_data = None
        if last_appt:
            provider = db.get(Provider, last_appt.provider_id)
            appt_type = db.get(AppointmentType, last_appt.appointment_type_id)
            last_appt_data = {
                "appointment_id": last_appt.id,
                "type": appt_type.name if appt_type else "unknown",
                "start_time": last_appt.start_time.isoformat(),
                "status": last_appt.status,
                "provider": (
                    f"Dr. {provider.first_name} {provider.last_name}"
                    if provider
                    else "Unknown"
                ),
            }

        recall = (
            db.query(PatientRecall)
            .filter(PatientRecall.patient_id == patient_id)
            .filter(PatientRecall.status == "pending")
            .order_by(PatientRecall.due_date)
            .first()
        )
        recall_data = None
        if recall:
            today = datetime.utcnow().date()
            days_overdue = (today - recall.due_date).days
            recall_data = {
                "recall_type": recall.recall_type,
                "due_date": str(recall.due_date),
                "days_overdue": days_overdue if days_overdue > 0 else 0,
            }

        return json.dumps(
            {
                "patient": {
                    "id": patient.id,
                    "name": f"{patient.first_name} {patient.last_name}",
                    "dob": str(patient.dob) if patient.dob else None,
                },
                "last_appointment": last_appt_data,
                "recall": recall_data,
            }
        )
    finally:
        db.close()


@tool
def get_recall_queue() -> str:
    """Return all patients with overdue pending recalls, most overdue first."""
    db = SessionLocal()
    try:
        today = datetime.utcnow().date()
        overdue = (
            db.query(PatientRecall)
            .filter(PatientRecall.due_date < today)
            .filter(PatientRecall.status == "pending")
            .order_by(PatientRecall.due_date)
            .all()
        )
        if not overdue:
            return "No overdue recalls at this time."

        result = []
        for recall in overdue:
            patient = db.get(Patient, recall.patient_id)
            days_overdue = (today - recall.due_date).days
            result.append(
                {
                    "patient_id": recall.patient_id,
                    "name": (
                        f"{patient.first_name} {patient.last_name}"
                        if patient
                        else "Unknown"
                    ),
                    "recall_type": recall.recall_type,
                    "due_date": str(recall.due_date),
                    "days_overdue": days_overdue,
                }
            )
        result.sort(key=lambda x: x["days_overdue"], reverse=True)
        return json.dumps(result)
    finally:
        db.close()


@tool
def search_patients(name: str) -> str:
    """Search patients by first or last name (case-insensitive partial match). Returns up to 10 matches."""
    db = SessionLocal()
    try:
        parts = name.strip().split()
        if len(parts) >= 2:
            # Try full-name match first (e.g. "Diana Taylor")
            first_term = f"%{parts[0]}%"
            last_term = f"%{parts[-1]}%"
            patients = (
                db.query(Patient)
                .filter(
                    Patient.first_name.ilike(first_term) & Patient.last_name.ilike(last_term)
                )
                .limit(10)
                .all()
            )
            if not patients:
                # Fall back to either name matching any part
                term = f"%{name.strip()}%"
                patients = (
                    db.query(Patient)
                    .filter(
                        Patient.first_name.ilike(first_term) | Patient.last_name.ilike(last_term)
                    )
                    .limit(10)
                    .all()
                )
        else:
            term = f"%{name.strip()}%"
            patients = (
                db.query(Patient)
                .filter(
                    Patient.first_name.ilike(term) | Patient.last_name.ilike(term)
                )
                .limit(10)
                .all()
            )
        if not patients:
            return f"No patients found matching '{name}'."
        result = [{"id": p.id, "name": f"{p.first_name} {p.last_name}"} for p in patients]
        return json.dumps(result)
    finally:
        db.close()


@tool
def add_patient(
    first_name: str,
    last_name: str,
    dob: str = "",
    email: str = "",
    phone: str = "",
) -> str:
    """Add a new patient. dob in YYYY-MM-DD format; email and phone are optional."""
    db = SessionLocal()
    try:
        from app.models.orm import Patient as PatientModel
        patient = PatientModel(
            first_name=first_name.strip(),
            last_name=last_name.strip(),
            dob=_parse_date(dob) if dob.strip() else None,
            email=email.strip() or None,
            phone=phone.strip() or None,
        )
        db.add(patient)
        db.commit()
        db.refresh(patient)
        return (
            f"Patient added successfully!\n"
            f"  ID    : {patient.id}\n"
            f"  Name  : {patient.first_name} {patient.last_name}\n"
            f"  DOB   : {patient.dob or 'not provided'}\n"
            f"  Email : {patient.email or 'not provided'}\n"
            f"  Phone : {patient.phone or 'not provided'}"
        )
    finally:
        db.close()


@tool
def list_all_patients() -> str:
    """Return all patients sorted by last name."""
    db = SessionLocal()
    try:
        patients = db.query(Patient).order_by(Patient.last_name, Patient.first_name).all()
        if not patients:
            return "No patients found in the system."
        result = [{"id": p.id, "name": f"{p.first_name} {p.last_name}"} for p in patients]
        return json.dumps(result)
    finally:
        db.close()


@tool
def list_patients_by_provider(provider_name: str) -> str:
    """Return patients who have had at least one appointment with the given provider (partial name match)."""
    db = SessionLocal()
    try:
        term = f"%{provider_name.strip().replace('Dr.', '').strip()}%"
        providers = (
            db.query(Provider)
            .filter(
                Provider.first_name.ilike(term) | Provider.last_name.ilike(term)
            )
            .all()
        )
        if not providers:
            return f"No provider found matching '{provider_name}'."

        result = []
        for provider in providers:
            appts = (
                db.query(Appointment)
                .filter(Appointment.provider_id == provider.id)
                .order_by(Appointment.start_time.desc())
                .all()
            )
            seen = {}
            for a in appts:
                if a.patient_id not in seen:
                    patient = db.get(Patient, a.patient_id)
                    if patient:
                        seen[a.patient_id] = {
                            "patient_id": patient.id,
                            "name": f"{patient.first_name} {patient.last_name}",
                            "last_appointment": a.start_time.strftime("%Y-%m-%d"),
                            "provider": f"Dr. {provider.first_name} {provider.last_name}",
                        }
            result.extend(seen.values())

        if not result:
            return f"No patients found with appointments for '{provider_name}'."
        result.sort(key=lambda x: x["name"])
        return json.dumps(result)
    finally:
        db.close()


@tool
def get_patient_appointments(patient_id: int, days_ahead: int = 14) -> str:
    """Return a patient's appointments: past 30 days plus next days_ahead days (default 14)."""
    db = SessionLocal()
    try:
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        future = today + timedelta(days=days_ahead)
        # Past 30 days + future window
        past = today - timedelta(days=30)
        appts = (
            db.query(Appointment)
            .filter(Appointment.patient_id == patient_id)
            .filter(Appointment.start_time >= past)
            .filter(Appointment.start_time < future)
            .order_by(Appointment.start_time)
            .all()
        )
        if not appts:
            return f"No appointments found for patient {patient_id} in the next {days_ahead} days or past 30 days."
        result = []
        for a in appts:
            provider = db.get(Provider, a.provider_id)
            appt_type = db.get(AppointmentType, a.appointment_type_id)
            result.append({
                "appointment_id": a.id,
                "date": a.start_time.strftime("%A, %B %d, %Y at %I:%M %p"),
                "provider": f"Dr. {provider.first_name} {provider.last_name}" if provider else "Unknown",
                "type": appt_type.name if appt_type else "Unknown",
                "status": a.status,
            })
        return json.dumps(result)
    finally:
        db.close()


@tool
def get_appointments_for_date(date: str) -> str:
    """Return all booked appointments for a specific date (YYYY-MM-DD)."""
    d = _parse_date(date)
    db = SessionLocal()
    try:
        day_start = datetime(d.year, d.month, d.day)
        day_end = day_start + timedelta(days=1)
        appts = (
            db.query(Appointment)
            .filter(Appointment.start_time >= day_start)
            .filter(Appointment.start_time < day_end)
            .order_by(Appointment.start_time)
            .all()
        )
        if not appts:
            return f"No appointments scheduled for {d.strftime('%A, %B %d, %Y')}."
        result = []
        for a in appts:
            patient = db.get(Patient, a.patient_id)
            provider = db.get(Provider, a.provider_id)
            appt_type = db.get(AppointmentType, a.appointment_type_id)
            result.append({
                "appointment_id": a.id,
                "patient": f"{patient.first_name} {patient.last_name}" if patient else "Unknown",
                "provider": f"Dr. {provider.first_name} {provider.last_name}" if provider else "Unknown",
                "type": appt_type.name if appt_type else "Unknown",
                "start_time": a.start_time.isoformat(),
                "status": a.status,
            })
        return json.dumps(result)
    finally:
        db.close()


@tool
def draft_recall_message(patient_id: int) -> str:
    """Draft a personalised recall outreach message. Tone escalates with days overdue (≤30 gentle, 31-90 moderate, >90 urgent)."""
    db = SessionLocal()
    try:
        patient = db.get(Patient, patient_id)
        if not patient:
            return f"Error: patient {patient_id} not found."

        today = datetime.utcnow().date()
        recall = (
            db.query(PatientRecall)
            .filter(PatientRecall.patient_id == patient_id)
            .filter(PatientRecall.status == "pending")
            .filter(PatientRecall.due_date < today)
            .order_by(PatientRecall.due_date)
            .first()
        )

        if not recall:
            upcoming = (
                db.query(PatientRecall)
                .filter(PatientRecall.patient_id == patient_id)
                .filter(PatientRecall.status == "pending")
                .order_by(PatientRecall.due_date)
                .first()
            )
            if not upcoming:
                return f"{patient.first_name} {patient.last_name} has no pending recalls."
            return (
                f"Hi {patient.first_name},\n\n"
                f"This is a friendly reminder that your {upcoming.recall_type} is coming up on "
                f"{upcoming.due_date.strftime('%B %d, %Y')}. "
                f"Please call us at (555) 867-5309 to schedule.\n\n"
                f"— DentalAI Dental Team"
            )

        days_overdue = (today - recall.due_date).days

        if days_overdue <= 30:
            urgency, opener = "gentle", f"Hi {patient.first_name},"
            body = (
                f"We noticed your {recall.recall_type} was due on "
                f"{recall.due_date.strftime('%B %d, %Y')}. "
                f"We'd love to get you scheduled at your earliest convenience."
            )
        elif days_overdue <= 90:
            urgency, opener = "moderate", f"Hi {patient.first_name},"
            body = (
                f"Your {recall.recall_type} is now {days_overdue} days overdue "
                f"(due {recall.due_date.strftime('%B %d, %Y')}). "
                f"Staying current with your dental care is important — "
                f"please call us to get back on track."
            )
        else:
            urgency, opener = "urgent", f"Dear {patient.first_name},"
            body = (
                f"We're reaching out because your {recall.recall_type} is "
                f"{days_overdue} days overdue (originally due "
                f"{recall.due_date.strftime('%B %d, %Y')}). "
                f"Extended gaps can affect your oral health. "
                f"Please contact us as soon as possible."
            )

        return (
            f"{opener}\n\n"
            f"{body}\n\n"
            f"To schedule, call (555) 867-5309 or reply to this message.\n\n"
            f"— DentalAI Dental Team\n"
            f"[urgency={urgency} | recall_id={recall.id} | days_overdue={days_overdue}]"
        )
    finally:
        db.close()


@tool
def delete_appointment(appointment_id: int) -> str:
    """Permanently delete an appointment and free its slot. Use for 'delete' or 'remove' requests."""
    db = SessionLocal()
    try:
        appt = db.get(Appointment, appointment_id)
        if not appt:
            return f"Error: appointment {appointment_id} not found."
        patient = db.get(Patient, appt.patient_id)
        patient_name = f"{patient.first_name} {patient.last_name}" if patient else f"Patient #{appt.patient_id}"
        appt_time = appt.start_time.strftime('%A, %B %d at %I:%M %p')

        # Free the matching slot if it exists
        old_slot = (
            db.query(AvailableSlot)
            .filter(
                AvailableSlot.provider_id == appt.provider_id,
                AvailableSlot.start_time == appt.start_time,
            )
            .first()
        )
        if old_slot:
            old_slot.is_booked = False

        db.delete(appt)
        db.commit()
        return f"Appointment for {patient_name} on {appt_time} has been permanently deleted."
    finally:
        db.close()


@tool
def cancel_appointment(appointment_id: int) -> str:
    """Set appointment status to 'cancelled' (record kept). Use for 'cancel' requests."""
    db = SessionLocal()
    try:
        appt = db.get(Appointment, appointment_id)
        if not appt:
            return f"Error: appointment {appointment_id} not found."
        if appt.status == "cancelled":
            return f"Appointment {appointment_id} is already cancelled."
        old_status = appt.status
        appt.status = "cancelled"
        db.commit()
        patient = db.get(Patient, appt.patient_id)
        patient_name = f"{patient.first_name} {patient.last_name}" if patient else f"Patient #{appt.patient_id}"
        return (
            f"Appointment {appointment_id} for {patient_name} has been cancelled.\n"
            f"  Was: {old_status} on {appt.start_time.strftime('%A, %B %d at %I:%M %p')}"
        )
    finally:
        db.close()


@tool
def modify_appointment(
    appointment_id: int,
    new_provider_id: Optional[int] = None,
    new_slot_id: Optional[int] = None,
    new_appointment_type_id: Optional[int] = None,
    new_patient_id: Optional[int] = None,
    new_status: Optional[str] = None,
    new_notes: Optional[str] = None,
) -> str:
    """Edit any field of an appointment in one call (provider, slot, type, patient, status, notes). Pass only the fields to change. To reschedule, call check_available_slots first then pass new_slot_id."""
    valid_statuses = {"confirmed", "completed", "pending", "no_show", "cancelled"}
    if new_status and new_status not in valid_statuses:
        return f"Error: '{new_status}' is not a valid status. Choose from: {', '.join(sorted(valid_statuses))}."

    db = SessionLocal()
    try:
        appt = db.get(Appointment, appointment_id)
        if not appt:
            return f"Error: appointment {appointment_id} not found."

        changes: list[str] = []

        # ── Time / slot change ──────────────────────────────────────────────
        if new_slot_id is not None:
            new_slot = db.get(AvailableSlot, new_slot_id)
            if not new_slot:
                return f"Error: slot {new_slot_id} does not exist."
            if new_slot.is_booked:
                return f"Error: slot {new_slot_id} is already booked. Please choose a different slot."

            effective_type_id = new_appointment_type_id or appt.appointment_type_id
            appt_type = db.get(AppointmentType, effective_type_id)
            duration = appt_type.duration_minutes if appt_type else 30
            new_end = new_slot.start_time + timedelta(minutes=duration)
            cutoff = new_slot.start_time.replace(hour=17, minute=0, second=0, microsecond=0)
            if new_end > cutoff:
                return (
                    f"Error: this appointment would end at {new_end.strftime('%I:%M %p')}, "
                    f"after the 5:00 PM closing time. Please choose an earlier slot."
                )

            effective_provider_id = new_provider_id or appt.provider_id
            overlap = (
                db.query(Appointment)
                .filter(
                    Appointment.id != appointment_id,
                    Appointment.provider_id == effective_provider_id,
                    Appointment.status.notin_(["cancelled"]),
                    Appointment.start_time < new_end,
                    Appointment.end_time > new_slot.start_time,
                )
                .first()
            )
            if overlap:
                prov = db.get(Provider, effective_provider_id)
                prov_name = f"Dr. {prov.last_name}" if prov else f"Provider #{effective_provider_id}"
                return (
                    f"Error: {prov_name} already has an appointment from "
                    f"{overlap.start_time.strftime('%I:%M %p')} to {overlap.end_time.strftime('%I:%M %p')} "
                    f"that overlaps with the requested slot. Please choose a different time."
                )

            # Free the old slot
            old_slot = (
                db.query(AvailableSlot)
                .filter(
                    AvailableSlot.provider_id == appt.provider_id,
                    AvailableSlot.start_time == appt.start_time,
                )
                .first()
            )
            if old_slot:
                old_slot.is_booked = False

            changes.append(f"  Time    : {appt.start_time.strftime('%A, %B %d at %I:%M %p')} → {new_slot.start_time.strftime('%A, %B %d at %I:%M %p')}")
            appt.start_time = new_slot.start_time
            appt.end_time = new_end
            appt.location_id = new_slot.location_id
            if new_provider_id is None:
                appt.provider_id = new_slot.provider_id
            new_slot.is_booked = True

        # ── Provider change (no slot change) ────────────────────────────────
        if new_provider_id is not None and new_slot_id is None:
            new_prov = db.get(Provider, new_provider_id)
            if not new_prov:
                return f"Error: provider {new_provider_id} not found."

            # Check for conflicts at the existing time
            effective_end = appt.end_time
            overlap = (
                db.query(Appointment)
                .filter(
                    Appointment.id != appointment_id,
                    Appointment.provider_id == new_provider_id,
                    Appointment.status.notin_(["cancelled"]),
                    Appointment.start_time < effective_end,
                    Appointment.end_time > appt.start_time,
                )
                .first()
            )
            if overlap:
                new_prov_name = f"Dr. {new_prov.first_name} {new_prov.last_name}"
                return (
                    f"Error: {new_prov_name} already has an appointment at "
                    f"{overlap.start_time.strftime('%I:%M %p')}–{overlap.end_time.strftime('%I:%M %p')} "
                    f"that conflicts with the existing time. "
                    f"Call check_available_slots(provider_id={new_provider_id}) to find a free slot, "
                    f"then call modify_appointment again with new_provider_id and new_slot_id."
                )

            old_prov = db.get(Provider, appt.provider_id)
            old_prov_name = f"Dr. {old_prov.last_name}" if old_prov else f"Provider #{appt.provider_id}"
            # Free old slot, mark new slot if one exists
            old_slot = (
                db.query(AvailableSlot)
                .filter(AvailableSlot.provider_id == appt.provider_id, AvailableSlot.start_time == appt.start_time)
                .first()
            )
            if old_slot:
                old_slot.is_booked = False
            new_slot_match = (
                db.query(AvailableSlot)
                .filter(AvailableSlot.provider_id == new_provider_id, AvailableSlot.start_time == appt.start_time)
                .first()
            )
            if new_slot_match:
                new_slot_match.is_booked = True
                appt.location_id = new_slot_match.location_id

            changes.append(f"  Provider: {old_prov_name} → Dr. {new_prov.first_name} {new_prov.last_name}")
            appt.provider_id = new_provider_id

        elif new_provider_id is not None and new_slot_id is not None:
            # Provider supplied alongside a slot — apply it
            old_prov = db.get(Provider, appt.provider_id)
            new_prov = db.get(Provider, new_provider_id)
            old_name = f"Dr. {old_prov.last_name}" if old_prov else f"#{appt.provider_id}"
            new_name = f"Dr. {new_prov.first_name} {new_prov.last_name}" if new_prov else f"#{new_provider_id}"
            changes.append(f"  Provider: {old_name} → {new_name}")
            appt.provider_id = new_provider_id

        # ── Appointment type ─────────────────────────────────────────────────
        if new_appointment_type_id is not None and new_appointment_type_id != appt.appointment_type_id:
            old_type = db.get(AppointmentType, appt.appointment_type_id)
            new_type = db.get(AppointmentType, new_appointment_type_id)
            if not new_type:
                return f"Error: appointment type {new_appointment_type_id} not found."
            changes.append(f"  Type    : {old_type.name if old_type else appt.appointment_type_id} → {new_type.name}")
            appt.appointment_type_id = new_appointment_type_id
            # Recompute end_time if no slot was swapped
            if new_slot_id is None:
                new_end = appt.start_time + timedelta(minutes=new_type.duration_minutes)
                cutoff = appt.start_time.replace(hour=17, minute=0, second=0, microsecond=0)
                if new_end > cutoff:
                    return (
                        f"Error: changing to '{new_type.name}' ({new_type.duration_minutes} min) would end at "
                        f"{new_end.strftime('%I:%M %p')}, after the 5:00 PM closing time."
                    )
                appt.end_time = new_end

        # ── Patient ──────────────────────────────────────────────────────────
        if new_patient_id is not None and new_patient_id != appt.patient_id:
            new_patient = db.get(Patient, new_patient_id)
            if not new_patient:
                return f"Error: patient {new_patient_id} not found."
            old_patient = db.get(Patient, appt.patient_id)
            old_pt_name = f"{old_patient.first_name} {old_patient.last_name}" if old_patient else f"#{appt.patient_id}"
            changes.append(f"  Patient : {old_pt_name} → {new_patient.first_name} {new_patient.last_name}")
            appt.patient_id = new_patient_id

        # ── Status ───────────────────────────────────────────────────────────
        if new_status is not None and new_status != appt.status:
            changes.append(f"  Status  : {appt.status} → {new_status}")
            appt.status = new_status

        # ── Notes ────────────────────────────────────────────────────────────
        if new_notes is not None:
            changes.append(f"  Notes   : updated")
            appt.notes = new_notes or None

        if not changes:
            return "No changes were made — all supplied values match the current appointment."

        db.commit()
        patient = db.get(Patient, appt.patient_id)
        patient_name = f"{patient.first_name} {patient.last_name}" if patient else f"Patient #{appt.patient_id}"
        return (
            f"Appointment {appointment_id} for {patient_name} updated:\n"
            + "\n".join(changes)
        )
    finally:
        db.close()


@tool
def reschedule_appointment(appointment_id: int, new_slot_id: int) -> str:
    """Move an existing appointment to a different available slot.

    The old slot is freed (is_booked = False) and the new slot is reserved.

    Args:
        appointment_id: The ID of the appointment to reschedule.
        new_slot_id:    The ID of the new AvailableSlot to move the appointment to.

    Returns:
        Confirmation string with old and new times, or an error message.
    """
    db = SessionLocal()
    try:
        appt = db.get(Appointment, appointment_id)
        if not appt:
            return f"Error: appointment {appointment_id} not found."

        new_slot = db.get(AvailableSlot, new_slot_id)
        if not new_slot:
            return f"Error: slot {new_slot_id} does not exist."
        if new_slot.is_booked:
            return f"Error: slot {new_slot_id} is already booked. Please choose a different slot."

        # Enforce 5 PM closing time
        appt_type = db.get(AppointmentType, appt.appointment_type_id)
        duration = appt_type.duration_minutes if appt_type else 30
        new_end = new_slot.start_time + timedelta(minutes=duration)
        closing = new_slot.start_time.replace(hour=17, minute=0, second=0, microsecond=0)
        if new_end > closing:
            return (
                f"Error: rescheduling to that slot would end at {new_end.strftime('%I:%M %p')}, "
                f"after the 5:00 PM closing time."
            )

        # Check for overlapping appointments with the same provider (excluding self)
        overlap = (
            db.query(Appointment)
            .filter(
                Appointment.id != appointment_id,
                Appointment.provider_id == new_slot.provider_id,
                Appointment.status.notin_(["cancelled"]),
                Appointment.start_time < new_end,
                Appointment.end_time > new_slot.start_time,
            )
            .first()
        )
        if overlap:
            prov = db.get(Provider, new_slot.provider_id)
            prov_name = f"Dr. {prov.last_name}" if prov else f"Provider #{new_slot.provider_id}"
            return (
                f"Error: {prov_name} already has an appointment from "
                f"{overlap.start_time.strftime('%I:%M %p')} to {overlap.end_time.strftime('%I:%M %p')} "
                f"that overlaps with the new slot. Please choose a different slot."
            )

        old_time = appt.start_time

        # Free the old slot if one exists
        old_slot = (
            db.query(AvailableSlot)
            .filter(
                AvailableSlot.provider_id == appt.provider_id,
                AvailableSlot.start_time == appt.start_time,
            )
            .first()
        )
        if old_slot:
            old_slot.is_booked = False

        # Update the appointment
        appt.start_time = new_slot.start_time
        appt.end_time = new_end
        appt.provider_id = new_slot.provider_id
        appt.location_id = new_slot.location_id
        appt.status = "confirmed"
        new_slot.is_booked = True
        db.commit()

        patient = db.get(Patient, appt.patient_id)
        patient_name = f"{patient.first_name} {patient.last_name}" if patient else f"Patient #{appt.patient_id}"
        provider = db.get(Provider, new_slot.provider_id)
        provider_name = f"Dr. {provider.first_name} {provider.last_name}" if provider else "Provider"
        return (
            f"Appointment {appointment_id} for {patient_name} rescheduled.\n"
            f"  From: {old_time.strftime('%A, %B %d at %I:%M %p')}\n"
            f"  To  : {new_slot.start_time.strftime('%A, %B %d at %I:%M %p')}\n"
            f"  Provider: {provider_name}"
        )
    finally:
        db.close()


@tool
def change_appointment_provider(appointment_id: int, new_provider_id: int) -> str:
    """Change the provider for an existing appointment, keeping the same date and time if possible.

    Tries to find an available slot for the new provider at the exact same start time.
    If no slot exists at that time, returns an error listing the new provider's available slots
    so the agent can ask the user to pick one.

    Args:
        appointment_id: The ID of the appointment to update.
        new_provider_id: The ID of the provider to reassign the appointment to.

    Returns:
        Confirmation string, or an error message with available alternatives.
    """
    db = SessionLocal()
    try:
        appt = db.get(Appointment, appointment_id)
        if not appt:
            return f"Error: appointment {appointment_id} not found."

        new_prov = db.get(Provider, new_provider_id)
        if not new_prov:
            return f"Error: provider {new_provider_id} not found."

        appt_type = db.get(AppointmentType, appt.appointment_type_id)
        duration = appt_type.duration_minutes if appt_type else 30
        orig_start = appt.start_time
        orig_end = appt.end_time

        # Check if the new provider has a free slot at the same time
        conflict = (
            db.query(Appointment)
            .filter(
                Appointment.id != appointment_id,
                Appointment.provider_id == new_provider_id,
                Appointment.status.notin_(["cancelled"]),
                Appointment.start_time < orig_end,
                Appointment.end_time > orig_start,
            )
            .first()
        )

        if not conflict:
            # Reassign directly — keep same times
            old_prov = db.get(Provider, appt.provider_id)
            old_prov_name = f"Dr. {old_prov.last_name}" if old_prov else f"Provider #{appt.provider_id}"

            # Free old slot if one exists
            old_slot = (
                db.query(AvailableSlot)
                .filter(
                    AvailableSlot.provider_id == appt.provider_id,
                    AvailableSlot.start_time == appt.start_time,
                )
                .first()
            )
            if old_slot:
                old_slot.is_booked = False

            appt.provider_id = new_provider_id
            # Update location to match new provider's default location if available
            new_slot_same_time = (
                db.query(AvailableSlot)
                .filter(
                    AvailableSlot.provider_id == new_provider_id,
                    AvailableSlot.start_time == orig_start,
                )
                .first()
            )
            if new_slot_same_time:
                new_slot_same_time.is_booked = True
                appt.location_id = new_slot_same_time.location_id

            db.commit()
            patient = db.get(Patient, appt.patient_id)
            patient_name = f"{patient.first_name} {patient.last_name}" if patient else f"Patient #{appt.patient_id}"
            new_prov_name = f"Dr. {new_prov.first_name} {new_prov.last_name}"
            return (
                f"Provider changed successfully.\n"
                f"  Patient : {patient_name}\n"
                f"  Provider: {old_prov_name} → {new_prov_name}\n"
                f"  Time    : {orig_start.strftime('%A, %B %d at %I:%M %p')} – {orig_end.strftime('%I:%M %p')} (unchanged)"
            )
        else:
            new_prov_name = f"Dr. {new_prov.first_name} {new_prov.last_name}"
            return (
                f"Error: {new_prov_name} already has an appointment at that time "
                f"({conflict.start_time.strftime('%I:%M %p')}–{conflict.end_time.strftime('%I:%M %p')}). "
                f"Use check_available_slots with provider_id={new_provider_id} to find a free slot, "
                f"then use reschedule_appointment to move the appointment to that slot."
            )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Tool registry — maps name → callable and builds OpenAI function schemas
# ---------------------------------------------------------------------------

@tool
def search_clinic_docs(question: str) -> str:
    """Look up clinic policies, insurance, billing, procedures, hours. Answer only from the result and name the source."""
    from app.rag.retrieval import lookup

    return lookup(question)


TOOLS = [
    search_patients,
    add_patient,
    list_all_patients,
    list_patients_by_provider,
    get_patient_appointments,
    get_appointments_for_date,
    check_available_slots,
    book_appointment,
    delete_appointment,
    cancel_appointment,
    modify_appointment,
    get_patient_context,
    get_recall_queue,
    draft_recall_message,
    search_clinic_docs,
]

# {tool_name: callable}  — used to dispatch tool calls from the agent loop
_TOOL_MAP: Dict[str, Callable] = {t.name: t for t in TOOLS}


def _build_openai_schemas() -> List[Dict[str, Any]]:
    """Convert LangChain tool definitions to OpenAI function-calling format."""
    schemas = []
    for lc_tool in TOOLS:
        # LangChain exposes the JSON schema as .args_schema.schema()
        params = lc_tool.args_schema.schema()
        # Remove LangChain's internal $defs nesting if present
        params.pop("title", None)
        params.pop("$defs", None)
        # Ensure 'properties' exists for tools with no required args
        params.setdefault("properties", {})
        params.setdefault("type", "object")
        # Strip auto-generated title fields from each property (redundant with param names)
        for prop in params["properties"].values():
            prop.pop("title", None)
        schemas.append(
            {
                "type": "function",
                "function": {
                    "name": lc_tool.name,
                    "description": (lc_tool.description or "").strip(),
                    "parameters": params,
                },
            }
        )
    return schemas


OPENAI_TOOL_SCHEMAS = _build_openai_schemas()

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are DentalAI, a dental practice scheduling assistant. "
    "Only help with dental practice tasks (scheduling, patients, recalls, appointments). "
    "Politely decline anything else.\n\n"
    "Tool usage rules:\n"
    "- Patient names: call search_patients first. "
    "Exception: 'patient 1', 'patient 3', numeric IDs — use patient_id directly, never call search_patients.\n"
    "- Patient appointment checks: use get_patient_appointments(patient_id), "
    "not get_appointments_for_date per day.\n"
    "- 'delete'/'remove' → delete_appointment. 'cancel' → cancel_appointment.\n"
    "- All edits and reschedules: use modify_appointment. "
    "To reschedule: call check_available_slots first, then pass new_slot_id.\n"
    "- appointment_type_id: use 1 (Cleaning) unless the user specifies otherwise.\n"
    "- Clinic policy, insurance, billing, procedure or hours questions: call search_clinic_docs "
    "and answer only from its text, naming the source. If it finds nothing, say you do not have "
    "that information and suggest calling the office. Do not use it for booking.\n\n"
    f"Today: {datetime.utcnow().strftime('%Y-%m-%d')}. "
    f"Slots available through {(datetime.utcnow() + timedelta(days=27)).strftime('%Y-%m-%d')} (28 days). "
    "Resolve relative dates (today/tomorrow/weekday names) to YYYY-MM-DD before calling tools.\n\n"
    "IMPORTANT — out-of-range dates: if the requested date is beyond the 28-day window, "
    "do NOT call check_available_slots — tell the user the date is outside the scheduling window.\n\n"
    "IMPORTANT — office hours: practice closes at 5 PM. "
    "Never book a slot whose end time exceeds 17:00.\n\n"
    "IMPORTANT — booking flow:\n"
    "1. After presenting a slot list, keep each slot_id mapped to its list number.\n"
    "2. When the user picks a slot by number, use that slot_id directly in book_appointment — "
    "do NOT re-query check_available_slots (re-querying changes ordering and books the wrong slot).\n"
)

# ---------------------------------------------------------------------------
# OpenAI client (lazy — instantiated on first use)
# ---------------------------------------------------------------------------

_groq_client: Optional[Groq] = None


def _get_client() -> Groq:
    global _groq_client
    if _groq_client is None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "GROQ_API_KEY is not set. Add it to backend/.env and restart."
            )
        _groq_client = Groq(api_key=api_key)
        logger.info("[AGENT] Groq client initialised (model=openai/gpt-oss-20b)")
    return _groq_client


# ---------------------------------------------------------------------------
# Public run function
# ---------------------------------------------------------------------------


# Groq sometimes rejects the model's own tool call with a 400 "Failed to parse
# tool call arguments as JSON". It is intermittent, so a resample usually works.
_TOOL_PARSE_RETRIES = 2
_TOOL_PARSE_RETRY_TEMPERATURE = 0.3  # temperature 0 may repeat the same bad output


def is_tool_parse_error(exc: BaseException) -> bool:
    """True for Groq's 400 about malformed tool-call JSON (not for 413 or other 4xx)."""
    return (
        getattr(exc, "status_code", None) == 400
        and "failed to parse tool call arguments" in str(exc).lower()
    )


def run_agent(message: str, session_id: str) -> Dict[str, Any]:
    """Invoke the agent with a user message and return structured output.

    Implements a multi-turn function-calling loop:
      1. Appends the user message to session history.
      2. Calls the OpenAI API with all accumulated messages + tool schemas.
      3. If the model calls tools, executes them and feeds results back.
      4. Repeats until the model produces a plain-text "stop" response or
         MAX_ITERATIONS is reached.

    Args:
        message:    The user's natural-language request.
        session_id: Identifies the conversation thread for memory continuity.

    Returns:
        {
            "response":   str,
            "tool_calls": [{"tool": str, "input": dict, "output": str}]
        }
    """
    client = _get_client()
    history = _get_history(session_id)
    history_len = len(history)  # snapshot before this turn

    # Keep only the last 10 history messages to stay within the 8k TPM limit.
    # Also truncate any tool result content that is unusually long.
    MAX_TOOL_OUTPUT_CHARS = 1500
    MAX_HISTORY_MSGS = 10

    def _trim_msg(m: Dict[str, Any]) -> Dict[str, Any]:
        if m.get("role") == "tool" and isinstance(m.get("content"), str):
            if len(m["content"]) > MAX_TOOL_OUTPUT_CHARS:
                return {**m, "content": m["content"][:MAX_TOOL_OUTPUT_CHARS] + "\n…(truncated)"}
        return m

    trimmed_history = [_trim_msg(m) for m in history[-MAX_HISTORY_MSGS:]]

    # Build the full messages list: system prompt + session history + new turn
    messages: List[ChatCompletionMessageParam] = (
        [{"role": "system", "content": _SYSTEM_PROMPT}]
        + trimmed_history  # type: ignore[arg-type]
        + [{"role": "user", "content": message}]
    )

    tool_call_log: List[Dict[str, Any]] = []
    _tokens: Dict[str, int] = {"prompt": 0, "completion": 0}
    _parse_retries = [0]  # tool-call JSON retries used this turn (reported in the result)

    def _parse_retry_wait(exc_str: str) -> float:
        """Parse 'try again in Xm Y.Zs' or 'try again in Y.Zs' → total seconds."""
        m = re.search(r'try again in (?:(\d+)m)?([\d.]+)s', exc_str, re.IGNORECASE)
        if m:
            minutes = float(m.group(1) or 0)
            seconds = float(m.group(2) or 0)
            return minutes * 60 + seconds
        return 30.0

    def _chat_create_with_retry(
        msgs: List[ChatCompletionMessageParam], temperature: float = 0
    ) -> Any:
        """Call Groq with manual 429 retry so we can surface wait time to the frontend."""
        import groq as _groq_mod
        max_retries = 3
        for attempt in range(max_retries):
            try:
                result = client.chat.completions.create(
                    model="openai/gpt-oss-20b",
                    messages=msgs,
                    tools=OPENAI_TOOL_SCHEMAS,  # type: ignore[arg-type]
                    tool_choice="auto",
                    temperature=temperature,
                )
                clear_retry_status(session_id)
                if result.usage:
                    _tokens["prompt"] += result.usage.prompt_tokens or 0
                    _tokens["completion"] += result.usage.completion_tokens or 0
                return result
            except _groq_mod.RateLimitError as exc:
                wait = _parse_retry_wait(str(exc))
                logger.info("[AGENT] Groq 429 — wait=%.0fs (session=%s)", wait, session_id)
                # Daily/large limits (>5 min) — don't retry, surface immediately
                if wait > 300:
                    clear_retry_status(session_id)
                    mins = int(wait // 60)
                    secs = int(wait % 60)
                    raise RuntimeError(
                        f"The AI provider's daily token limit has been reached. "
                        f"Please try again in {mins}m {secs}s."
                    ) from exc
                set_retry_status(session_id, wait)
                if attempt < max_retries - 1:
                    time.sleep(wait)
                else:
                    clear_retry_status(session_id)
                    raise
            except _groq_mod.BadRequestError as exc:
                clear_retry_status(session_id)
                # Re-raise as a labelled RuntimeError only for true 413s so the
                # eval harness can detect them by text (RuntimeError has no
                # status_code).  Any other 4xx (e.g. bad tool-call JSON → 400)
                # is re-raised as-is so is_size_error() sees status_code=400
                # and correctly returns False, counting it as an agent failure.
                if getattr(exc, "status_code", None) == 413:
                    raise RuntimeError(f"413 Request too large: {exc}") from exc
                raise
            except Exception:
                clear_retry_status(session_id)
                raise

    def _chat_create_resilient(msgs: List[ChatCompletionMessageParam]) -> Any:
        """Retry (resampled) when Groq rejects the model's tool-call JSON; the
        429 handling stays inside _chat_create_with_retry. Message content is
        never logged."""
        for attempt in range(_TOOL_PARSE_RETRIES + 1):
            try:
                return _chat_create_with_retry(
                    msgs, temperature=0 if attempt == 0 else _TOOL_PARSE_RETRY_TEMPERATURE
                )
            except Exception as exc:
                if attempt < _TOOL_PARSE_RETRIES and is_tool_parse_error(exc):
                    _parse_retries[0] += 1
                    logger.warning(
                        "[AGENT] Groq 400 tool-call JSON parse failure — retry %d/%d (session=%s)",
                        attempt + 1, _TOOL_PARSE_RETRIES, session_id,
                    )
                    continue
                raise

    for iteration in range(MAX_ITERATIONS):
        response = _chat_create_resilient(messages)
        choice = response.choices[0]

        if choice.finish_reason == "stop":
            # Model is done — extract the final answer
            final_answer = choice.message.content or ""
            break

        if choice.finish_reason == "tool_calls":
            # Append the assistant's tool-call message to the conversation
            # Build manually to avoid unsupported fields (annotations, executed_tools, etc.)
            assistant_msg = choice.message
            assistant_dict: Dict[str, Any] = {
                "role": "assistant",
                "content": assistant_msg.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in (assistant_msg.tool_calls or [])
                ],
            }
            messages.append(assistant_dict)  # type: ignore[arg-type]

            # Execute every tool call the model requested in this round
            for tc in assistant_msg.tool_calls or []:
                tool_name = tc.function.name
                tool_input_raw = tc.function.arguments  # JSON string

                try:
                    tool_input = json.loads(tool_input_raw)
                except json.JSONDecodeError:
                    tool_input = {}

                # Dispatch to the matching LangChain tool
                if tool_name in _TOOL_MAP:
                    try:
                        tool_output = _TOOL_MAP[tool_name].invoke(tool_input)
                    except Exception as exc:
                        tool_output = f"Tool error: {exc}"
                else:
                    tool_output = f"Unknown tool: {tool_name}"

                # Log for the response payload
                tool_call_log.append(
                    {"tool": tool_name, "input": tool_input, "output": str(tool_output)}
                )
                keys = list(tool_input.keys()) if isinstance(tool_input, dict) else []
                logger.info("[AGENT] tool_call=%s input_keys=%s", tool_name, keys)

                # Feed the tool result back as a "tool" role message
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": str(tool_output),
                    }
                )
            continue  # next iteration to let the model reason over results

        # Unexpected finish reason — break and return whatever we have
        final_answer = choice.message.content or f"[finished: {choice.finish_reason}]"
        break
    else:
        final_answer = "Agent reached maximum iterations without a final answer."

    # Persist this full turn: user msg + tool call interleave + final answer.
    # Saving tool call messages lets the next turn see which slots were returned,
    # so the model doesn't lose context and ask redundant questions.
    new_messages = messages[1 + history_len:]  # skip system prompt + old history
    history.extend(new_messages)
    history.append({"role": "assistant", "content": final_answer})

    logger.info(
        "[AGENT] session=%s tools_used=%s response_len=%d",
        session_id,
        [tc["tool"] for tc in tool_call_log],
        len(final_answer),
    )

    return {
        "response": final_answer,
        "tool_calls": tool_call_log,
        "prompt_tokens": _tokens["prompt"],
        "completion_tokens": _tokens["completion"],
        "tool_parse_retries": _parse_retries[0],
    }
