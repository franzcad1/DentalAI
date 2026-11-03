"""Unit tests for eval harness scoring helpers.

Run with: cd backend && py -m pytest tests/test_eval_harness.py -v
"""
import os
import sys

# Ensure backend/ is on the path so evals.run_evals is importable.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_normalize_narrow_no_break_space_matches():
    """U+202F in response must match a plain-space expectation."""
    from evals.run_evals import check_response_text

    # Model uses "Patient 1"; case expects "Patient 1"
    assert check_response_text(["Patient 1"], "Patient 1 has been confirmed")


def test_normalize_no_break_space_matches():
    """U+00A0 (non-breaking space) in response must match a plain-space expectation."""
    from evals.run_evals import check_response_text

    assert check_response_text(["Dr. Smith"], "Your provider is Dr. Smith")


def test_normalize_does_not_make_wrong_response_pass():
    """Normalization must not cause a genuinely wrong response to pass."""
    from evals.run_evals import check_response_text

    # Response has "Dr. Jones" (with U+202F); expectation is "Dr. Smith" — must fail.
    assert not check_response_text(["Dr. Smith"], "Dr. Jones confirmed your appointment")
