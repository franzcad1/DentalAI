"""M2 Eval harness — score the agent against golden cases.

Usage:
    cd backend
    py evals/run_evals.py                   # run all cases
    py evals/run_evals.py --category recall # run one category
    py evals/run_evals.py --fail-under 80   # exit 1 if score < 80%
    py evals/run_evals.py --reseed          # drop/recreate DB before running

Each case checks:
  1. Tool coverage   — every expected tool was called at least once
  2. Tool order      — expected tools appear in the correct relative order
  3. Response text   — every required phrase appears in the final answer
  4. Forbidden tools — none of the forbidden tools were called
  5. Arg checks      — required argument values appear in at least one
                       call to the target tool

Hallucination fields (see evals/hallucination.py): `must_say_not_found`, `expected_source`, `check_claims`.
Optional case fields: `response_excludes` (phrases that must NOT appear, used
to catch invented answers) and `requires: "rag"` (case is skipped unless
RAG_DATABASE_URL and COHERE_API_KEY are set).

A case passes only when all checks pass.
Provider errors (rate limits, network failures) are counted separately
and excluded from the pass-rate denominator so infra noise cannot fail CI.

Exit codes:
  0 — score >= --fail-under
  1 — score below --fail-under (or no scorable cases)
  2 — GROQ_API_KEY not set
  3 — category not found / no matching cases
  4 — too many provider errors (infra outage suspected)
  5 — daily token limit hit mid-run (partial results saved)
"""

import argparse
import json
import os
import re
import sys
import time
import traceback
import unicodedata
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass  # python-dotenv not installed — key must be set in the shell

# Make sure the app package is importable when run from backend/
sys.path.insert(0, str(Path(__file__).parent.parent))

from evals import hallucination  # noqa: E402

# Populated at runtime after key check (allows --help without a key)
run_agent: Callable = None  # type: ignore[assignment]

CASES_FILE = Path(__file__).parent / "cases.json"
RESULTS_FILE = Path(__file__).parent / "results" / "latest.json"

# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def _tools_called(result: Dict[str, Any]) -> List[str]:
    return [tc["tool"] for tc in result.get("tool_calls", [])]


def _tool_inputs(result: Dict[str, Any], tool_name: str) -> List[Dict[str, Any]]:
    """Return all input dicts for calls to tool_name."""
    return [tc["input"] for tc in result.get("tool_calls", []) if tc["tool"] == tool_name]


def check_tool_coverage(expected: List[str], called: List[str]) -> bool:
    if not expected:
        return True
    return all(t in called for t in expected)


def check_tool_order(expected: List[str], called: List[str]) -> bool:
    """Expected tools must appear in correct relative order (subsequence)."""
    if len(expected) <= 1:
        return True
    idx = 0
    for tool in called:
        if idx < len(expected) and tool == expected[idx]:
            idx += 1
    return idx == len(expected)


def _normalize_ws(s: str) -> str:
    """Replace Unicode space separators (U+00A0, U+202F, etc.) with plain space.

    Models sometimes emit narrow no-break spaces (U+202F) in formatted output
    (e.g. "Patient 1", "28 days").  Normalising before comparison prevents
    false failures when response_contains phrases use plain spaces.
    """
    out = []
    for ch in s:
        out.append(" " if unicodedata.category(ch) == "Zs" else ch)
    return re.sub(r" {2,}", " ", "".join(out))


def check_response_text(required_phrases: List[str], response: str) -> bool:
    if not required_phrases:
        return True
    normalized = _normalize_ws(response).lower()
    return all(_normalize_ws(p).lower() in normalized for p in required_phrases)


def check_response_excludes(excluded_phrases: List[str], response: str) -> bool:
    """True when none of the excluded phrases appear (used to catch invented answers)."""
    if not excluded_phrases:
        return True
    normalized = _normalize_ws(response).lower()
    return not any(_normalize_ws(p).lower() in normalized for p in excluded_phrases)


def apply_ablation(agent_module: Any, mode: str) -> None:
    """Make the agent behave like the pre-M3 agent for A/B diagnosis (process-local).

    mode "rag": drop the search_clinic_docs tool schema and its system-prompt line.
    """
    if mode == "none":
        return
    if mode != "rag":
        raise ValueError(f"unknown ablation: {mode}")
    agent_module.OPENAI_TOOL_SCHEMAS = [
        t for t in agent_module.OPENAI_TOOL_SCHEMAS
        if t["function"]["name"] != "search_clinic_docs"
    ]
    agent_module._SYSTEM_PROMPT = agent_module._SYSTEM_PROMPT.replace(
        agent_module._CLINIC_PROMPT_LINE, ""
    )


def select_cases(all_cases: List[Dict[str, Any]], only: Optional[str]) -> List[Dict[str, Any]]:
    """--only ID[,ID...]: exactly those cases, in the given order. Unknown ids raise."""
    if not only:
        return all_cases
    by_id = {c["id"]: c for c in all_cases}
    ids = [i.strip() for i in only.split(",") if i.strip()]
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise ValueError(f"unknown case id(s): {', '.join(missing)}")
    return [by_id[i] for i in ids]


def failed_generation(exc: Exception) -> str:
    """The model's rejected tool call text from a Groq 400 body, if present (eval-only)."""
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error", body)
        if isinstance(err, dict):
            return str(err.get("failed_generation") or "")
    return ""


def filter_unavailable(cases: List[Dict[str, Any]], rag_configured: bool):
    """Drop cases that need RAG when it is not configured. Returns (kept, skipped)."""
    if rag_configured:
        return cases, []
    kept = [c for c in cases if c.get("requires") != "rag"]
    return kept, [c for c in cases if c.get("requires") == "rag"]


def check_forbidden_tools(forbidden: List[str], called: List[str]) -> bool:
    if not forbidden:
        return True
    return not any(t in called for t in forbidden)


def check_expected_args(
    expected_args: Dict[str, Any],
    result: Dict[str, Any],
) -> bool:
    """For each tool in expected_args, verify the required key=value appears
    in at least one call to that tool."""
    if not expected_args:
        return True
    for tool_name, required in expected_args.items():
        calls = _tool_inputs(result, tool_name)
        if not calls:
            return False
        match = any(
            all(str(c.get(k)) == str(v) for k, v in required.items())
            for c in calls
        )
        if not match:
            return False
    return True


def is_provider_error(exc: Exception) -> bool:
    """True when the failure is infra noise, not agent quality."""
    msg = str(exc).lower()
    return any(kw in msg for kw in ("rate limit", "429", "timeout", "connection", "ratelimit", "daily token limit"))


def is_size_error(exc: Exception) -> bool:
    """True when the request was rejected as too large (HTTP 413).

    Groq 1.7.0 raises BadRequestError for *any* HTTP 4xx (not just 413),
    so we check status_code first to avoid misclassifying a bad-JSON 400
    as a size error and silently excluding it from the denominator.
    """
    if hasattr(exc, "status_code"):
        return exc.status_code == 413
    msg = str(exc).lower()
    return any(kw in msg for kw in ("413", "request too large", "request entity too large", "payload too large"))


class DailyLimitStop(Exception):
    """Raised by run_cases when the provider's daily token limit is hit."""
    def __init__(self, partial: List[Dict[str, Any]], provider_msg: str = ""):
        self.partial = partial
        self.provider_msg = provider_msg


def score_case(
    case: Dict[str, Any],
    result: Dict[str, Any],
    db_before: Optional[Dict[str, int]] = None,
    db_after: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    called = _tools_called(result)
    expected = case.get("expected_tools", [])
    phrases = case.get("response_contains", [])
    forbidden = case.get("forbidden_tools", [])
    exp_args = case.get("expected_args", {})

    coverage = check_tool_coverage(expected, called)
    order = check_tool_order(expected, called)
    text = check_response_text(phrases, result.get("response", ""))
    excl_ok = check_response_excludes(case.get("response_excludes", []), result.get("response", ""))
    no_forbidden = check_forbidden_tools(forbidden, called)
    args_ok = check_expected_args(exp_args, result)

    response = result.get("response", "")
    extra: Dict[str, Any] = {}
    if case.get("must_say_not_found"):
        extra["not_found"] = hallucination.check_not_found(response)
        extra["no_invented_specifics"] = not hallucination.invented_specifics(response)
    if case.get("expected_source"):
        extra["source_named"] = hallucination.check_source(case["expected_source"], response)
    if case.get("check_claims"):
        verdict = hallucination.check_action_claims(
            response, result.get("tool_calls", []), db_before, db_after)
        extra["action_claims_ok"] = verdict["ok"]
        extra["claim_problems"] = verdict["reasons"]
    extra_ok = all(v for k, v in extra.items() if k != "claim_problems")

    passed = coverage and order and text and excl_ok and no_forbidden and args_ok and extra_ok
    out = {
        "id": case["id"],
        "category": case["category"],
        "passed": passed,
        "errored": False,
        "provider_error": False,
        "size_error": False,
        "prompt_tokens": result.get("prompt_tokens", 0),
        "completion_tokens": result.get("completion_tokens", 0),
        "tool_parse_retries": result.get("tool_parse_retries", 0),
        "checks": {
            "tool_coverage": coverage,
            "tool_order": order,
            "response_text": text,
            "response_excludes": excl_ok,
            "no_forbidden_tools": no_forbidden,
            "expected_args": args_ok,
        },
        "expected_tools": expected,
        "actual_tools": called,
        "response_snippet": result.get("response", "")[:120],
    }
    if extra:
        out["checks"].update({k: v for k, v in extra.items() if k != "claim_problems"})
        out["claim_problems"] = extra.get("claim_problems", [])
        # Raw answer and tool outputs so scoring rules can be re-checked without new Groq calls.
        out["raw"] = {"response": response, "tool_calls": result.get("tool_calls", [])}
    return out


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_cases(cases: List[Dict[str, Any]], delay: float = 1.5) -> List[Dict[str, Any]]:
    scored = []
    for i, case in enumerate(cases):
        session_id = f"eval-{uuid.uuid4().hex[:8]}"
        print(f"  [{i+1:02d}/{len(cases)}] {case['id']} ... ", end="", flush=True)
        try:
            before = hallucination.db_snapshot() if case.get("check_claims") else None
            result = run_agent(case["input"], session_id=session_id)
            after = hallucination.db_snapshot() if case.get("check_claims") else None
            outcome = score_case(case, result, before, after)
            print("PASS" if outcome["passed"] else "FAIL")
            if not outcome["passed"]:
                _print_failure(outcome)
        except Exception as exc:
            provider_err = is_provider_error(exc)
            size_err = is_size_error(exc)
            _stop_daily = "daily token limit" in str(exc).lower()
            outcome = {
                "id": case["id"],
                "category": case["category"],
                "passed": False,
                "errored": True,
                "provider_error": provider_err,
                "size_error": size_err,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "checks": {
                    "tool_coverage": False,
                    "tool_order": False,
                    "response_text": False,
                    "response_excludes": False,
                    "no_forbidden_tools": False,
                    "expected_args": False,
                },
                "expected_tools": case.get("expected_tools", []),
                "actual_tools": [],
                "response_snippet": "",
                "error": traceback.format_exc(),
            }
            label = (
                "DAILY_LIMIT" if _stop_daily else
                "PROVIDER_ERROR" if provider_err else
                "SIZE_ERROR" if size_err else
                "ERROR"
            )
            print(label)
            print(f"     {str(exc)[:120]}")
            fg = failed_generation(exc)
            if fg:
                print(f"     failed_generation: {fg[:400]!r}")
            scored.append(outcome)
            if _stop_daily:
                raise DailyLimitStop(scored, str(exc))
            if i < len(cases) - 1:
                time.sleep(delay)
            continue
        scored.append(outcome)
        if i < len(cases) - 1:
            time.sleep(delay)
    return scored


def _print_failure(outcome: Dict[str, Any]) -> None:
    checks = outcome["checks"]
    if not checks["tool_coverage"]:
        missing = [t for t in outcome["expected_tools"] if t not in outcome["actual_tools"]]
        print(f"     tool_coverage FAIL — missing: {missing}")
    if not checks["tool_order"]:
        print(f"     tool_order FAIL — expected {outcome['expected_tools']}, got {outcome['actual_tools']}")
    if not checks["response_text"]:
        print(f"     response_text FAIL — snippet: {outcome['response_snippet']!r}")
    if not checks.get("response_excludes", True):
        print(f"     response_excludes FAIL — snippet: {outcome['response_snippet']!r}")
    if not checks["no_forbidden_tools"]:
        print(f"     forbidden_tools FAIL — snippet: {outcome['response_snippet']!r}")
    if not checks["expected_args"]:
        print(f"     expected_args FAIL — actual tools: {outcome['actual_tools']}")
    for name in ("not_found", "no_invented_specifics", "source_named", "action_claims_ok"):
        if name in checks and not checks[name]:
            extra = f" — {outcome['claim_problems']}" if name == "action_claims_ok" else ""
            print(f"     {name} FAIL{extra}")
    if any(k in checks and not checks[k] for k in ("not_found", "no_invented_specifics", "source_named", "action_claims_ok")):
        print(f"     answer: {outcome.get('raw', {}).get('response', '')[:300]!r}")


_PROVIDER_ERROR_LIMIT = 3  # more than this many provider errors → suspect infra outage


def print_summary(scored: List[Dict[str, Any]], fail_under: int) -> int:
    provider_errors = [s for s in scored if s.get("provider_error")]
    size_errors = [s for s in scored if s.get("size_error")]
    errors = [s for s in scored if s.get("errored") and not s.get("provider_error") and not s.get("size_error")]
    scorable = [s for s in scored if not s.get("provider_error") and not s.get("size_error")]

    total = len(scorable)
    passed = sum(1 for s in scorable if s["passed"])
    pct = int(passed / total * 100) if total else 0

    print()
    print("=" * 56)
    print(f"  Result: {passed}/{total} passed  ({pct}%)")
    if provider_errors:
        print(f"  Provider errors (excluded): {len(provider_errors)}")
    if size_errors:
        print(f"  Size errors / 413 (excluded): {len(size_errors)}")
    if errors:
        print(f"  Agent errors (counted as fail): {len(errors)}")
    parse_retries = sum(s.get("tool_parse_retries", 0) for s in scored)
    if parse_retries:
        print(f"  Groq tool-call JSON retries used: {parse_retries}")
    total_pt = sum(s.get("prompt_tokens", 0) for s in scored)
    total_ct = sum(s.get("completion_tokens", 0) for s in scored)
    if total_pt or total_ct:
        print(f"  Tokens  prompt={total_pt:,}  completion={total_ct:,}  total={total_pt + total_ct:,}")
    print("=" * 56)

    categories: Dict[str, List[Optional[bool]]] = {}
    for s in scored:
        excluded = s.get("provider_error") or s.get("size_error")
        result_val: Optional[bool] = None if excluded else s["passed"]
        categories.setdefault(s["category"], []).append(result_val)
    for cat, results in sorted(categories.items()):
        n = len([r for r in results if r is not None])
        p = sum(1 for r in results if r is True)
        errs = sum(1 for r in results if r is None)
        suffix = f"  ({errs} excluded)" if errs else ""
        print(f"  {cat:<22} {p}/{n}{suffix}")

    print("=" * 56)

    if len(provider_errors) > _PROVIDER_ERROR_LIMIT:
        print(
            f"  INFRA OUTAGE — {len(provider_errors)} provider errors exceeds limit "
            f"({_PROVIDER_ERROR_LIMIT}); results are not meaningful"
        )
        return 4

    if total == 0:
        print("  No scorable cases — GATE FAIL (all cases errored or excluded)")
        return 1

    if pct < fail_under:
        print(f"  GATE FAIL — {pct}% is below the {fail_under}% threshold")
        return 1
    print(f"  GATE PASS — {pct}% >= {fail_under}%")
    return 0


def save_results(scored: List[Dict[str, Any]]) -> None:
    RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    scorable = [s for s in scored if not s.get("provider_error") and not s.get("size_error")]
    passed = sum(1 for s in scorable if s["passed"])
    payload = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_cases": len(scored),
        "scorable": len(scorable),
        "passed": passed,
        "provider_errors": sum(1 for s in scored if s.get("provider_error")),
        "size_errors": sum(1 for s in scored if s.get("size_error")),
        "total_prompt_tokens": sum(s.get("prompt_tokens", 0) for s in scored),
        "total_completion_tokens": sum(s.get("completion_tokens", 0) for s in scored),
        "cases": scored,
    }
    RESULTS_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\n  Results saved to {RESULTS_FILE}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_repeat(cases: List[Dict[str, Any]], args: Any, agent_module: Any) -> int:
    """Run the selected cases args.repeat times; print a per-case tally. Not saved."""
    label = f"ablate={args.ablate}"
    print(f"\nDentalAI Eval Harness — repeat x{args.repeat} ({label}), {len(cases)} case(s)\n")
    tally: Dict[str, Dict[str, int]] = {}
    tokens = 0
    start_400s = agent_module.AGENT_STATS["tool_parse_errors"]
    for rep_no in range(1, args.repeat + 1):
        print(f"--- repetition {rep_no}/{args.repeat}")
        if args.reseed:
            from app.db.seed import run_seed
            run_seed()
        try:
            scored = run_cases(cases, delay=args.delay)
        except DailyLimitStop as e:
            print("\n  DAILY LIMIT reached — stopping early; tally below is partial.")
            scored = e.partial
            _accumulate(tally, scored)
            tokens += sum(s.get("prompt_tokens", 0) + s.get("completion_tokens", 0) for s in scored)
            break
        _accumulate(tally, scored)
        tokens += sum(s.get("prompt_tokens", 0) + s.get("completion_tokens", 0) for s in scored)
    n400 = agent_module.AGENT_STATS["tool_parse_errors"] - start_400s
    print("\n" + "=" * 56)
    print(f"  Repeat tally ({label})")
    for cid, t in tally.items():
        print(f"  {cid:<14} pass={t['pass']} fail={t['fail']} error={t['error']}")
    print(f"  Groq tool-call JSON 400s seen (incl. rescued by retry): {n400}")
    print(f"  Tokens (completed calls only): {tokens:,}")
    print("=" * 56)
    return 0


def _accumulate(tally: Dict[str, Dict[str, int]], scored: List[Dict[str, Any]]) -> None:
    for s in scored:
        t = tally.setdefault(s["id"], {"pass": 0, "fail": 0, "error": 0})
        if s.get("errored"):
            t["error"] += 1
        elif s["passed"]:
            t["pass"] += 1
        else:
            t["fail"] += 1


def main() -> None:
    # On Windows the default console encoding (cp1252) drops emoji as "?".
    if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="Run DentalAI agent evals")
    parser.add_argument("--category", help="Run only cases in this category")
    parser.add_argument("--fail-under", type=int, default=80,
                        help="Exit 1 if pass rate is below this percentage (default: 80)")
    parser.add_argument("--delay", type=float, default=1.5,
                        help="Seconds between cases (default: 1.5, avoids TPM limits)")
    parser.add_argument("--no-save", action="store_true",
                        help="Skip writing results/latest.json")
    parser.add_argument("--reseed", action="store_true",
                        help="Drop and recreate the database before running")
    parser.add_argument("--full", action="store_true",
                        help="Run all cases; default runs only smoke-tagged cases")
    parser.add_argument("--only-missing", action="store_true",
                        help="Skip cases that already have a completed result in latest.json")
    parser.add_argument("--only", help="Run only these case ids (comma-separated), ignoring the smoke filter")
    parser.add_argument("--repeat", type=int, default=1,
                        help="Run the selected cases N times and print a per-case tally (results are not saved)")
    parser.add_argument("--ablate", choices=["none", "rag"], default="none",
                        help="rag = run without the knowledge tool and its prompt line (pre-M3 behaviour)")
    args = parser.parse_args()

    if not os.getenv("GROQ_API_KEY"):
        print("ERROR: GROQ_API_KEY is not set — evals require a live Groq key.")
        print("Set it in backend/.env or export it before running.")
        sys.exit(2)

    # Always use eval.db — never the dev database.
    # Both shell exports and .env may point at dentalai.db; ignore both.
    # The app reads DATABASE_URL at import time (session.py line 8), so
    # this must be set before "from app.agent.agent import run_agent" below.
    os.environ["DATABASE_URL"] = "sqlite:///./eval.db"

    from app.agent.agent import run_agent as _run_agent
    global run_agent
    run_agent = _run_agent
    import app.agent.agent as _agent_module
    apply_ablation(_agent_module, args.ablate)

    if args.reseed:
        from app.db.seed import run_seed
        print("Reseeding database…")
        run_seed()

    all_cases = json.loads(CASES_FILE.read_text())

    if args.only:
        try:
            cases = select_cases(all_cases, args.only)
        except ValueError as e:
            print(f"ERROR: {e}")
            sys.exit(3)
    # --full runs everything; default runs only smoke-tagged cases
    elif args.full or args.category:
        # --category searches every case, not just the smoke subset
        cases = all_cases
    else:
        smoke = [c for c in all_cases if c.get("smoke")]
        cases = smoke if smoke else all_cases

    from app.rag.retrieval import is_configured as _rag_configured

    cases, skipped = filter_unavailable(cases, _rag_configured())
    if skipped:
        print(f"Skipping {len(skipped)} knowledge case(s): RAG not configured "
              "(set RAG_DATABASE_URL and COHERE_API_KEY, then run ingest).")

    if args.category:
        cases = [c for c in cases if c["category"] == args.category]
        if not cases:
            print(f"No cases found for category '{args.category}'")
            sys.exit(3)

    # --only-missing: skip cases with a completed result in latest.json
    prev_results: Dict[str, Any] = {}
    if args.only_missing and RESULTS_FILE.exists():
        prev = json.loads(RESULTS_FILE.read_text())
        prev_results = {c["id"]: c for c in prev.get("cases", [])}
        done_ids = {
            cid for cid, c in prev_results.items()
            if not c.get("errored") and not c.get("size_error")
        }
        cases = [c for c in cases if c["id"] not in done_ids]
        if not cases:
            print("All cases already complete — nothing to run.")
            sys.exit(0)
        print(f"Resuming: {len(done_ids)} done, {len(cases)} remaining")

    if args.repeat > 1:
        sys.exit(run_repeat(cases, args, _agent_module))

    suite_label = "full" if args.full else f"smoke ({len(cases)} cases)"
    print(f"\nDentalAI Eval Harness — {suite_label}")
    print(f"Threshold: {args.fail_under}%  |  Delay: {args.delay}s\n")

    try:
        scored = run_cases(cases, delay=args.delay)
    except DailyLimitStop as e:
        scored = e.partial
        # Merge with any previous completed results when resuming
        if prev_results:
            existing = {c["id"]: c for c in scored}
            merged = [c for cid, c in prev_results.items() if cid not in existing]
            merged.extend(scored)
            scored = merged
        _wait = re.search(r"try again in\s+([\d]+m\s*[\d]+s|[\d]+\s*minutes?|[\d]+\s*seconds?)", e.provider_msg, re.I)
        _wait_str = f"retry in ~{_wait.group(1)}" if _wait else "retry later"
        print(f"\n  DAILY LIMIT reached — {_wait_str}. Partial results saved.")
        print("  Note: earlier runs in the last 24 h still count against your quota.")
        print("  Waiting a few minutes may only free one or two cases.")
        print("  Run again with --only-missing to continue.")
        if not args.no_save:
            save_results(scored)
        sys.exit(5)

    # Merge with previous completed results if resuming
    if prev_results:
        existing = {c["id"]: c for c in scored}
        merged = [c for cid, c in prev_results.items() if cid not in existing]
        merged.extend(scored)
        scored = merged

    if not args.no_save:
        save_results(scored)

    exit_code = print_summary(scored, args.fail_under)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
