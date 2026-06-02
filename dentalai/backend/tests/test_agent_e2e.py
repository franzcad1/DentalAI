"""End-to-end agent tests.

These tests call run_agent() directly and require OPENAI_API_KEY to be set
in the environment or in backend/.env.

Run with:
    cd backend
    py -m pytest tests/test_agent_e2e.py -v -s

If OPENAI_API_KEY is not set, tests are skipped automatically.
"""

import json
import os

import pytest

# Skip the entire module if no API key is available
pytestmark = pytest.mark.skipif(
    not os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY", "").startswith("sk-test"),
    reason="OPENAI_API_KEY not set — skipping live agent tests",
)


@pytest.fixture(scope="module")
def seeded_db():
    """Ensure a seeded DB exists before running agent tests."""
    from app.db.seed import run_seed
    run_seed()


def test_book_cleaning_for_patient_3(seeded_db):
    """Agent should find an open slot this week and book a cleaning for patient 3."""
    from app.agent.agent import run_agent

    result = run_agent(
        "Book a cleaning for patient 3 with any available provider this week",
        session_id="e2e-booking",
    )

    print("\n--- RESPONSE ---")
    print(result["response"])
    print("\n--- TOOL CALLS ---")
    for tc in result["tool_calls"]:
        print(f"  {tc['tool']}({tc['input']}) → {tc['output'][:120]}")

    # The agent must have called at least check_available_slots and book_appointment
    tool_names = [tc["tool"] for tc in result["tool_calls"]]
    assert "check_available_slots" in tool_names, "Expected slot search"
    assert "book_appointment" in tool_names, "Expected booking"
    assert "patient" in result["response"].lower() or "book" in result["response"].lower()


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
    # Response should mention patients or days overdue
    response_lower = result["response"].lower()
    assert "recall" in response_lower or "overdue" in response_lower or "patient" in response_lower


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
    # Response should contain the drafted message text
    assert len(result["response"]) > 50
