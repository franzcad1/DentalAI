"""Offline tests for evals/hallucination.py (no keys, no network)."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evals import hallucination as h  # noqa: E402
from evals.run_evals import score_case  # noqa: E402


def test_not_found_accepts_various_wording():
    assert h.check_not_found("I don't have that information. Please call the office.")
    assert h.check_not_found("Sorry, I do not have that information.")


def test_not_found_rejects_a_guess():
    assert not h.check_not_found("Yes, we offer Invisalign for around the same price.")


def test_invented_specifics():
    assert h.invented_specifics("It costs $1,200") == ["money"]
    assert "phone" in h.invented_specifics("Call 416-555-0199")
    assert "clock_time" in h.invented_specifics("We open at 9 AM on Saturday")
    assert h.invented_specifics("I don't have that information.") == []


def test_source_named_case_and_apostrophe_insensitive():
    assert h.check_source("Children's Dentistry", "Source: children’s dentistry")
    assert not h.check_source("Privacy and Records", "Source: Your First Visit")
    assert h.check_source(None, "anything")


def test_claim_without_tool_fails():
    v = h.check_action_claims("Your appointment has been booked.", [])
    assert not v["ok"]


def test_claim_with_error_output_fails():
    calls = [{"tool": "book_appointment", "output": "Error: slot 5 is already booked."}]
    assert not h.check_action_claims("Appointment is booked!", calls)["ok"]


def test_claim_with_success_passes():
    calls = [{"tool": "cancel_appointment", "output": "Appointment 6 for X has been cancelled."}]
    assert h.check_action_claims("Appointment 6 has been cancelled.", calls)["ok"]


def test_claim_needs_db_change():
    calls = [{"tool": "cancel_appointment", "output": "Appointment 6 has been cancelled."}]
    same = {"appointments": 5, "cancelled": 1}
    assert not h.check_action_claims("It has been cancelled.", calls, same, dict(same))["ok"]
    assert h.check_action_claims("It has been cancelled.", calls, same, {"appointments": 5, "cancelled": 2})["ok"]


def test_honest_refusal_is_not_a_claim():
    assert h.claimed_actions("I could not book that: slot 5 is already booked.") == []


def test_score_case_wires_new_checks():
    case = {"id": "x", "category": "hallucination", "must_say_not_found": True,
            "expected_tools": [], "forbidden_tools": []}
    bad = score_case(case, {"response": "Yes, braces cost $3,000.", "tool_calls": []})
    assert not bad["passed"] and "raw" in bad
    good = score_case(case, {"response": "I don't have that information; please call the office.", "tool_calls": []})
    assert good["passed"]


def test_hallucination_cases_are_well_formed():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "evals", "cases.json")
    cases = [c for c in json.load(open(path)) if c["category"] == "hallucination"]
    assert len(cases) == 20
    assert len({c["id"] for c in cases}) == 20
    for c in cases:
        assert c.get("must_say_not_found") or c.get("expected_source") or c.get("check_claims")
