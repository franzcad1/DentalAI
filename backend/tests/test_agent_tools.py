"""Unit tests for agent tool functions — no API key required.

All tests use the `agent_db` fixture from conftest.py which:
- spins up a fresh in-memory SQLite database per test
- patches app.agent.agent.SessionLocal to point at it
- seeds one provider, one location, two appointment types, two patients,
  one future slot, and one overdue recall

Run with: cd backend && py -m pytest tests/test_agent_tools.py -v
"""

import json
from datetime import datetime, timedelta

import pytest


# ---------------------------------------------------------------------------
# check_available_slots
# ---------------------------------------------------------------------------


def test_check_slots_returns_open_slot(agent_db):
    from app.agent.agent import check_available_slots

    date_from = (datetime.utcnow() + timedelta(days=1)).strftime("%Y-%m-%d")
    date_to = (datetime.utcnow() + timedelta(days=7)).strftime("%Y-%m-%d")

    result = json.loads(check_available_slots.invoke({"date_from": date_from, "date_to": date_to, "provider_id": 0}))
    assert len(result) == 1
    assert "Dr. Alice Smith" in result[0]["provider_name"]


def test_check_slots_empty_when_no_slots_in_range(agent_db):
    from app.agent.agent import check_available_slots

    # Search a date range in the past — tool returns a plain "no results" string
    result = check_available_slots.invoke({"date_from": "2020-01-01", "date_to": "2020-01-07", "provider_id": 0})
    assert "no available slots" in result.lower()


def test_check_slots_filter_by_provider(agent_db):
    from app.agent.agent import check_available_slots

    date_from = (datetime.utcnow() + timedelta(days=1)).strftime("%Y-%m-%d")
    date_to = (datetime.utcnow() + timedelta(days=7)).strftime("%Y-%m-%d")

    # provider_id=999 doesn't exist — tool returns a plain "no results" string
    result = check_available_slots.invoke({"date_from": date_from, "date_to": date_to, "provider_id": 999})
    assert "no available slots" in result.lower()


# ---------------------------------------------------------------------------
# book_appointment
# ---------------------------------------------------------------------------


def test_book_appointment_success(agent_db):
    from app.agent.agent import book_appointment
    from app.models.orm import AvailableSlot

    result = book_appointment.invoke({"patient_id": 1, "slot_id": 1, "appointment_type_id": 1, "notes": "First visit"})
    assert "booked successfully" in result.lower()
    assert "John Doe" in result

    db = agent_db()
    try:
        slot = db.get(AvailableSlot, 1)
        assert slot.is_booked is True
    finally:
        db.close()


def test_book_appointment_rejects_double_booking(agent_db):
    from app.agent.agent import book_appointment

    book_appointment.invoke({"patient_id": 1, "slot_id": 1, "appointment_type_id": 1, "notes": ""})
    result = book_appointment.invoke({"patient_id": 2, "slot_id": 1, "appointment_type_id": 1, "notes": ""})
    assert "already booked" in result.lower()


def test_book_appointment_unknown_slot(agent_db):
    from app.agent.agent import book_appointment

    result = book_appointment.invoke({"patient_id": 1, "slot_id": 9999, "appointment_type_id": 1, "notes": ""})
    assert "not found" in result.lower() or "error" in result.lower()


def test_book_appointment_unknown_patient(agent_db):
    from app.agent.agent import book_appointment

    result = book_appointment.invoke({"patient_id": 9999, "slot_id": 1, "appointment_type_id": 1, "notes": ""})
    assert "not found" in result.lower() or "error" in result.lower()


# ---------------------------------------------------------------------------
# get_patient_context
# ---------------------------------------------------------------------------


def test_get_patient_context_includes_recall(agent_db):
    from app.agent.agent import get_patient_context

    result = json.loads(get_patient_context.invoke({"patient_id": 1}))
    assert result["patient"]["name"] == "John Doe"
    assert result["recall"]["recall_type"] == "6-month cleaning"
    assert result["recall"]["days_overdue"] > 0


def test_get_patient_context_unknown_patient(agent_db):
    from app.agent.agent import get_patient_context

    result = get_patient_context.invoke({"patient_id": 9999})
    assert "not found" in result.lower() or "error" in result.lower()


def test_get_patient_context_no_recall(agent_db):
    from app.agent.agent import get_patient_context

    # Patient 2 (Jane Roe) has no recall seeded
    result = json.loads(get_patient_context.invoke({"patient_id": 2}))
    assert result["patient"]["name"] == "Jane Roe"
    assert result.get("recall") is None or result.get("recall") == {}


# ---------------------------------------------------------------------------
# get_recall_queue
# ---------------------------------------------------------------------------


def test_get_recall_queue_returns_overdue(agent_db):
    from app.agent.agent import get_recall_queue

    result = json.loads(get_recall_queue.invoke({}))
    assert len(result) == 1
    assert result[0]["name"] == "John Doe"
    assert result[0]["days_overdue"] > 0


def test_get_recall_queue_empty_when_no_recalls(agent_db):
    from app.agent.agent import get_recall_queue
    from app.models.orm import PatientRecall

    # Remove the seeded recall
    db = agent_db()
    try:
        db.query(PatientRecall).delete()
        db.commit()
    finally:
        db.close()

    # Tool returns a plain "no results" string when the queue is empty
    result = get_recall_queue.invoke({})
    assert "no" in result.lower() or "recall" in result.lower()


# ---------------------------------------------------------------------------
# search_patients
# ---------------------------------------------------------------------------


def test_search_patients_found(agent_db):
    from app.agent.agent import search_patients

    result = json.loads(search_patients.invoke({"name": "John"}))
    assert any(p["name"] == "John Doe" for p in result)


def test_search_patients_not_found(agent_db):
    from app.agent.agent import search_patients

    result = search_patients.invoke({"name": "Zzzunknown"})
    # Either an empty list or a "no results" message string
    try:
        parsed = json.loads(result)
        assert parsed == []
    except (ValueError, TypeError):
        assert "no" in result.lower() or "not found" in result.lower()


# ---------------------------------------------------------------------------
# draft_recall_message
# ---------------------------------------------------------------------------


def test_draft_recall_message_personalised(agent_db):
    from app.agent.agent import draft_recall_message

    result = draft_recall_message.invoke({"patient_id": 1})
    assert "John" in result
    assert "cleaning" in result.lower()
    assert "overdue" in result.lower()


def test_draft_recall_message_unknown_patient(agent_db):
    from app.agent.agent import draft_recall_message

    result = draft_recall_message.invoke({"patient_id": 9999})
    assert "not found" in result.lower() or "error" in result.lower()


# ---------------------------------------------------------------------------
# cancel_appointment
# ---------------------------------------------------------------------------


def test_cancel_appointment_sets_status(agent_db):
    from app.agent.agent import book_appointment, cancel_appointment
    from app.models.orm import Appointment

    book_appointment.invoke({"patient_id": 1, "slot_id": 1, "appointment_type_id": 1, "notes": ""})

    result = cancel_appointment.invoke({"appointment_id": 1})
    assert "cancel" in result.lower()

    db = agent_db()
    try:
        appt = db.get(Appointment, 1)
        assert appt.status == "cancelled"
    finally:
        db.close()


def test_cancel_appointment_unknown_id(agent_db):
    from app.agent.agent import cancel_appointment

    result = cancel_appointment.invoke({"appointment_id": 9999})
    assert "not found" in result.lower() or "error" in result.lower()


# ---------------------------------------------------------------------------
# list_all_patients
# ---------------------------------------------------------------------------


def test_list_all_patients_returns_both(agent_db):
    from app.agent.agent import list_all_patients

    result = json.loads(list_all_patients.invoke({}))
    names = [p["name"] for p in result]
    assert "John Doe" in names
    assert "Jane Roe" in names
