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

    # Response has "Dr. Jones"; expectation is "Dr. Smith" -- must fail.
    assert not check_response_text(["Dr. Smith"], "Dr. Jones confirmed your appointment")


# ---------------------------------------------------------------------------
# is_size_error -- 400 vs 413 discrimination
# ---------------------------------------------------------------------------

class _FakeExc(Exception):
    """Minimal stand-in for Groq's BadRequestError (carries status_code)."""
    def __init__(self, status_code: int, message: str = ""):
        super().__init__(message)
        self.status_code = status_code


def test_is_size_error_false_for_status_400():
    """HTTP 400 (bad tool-call JSON) must NOT be treated as a size error."""
    from evals.run_evals import is_size_error
    assert not is_size_error(_FakeExc(400, "bad request"))


def test_is_size_error_true_for_status_413():
    """HTTP 413 via status_code attribute must be detected as a size error."""
    from evals.run_evals import is_size_error
    assert is_size_error(_FakeExc(413, "request too large"))


def test_is_size_error_true_for_runtime_error_413_text():
    """RuntimeError wrapping a real 413 (as agent.py re-raises it) must be detected."""
    from evals.run_evals import is_size_error
    assert is_size_error(RuntimeError("413 Request too large: some details"))


def test_is_size_error_false_for_plain_runtime_error():
    """A RuntimeError without '413' in its message must not be treated as a size error."""
    from evals.run_evals import is_size_error
    assert not is_size_error(RuntimeError("invalid tool call arguments"))
