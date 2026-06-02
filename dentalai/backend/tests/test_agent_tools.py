"""Unit tests for agent tool functions — no OpenAI API key required.

These tests call the tool functions directly (bypassing the LangChain executor)
to verify DB interactions and response shapes are correct.

Run with: cd backend && py -m pytest tests/test_agent_tools.py -v
"""

import json
from datetime import datetime, timedelta

import pytest

from app.db.session import Base, SessionLocal, engine
from app.models.orm import (
    AppointmentType,
    AvailableSlot,
    Location,
    Patient,
    PatientRecall,
    Provider,
)


@pytest.fixture(autouse=True)
def fresh_db():
    """Drop and recreate all tables for each test for isolation."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        # Seed minimal fixtures
        provider = Provider(first_name="Alice", last_name="Smith", specialty="General")
        location = Location(name="Main Office", address="123 Main St", phone="555-0100")
        db.add_all([provider, location])
        db.flush()

        appt_types = [
            AppointmentType(name="cleaning", duration_minutes=45),
            AppointmentType(name="exam", duration_minutes=30),
        ]
        db.add_all(appt_types)

        patients = [
            Patient(first_name="John", last_name="Doe", email="john@example.com"),
            Patient(first_name="Jane", last_name="Roe", email="jane@example.com"),
        ]
        db.add_all(patients)
        db.flush()

        # Create a slot 3 days from now
        slot_time = datetime.utcnow() + timedelta(days=3)
        slot = AvailableSlot(
            provider_id=provider.id,
            location_id=location.id,
            start_time=slot_time,
            end_time=slot_time + timedelta(minutes=30),
            is_booked=False,
        )
        db.add(slot)

        # Overdue recall for patient 1
        from datetime import date
        recall = PatientRecall(
            patient_id=patients[0].id,
            recall_type="6-month cleaning",
            due_date=date(2024, 1, 1),
            status="pending",
        )
        db.add(recall)

        db.commit()
    finally:
        db.close()

    yield


def test_check_available_slots_returns_open_slot():
    from app.agent.agent import check_available_slots

    date_from = (datetime.utcnow() + timedelta(days=1)).strftime("%Y-%m-%d")
    date_to = (datetime.utcnow() + timedelta(days=7)).strftime("%Y-%m-%d")

    result = check_available_slots.invoke({"date_from": date_from, "date_to": date_to, "provider_id": 0})
    parsed = json.loads(result)
    assert len(parsed) == 1
    assert parsed[0]["slot_id"] == 1
    assert "Dr. Alice Smith" in parsed[0]["provider_name"]


def test_get_recall_queue_returns_overdue():
    from app.agent.agent import get_recall_queue

    result = get_recall_queue.invoke({})
    parsed = json.loads(result)
    assert len(parsed) == 1
    assert parsed[0]["name"] == "John Doe"
    assert parsed[0]["days_overdue"] > 0


def test_get_patient_context_includes_recall():
    from app.agent.agent import get_patient_context

    result = get_patient_context.invoke({"patient_id": 1})
    parsed = json.loads(result)
    assert parsed["patient"]["name"] == "John Doe"
    assert parsed["recall"]["recall_type"] == "6-month cleaning"
    assert parsed["recall"]["days_overdue"] > 0


def test_draft_recall_message_is_personalised():
    from app.agent.agent import draft_recall_message

    result = draft_recall_message.invoke({"patient_id": 1})
    assert "John" in result
    assert "cleaning" in result.lower()
    # Should escalate to urgent since way overdue
    assert "overdue" in result.lower()


def test_book_appointment_creates_record_and_marks_slot():
    from app.agent.agent import book_appointment

    result = book_appointment.invoke(
        {"patient_id": 1, "slot_id": 1, "appointment_type_id": 1, "notes": "First visit"}
    )
    assert "booked successfully" in result.lower()
    assert "John Doe" in result

    # Verify the slot is now marked as booked
    db = SessionLocal()
    try:
        slot = db.get(AvailableSlot, 1)
        assert slot.is_booked is True
    finally:
        db.close()


def test_book_appointment_rejects_double_booking():
    from app.agent.agent import book_appointment

    # Book once
    book_appointment.invoke(
        {"patient_id": 1, "slot_id": 1, "appointment_type_id": 1, "notes": ""}
    )
    # Try to book the same slot again
    result = book_appointment.invoke(
        {"patient_id": 2, "slot_id": 1, "appointment_type_id": 1, "notes": ""}
    )
    assert "already booked" in result.lower()
