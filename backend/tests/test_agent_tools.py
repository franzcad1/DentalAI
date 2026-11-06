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
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
import app.models.orm  # noqa: F401
from app.models.orm import AvailableSlot, Location, Provider


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


def test_agent_fixed_overhead_within_budget():
    """System prompt + tool schemas must stay under 2500 estimated tokens.

    Uses chars // 4 as a rough approximation (~4 chars per token for English).
    Fails fast if someone adds a verbose docstring or a new tool without trimming.
    Budget: 2500 tokens leaves ~300 tokens of headroom above the current ~1923.
    """
    import json as _json
    from app.agent.agent import _SYSTEM_PROMPT, OPENAI_TOOL_SCHEMAS

    schema_str = _json.dumps(OPENAI_TOOL_SCHEMAS)
    estimated = (len(_SYSTEM_PROMPT) + len(schema_str)) // 4
    assert estimated <= 2500, (
        f"Fixed overhead ~{estimated} tokens exceeds budget of 2500. "
        f"Prompt ≈{len(_SYSTEM_PROMPT) // 4} tokens, "
        f"schemas ≈{len(schema_str) // 4} tokens. "
        "Trim tool descriptions or system prompt."
    )


def test_check_slots_capped_at_ten():
    """check_available_slots must return at most 10 slots regardless of DB size."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    db = TestSession()
    try:
        provider = Provider(first_name="Bob", last_name="Jones", specialty="General")
        location = Location(name="Office", address="1 Main", phone="555-0101")
        db.add_all([provider, location])
        db.flush()

        # Seed 15 unbooked slots spread over the next 3 days
        base = datetime.utcnow().replace(hour=8, minute=0, second=0, microsecond=0)
        for i in range(15):
            start = base + timedelta(days=1, hours=i % 8)
            db.add(AvailableSlot(
                provider_id=provider.id,
                location_id=location.id,
                start_time=start,
                end_time=start + timedelta(minutes=30),
                is_booked=False,
            ))
        db.commit()
    finally:
        db.close()

    with patch("app.agent.agent.SessionLocal", TestSession), \
         patch("app.events.bus.SessionLocal", TestSession):
        from app.agent.agent import check_available_slots
        date_from = (datetime.utcnow() + timedelta(days=1)).strftime("%Y-%m-%d")
        date_to = (datetime.utcnow() + timedelta(days=4)).strftime("%Y-%m-%d")
        result = json.loads(check_available_slots.invoke({"date_from": date_from, "date_to": date_to}))

    assert len(result) <= 10, f"Expected at most 10 slots, got {len(result)}"

    Base.metadata.drop_all(bind=engine)
    engine.dispose()


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


# ---------------------------------------------------------------------------
# Groq 400 "Failed to parse tool call arguments as JSON": bounded resample retry
# ---------------------------------------------------------------------------

def _groq_400(message: str, status: int = 400):
    import groq
    import httpx

    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    response = httpx.Response(status, request=request)
    return groq.BadRequestError(message, response=response, body=None)


class _FakeCompletions:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.temperatures = []

    def create(self, **kwargs):
        self.temperatures.append(kwargs.get("temperature"))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _fake_ok(text="all good"):
    from types import SimpleNamespace as NS

    message = NS(content=text, tool_calls=None)
    return NS(
        choices=[NS(finish_reason="stop", message=message)],
        usage=NS(prompt_tokens=10, completion_tokens=2),
    )


def _run_with_fake_groq(monkeypatch, outcomes, session):
    from types import SimpleNamespace as NS
    import app.agent.agent as agent_mod

    completions = _FakeCompletions(outcomes)
    fake_client = NS(chat=NS(completions=completions))
    monkeypatch.setattr(agent_mod, "_get_client", lambda: fake_client)
    return completions, agent_mod.run_agent("hello", session_id=session)


def test_is_tool_parse_error_only_matches_the_specific_400():
    from app.agent.agent import is_tool_parse_error

    assert is_tool_parse_error(_groq_400("Failed to parse tool call arguments as JSON"))
    assert not is_tool_parse_error(_groq_400("some other bad request"))
    assert not is_tool_parse_error(_groq_400("Failed to parse tool call arguments as JSON", status=413))
    assert not is_tool_parse_error(RuntimeError("Failed to parse tool call arguments as JSON"))


def test_tool_parse_400_is_retried_with_resample_then_succeeds(monkeypatch):
    bad = _groq_400("Failed to parse tool call arguments as JSON")
    completions, result = _run_with_fake_groq(monkeypatch, [bad, _fake_ok()], "retry-ok")
    assert result["response"] == "all good"
    assert result["tool_parse_retries"] == 1
    assert completions.temperatures == [0, 0.3]


def test_tool_parse_400_gives_up_after_bounded_retries(monkeypatch):
    import groq
    import pytest

    bad = lambda: _groq_400("Failed to parse tool call arguments as JSON")  # noqa: E731
    with pytest.raises(groq.BadRequestError):
        _run_with_fake_groq(monkeypatch, [bad(), bad(), bad(), _fake_ok()], "retry-giveup")


def test_other_400_is_not_retried(monkeypatch):
    import groq
    import pytest
    from types import SimpleNamespace as NS
    import app.agent.agent as agent_mod

    completions = _FakeCompletions([_groq_400("invalid something else"), _fake_ok()])
    monkeypatch.setattr(agent_mod, "_get_client", lambda: NS(chat=NS(completions=completions)))
    with pytest.raises(groq.BadRequestError):
        agent_mod.run_agent("hello", session_id="no-retry")
    assert len(completions.temperatures) == 1
