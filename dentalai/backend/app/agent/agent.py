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
from datetime import datetime, date, timedelta
from typing import Any, Callable, Dict, List, Optional

from dotenv import load_dotenv
from langchain_core.tools import tool
from openai import OpenAI
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
    """Return all unbooked appointment slots between date_from and date_to.

    Args:
        date_from:   Start date (inclusive) in YYYY-MM-DD format.
        date_to:     End date (inclusive) in YYYY-MM-DD format.
        provider_id: Optional provider filter. Pass 0 to search all providers.

    Returns:
        JSON-encoded list of available slots with slot_id, provider_id,
        provider_name, location_id, start_time, and end_time.
    """
    d_from = _parse_date(date_from)
    d_to = _parse_date(date_to)

    db = SessionLocal()
    try:
        q = (
            db.query(AvailableSlot)
            .filter(AvailableSlot.is_booked == False)  # noqa: E712
            .filter(
                AvailableSlot.start_time
                >= datetime(d_from.year, d_from.month, d_from.day)
            )
            .filter(
                AvailableSlot.start_time
                < datetime(d_to.year, d_to.month, d_to.day) + timedelta(days=1)
            )
        )
        if provider_id and provider_id != 0:
            q = q.filter(AvailableSlot.provider_id == provider_id)

        slots = q.order_by(AvailableSlot.start_time).limit(50).all()

        result = []
        for s in slots:
            provider = db.get(Provider, s.provider_id)
            provider_name = (
                f"Dr. {provider.first_name} {provider.last_name}"
                if provider
                else "Unknown"
            )
            result.append(
                {
                    "slot_id": s.id,
                    "provider_id": s.provider_id,
                    "provider_name": provider_name,
                    "location_id": s.location_id,
                    "start_time": s.start_time.isoformat(),
                    "end_time": s.end_time.isoformat(),
                }
            )

        if not result:
            return "No available slots found for the requested date range and provider."
        return json.dumps(result, indent=2)
    finally:
        db.close()


@tool
def book_appointment(
    patient_id: int,
    slot_id: int,
    appointment_type_id: int,
    notes: str = "",
) -> str:
    """Book an appointment for a patient using a specific available slot.

    Args:
        patient_id:           ID of the patient to book for.
        slot_id:              ID of the AvailableSlot to reserve.
        appointment_type_id:  ID of the appointment type (cleaning, exam, etc.).
        notes:                Optional clinical or scheduling notes.

    Returns:
        Confirmation string with the new appointment_id and key details,
        or an error message if the slot is already taken.
    """
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
    """Retrieve a full context summary for a patient.

    Includes demographics, their most recent appointment, and current recall status.

    Args:
        patient_id: The patient's ID.

    Returns:
        JSON object with keys: patient, last_appointment, recall.
    """
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
                "recall_id": recall.id,
                "recall_type": recall.recall_type,
                "due_date": str(recall.due_date),
                "status": recall.status,
                "days_overdue": days_overdue if days_overdue > 0 else 0,
            }

        return json.dumps(
            {
                "patient": {
                    "id": patient.id,
                    "name": f"{patient.first_name} {patient.last_name}",
                    "dob": str(patient.dob) if patient.dob else None,
                    "email": patient.email,
                    "phone": patient.phone,
                },
                "last_appointment": last_appt_data,
                "recall": recall_data,
            },
            indent=2,
        )
    finally:
        db.close()


@tool
def get_recall_queue() -> str:
    """Return all patients with pending overdue recalls, most overdue first.

    Only includes recalls whose due_date is strictly in the past and status
    is still 'pending'. Sorted by days_overdue descending.

    Returns:
        JSON list with patient_id, name, recall_type, due_date, days_overdue.
    """
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
        return json.dumps(result, indent=2)
    finally:
        db.close()


@tool
def draft_recall_message(patient_id: int) -> str:
    """Draft a personalised recall outreach message for a patient.

    Tone escalates with how overdue the recall is:
      ≤30 days  → gentle reminder
      31-90 days → moderate nudge
      >90 days  → urgent outreach

    Args:
        patient_id: The patient's ID.

    Returns:
        A plain-text recall message ready to be sent by SMS or email.
    """
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


# ---------------------------------------------------------------------------
# Tool registry — maps name → callable and builds OpenAI function schemas
# ---------------------------------------------------------------------------

TOOLS = [
    check_available_slots,
    book_appointment,
    get_patient_context,
    get_recall_queue,
    draft_recall_message,
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
    "You are DentalAI, an intelligent scheduling and recall assistant for a dental practice.\n\n"
    "You have access to the practice's live appointment system and patient records. Use your tools to:\n"
    "- Find open appointment slots for patients\n"
    "- Book appointments when asked (confirm patient name and time before finalising)\n"
    "- Retrieve patient history and recall status\n"
    "- Identify overdue patients who need outreach\n"
    "- Draft personalised recall messages\n\n"
    "When discussing appointment times, use a human-friendly format like "
    "'Monday, June 3 at 10:00 AM'. If a tool returns an error, explain it clearly "
    "and suggest alternatives."
)

# ---------------------------------------------------------------------------
# OpenAI client (lazy — instantiated on first use)
# ---------------------------------------------------------------------------

_openai_client: Optional[OpenAI] = None


def _get_client() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "OPENAI_API_KEY is not set. Add it to backend/.env and restart."
            )
        _openai_client = OpenAI(api_key=api_key)
        logger.info("[AGENT] OpenAI client initialised (model=gpt-4o-mini)")
    return _openai_client


# ---------------------------------------------------------------------------
# Public run function
# ---------------------------------------------------------------------------


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

    # Build the full messages list: system prompt + session history + new turn
    messages: List[ChatCompletionMessageParam] = (
        [{"role": "system", "content": _SYSTEM_PROMPT}]
        + history  # type: ignore[arg-type]
        + [{"role": "user", "content": message}]
    )

    tool_call_log: List[Dict[str, Any]] = []

    for iteration in range(MAX_ITERATIONS):
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            tools=OPENAI_TOOL_SCHEMAS,  # type: ignore[arg-type]
            tool_choice="auto",
            temperature=0,
        )
        choice = response.choices[0]

        if choice.finish_reason == "stop":
            # Model is done — extract the final answer
            final_answer = choice.message.content or ""
            break

        if choice.finish_reason == "tool_calls":
            # Append the assistant's tool-call message to the conversation
            assistant_msg = choice.message
            messages.append(assistant_msg.model_dump())  # type: ignore[arg-type]

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
                logger.info("[AGENT] tool_call=%s input=%s", tool_name, tool_input)

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

    # Persist this turn in the session history (without the system prompt)
    history.append({"role": "user", "content": message})
    history.append({"role": "assistant", "content": final_answer})

    logger.info(
        "[AGENT] session=%s tools_used=%s response_len=%d",
        session_id,
        [tc["tool"] for tc in tool_call_log],
        len(final_answer),
    )

    return {"response": final_answer, "tool_calls": tool_call_log}
