"""End-to-end agent tests.

These tests call run_agent() directly and require GROQ_API_KEY to be set
in the environment or in backend/.env.  They consume live Groq quota and
write to an isolated e2e_test.db that is deleted after the session.
dentalai.db is never opened.

Routine (offline) runs should skip this file:
    cd backend && py -m pytest tests --ignore=tests/test_agent_e2e.py

E2E-only run:
    cd backend && py -m pytest tests/test_agent_e2e.py -v -s
"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

# Skip the entire module if no API key is available.
pytestmark = pytest.mark.skipif(
    not os.getenv("GROQ_API_KEY"),
    reason="GROQ_API_KEY not set — skipping live agent tests",
)


@pytest.fixture(scope="module")
def seeded_db():
    """Seed an isolated e2e_test.db and patch every SessionLocal so
    the agent never touches dentalai.db or any other dev database.

    Patches applied for the lifetime of the module:
      - app.db.seed.engine / SessionLocal  → e2e_test.db engine/session
      - app.agent.agent.SessionLocal       → e2e_test.db session
      - app.events.bus.SessionLocal        → e2e_test.db session

    e2e_test.db is deleted on teardown.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import app.db.seed as _seed_mod

    db_path = (Path(__file__).parent.parent / "e2e_test.db").resolve()
    e2e_engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    E2ESession = sessionmaker(autocommit=False, autoflush=False, bind=e2e_engine)

    with patch.object(_seed_mod, "engine", e2e_engine), \
         patch.object(_seed_mod, "SessionLocal", E2ESession), \
         patch("app.agent.agent.SessionLocal", E2ESession), \
         patch("app.events.bus.SessionLocal", E2ESession):
        _seed_mod.run_seed()
        yield E2ESession

    e2e_engine.dispose()
    if db_path.exists():
        db_path.unlink()


@pytest.mark.e2e
def test_book_cleaning_for_patient_3(seeded_db):
    """Agent should find an open slot this week and book a cleaning for patient 3."""
    from app.agent.agent import run_agent

    result = run_agent(
        "Yes please book a cleaning for patient 3 with any available provider this week."
        " Go ahead and confirm it, no need to ask me.",
        session_id="e2e-booking",
    )

    print("\n--- RESPONSE ---")
    print(result["response"])
    print("\n--- TOOL CALLS ---")
    for tc in result["tool_calls"]:
        print(f"  {tc['tool']}({tc['input']}) → {tc['output'][:120]}")

    tool_names = [tc["tool"] for tc in result["tool_calls"]]
    assert "check_available_slots" in tool_names, "Expected slot search"
    assert "book_appointment" in tool_names, "Expected booking"
    assert "patient" in result["response"].lower() or "book" in result["response"].lower()


@pytest.mark.e2e
def test_most_overdue_recalls(seeded_db):
    """Agent should call get_recall_queue and return a ranked list."""
    from app.agent.agent import run_agent

    result = run_agent(
        "Which patients are most overdue for a recall?",
        session_id="e2e-recalls",
    )

    print("\n--- RESPONSE ---")
    print(result["response"])
    print("\n--- TOOL CALLS ---")
    for tc in result["tool_calls"]:
        print(f"  {tc['tool']}({tc['input']}) → {tc['output'][:120]}")

    tool_names = [tc["tool"] for tc in result["tool_calls"]]
    assert "get_recall_queue" in tool_names
    response_lower = result["response"].lower()
    assert "recall" in response_lower or "overdue" in response_lower or "patient" in response_lower


@pytest.mark.e2e
def test_draft_recall_message_for_patient_7(seeded_db):
    """Agent should call draft_recall_message and return a personalised message."""
    from app.agent.agent import run_agent

    result = run_agent(
        "Draft a recall message for patient 7",
        session_id="e2e-draft",
    )

    print("\n--- RESPONSE ---")
    print(result["response"])
    print("\n--- TOOL CALLS ---")
    for tc in result["tool_calls"]:
        print(f"  {tc['tool']}({tc['input']}) → {tc['output'][:120]}")

    tool_names = [tc["tool"] for tc in result["tool_calls"]]
    assert "draft_recall_message" in tool_names
    assert len(result["response"]) > 50
