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


# ---------------------------------------------------------------------------
# Diagnosis helpers: --only, --ablate rag, failed_generation
# ---------------------------------------------------------------------------

def test_select_cases_only_keeps_order_and_rejects_unknown():
    import pytest
    from evals.run_evals import select_cases

    cases = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
    assert [c["id"] for c in select_cases(cases, "c,a")] == ["c", "a"]
    assert select_cases(cases, None) == cases
    with pytest.raises(ValueError):
        select_cases(cases, "a,zzz")


def test_apply_ablation_rag_removes_tool_and_prompt_line_only(monkeypatch):
    import app.agent.agent as agent
    from evals.run_evals import apply_ablation

    schemas, prompt = agent.OPENAI_TOOL_SCHEMAS, agent._SYSTEM_PROMPT
    monkeypatch.setattr(agent, "OPENAI_TOOL_SCHEMAS", schemas)
    monkeypatch.setattr(agent, "_SYSTEM_PROMPT", prompt)
    apply_ablation(agent, "rag")
    names = [t["function"]["name"] for t in agent.OPENAI_TOOL_SCHEMAS]
    assert "search_clinic_docs" not in names
    assert len(names) == len(schemas) - 1
    assert "search_clinic_docs" not in agent._SYSTEM_PROMPT
    assert agent._CLINIC_PROMPT_LINE in prompt  # the original had it
    assert agent._SYSTEM_PROMPT == prompt.replace(agent._CLINIC_PROMPT_LINE, "")
    apply_ablation(agent, "none")  # no-op


def test_failed_generation_extracts_model_output_from_groq_body():
    from evals.run_evals import failed_generation

    class E(Exception):
        body = {"error": {"message": "x", "failed_generation": '{"name": "draft_recall_message", "arguments": {bad'}}

    assert failed_generation(E()).startswith('{"name": "draft_recall_message"')
    assert failed_generation(Exception("no body")) == ""


def test_tool_parse_error_counter_counts_rescued_and_final_errors(monkeypatch):
    import app.agent.agent as agent
    from test_agent_tools import _groq_400, _fake_ok, _run_with_fake_groq

    before = agent.AGENT_STATS["tool_parse_errors"]
    bad = _groq_400("Failed to parse tool call arguments as JSON")
    _run_with_fake_groq(monkeypatch, [bad, _fake_ok()], "stats-1")
    assert agent.AGENT_STATS["tool_parse_errors"] == before + 1
