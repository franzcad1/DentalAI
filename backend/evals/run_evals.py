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

A case passes only when all five checks pass.
Provider errors (rate limits, network failures) are counted separately
and excluded from the pass-rate denominator so infra noise cannot fail CI.

Exit codes:
  0 — score >= --fail-under
  1 — score below --fail-under (or no scorable cases)
  2 — GROQ_API_KEY not set
  3 — category not found
  4 — too many provider errors (infra outage suspected)
"""

import argparse
import json
import os
import sys
import time
import traceback
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# ---------------------------------------------------------------------------
# Capture shell-set DATABASE_URL before .env overwrites it, then load .env.
# We use this flag in main() to decide whether to force eval.db.
# ---------------------------------------------------------------------------
_DB_URL_FROM_SHELL: bool = "DATABASE_URL" in os.environ

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass  # python-dotenv not installed — key must be set in the shell

# Make sure the app package is importable when run from backend/
sys.path.insert(0, str(Path(__file__).parent.parent))

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


def check_response_text(required_phrases: List[str], response: str) -> bool:
    if not required_phrases:
        return True
    lower = response.lower()
    return all(p.lower() in lower for p in required_phrases)


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


def score_case(case: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    called = _tools_called(result)
    expected = case.get("expected_tools", [])
    phrases = case.get("response_contains", [])
    forbidden = case.get("forbidden_tools", [])
    exp_args = case.get("expected_args", {})

    coverage = check_tool_coverage(expected, called)
    order = check_tool_order(expected, called)
    text = check_response_text(phrases, result.get("response", ""))
    no_forbidden = check_forbidden_tools(forbidden, called)
    args_ok = check_expected_args(exp_args, result)

    passed = coverage and order and text and no_forbidden and args_ok
    return {
        "id": case["id"],
        "category": case["category"],
        "passed": passed,
        "errored": False,
        "checks": {
            "tool_coverage": coverage,
            "tool_order": order,
            "response_text": text,
            "no_forbidden_tools": no_forbidden,
            "expected_args": args_ok,
        },
        "expected_tools": expected,
        "actual_tools": called,
        "response_snippet": result.get("response", "")[:120],
    }


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_cases(cases: List[Dict[str, Any]], delay: float = 1.5) -> List[Dict[str, Any]]:
    scored = []
    for i, case in enumerate(cases):
        session_id = f"eval-{uuid.uuid4().hex[:8]}"
        print(f"  [{i+1:02d}/{len(cases)}] {case['id']} ... ", end="", flush=True)
        try:
            result = run_agent(case["input"], session_id=session_id)
            outcome = score_case(case, result)
            print("PASS" if outcome["passed"] else "FAIL")
            if not outcome["passed"]:
                _print_failure(outcome)
        except Exception as exc:
            provider_err = is_provider_error(exc)
            outcome = {
                "id": case["id"],
                "category": case["category"],
                "passed": False,
                "errored": True,
                "provider_error": provider_err,
                "checks": {
                    "tool_coverage": False,
                    "tool_order": False,
                    "response_text": False,
                    "no_forbidden_tools": False,
                    "expected_args": False,
                },
                "expected_tools": case.get("expected_tools", []),
                "actual_tools": [],
                "response_snippet": "",
                "error": traceback.format_exc(),
            }
            label = "PROVIDER_ERROR" if provider_err else "ERROR"
            print(label)
            print(f"     {str(exc)[:120]}")
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
    if not checks["no_forbidden_tools"]:
        print(f"     forbidden_tools FAIL — snippet: {outcome['response_snippet']!r}")
    if not checks["expected_args"]:
        print(f"     expected_args FAIL — actual tools: {outcome['actual_tools']}")


_PROVIDER_ERROR_LIMIT = 3  # more than this many provider errors → suspect infra outage


def print_summary(scored: List[Dict[str, Any]], fail_under: int) -> int:
    provider_errors = [s for s in scored if s.get("provider_error")]
    errors = [s for s in scored if s.get("errored") and not s.get("provider_error")]
    scorable = [s for s in scored if not s.get("provider_error")]

    total = len(scorable)
    passed = sum(1 for s in scorable if s["passed"])
    pct = int(passed / total * 100) if total else 0

    print()
    print("=" * 56)
    print(f"  Result: {passed}/{total} passed  ({pct}%)")
    if provider_errors:
        print(f"  Provider errors (excluded): {len(provider_errors)}")
    if errors:
        print(f"  Agent errors (counted as fail): {len(errors)}")
    print("=" * 56)

    categories: Dict[str, List[Optional[bool]]] = {}
    for s in scored:
        result_val: Optional[bool] = None if s.get("provider_error") else s["passed"]
        categories.setdefault(s["category"], []).append(result_val)
    for cat, results in sorted(categories.items()):
        n = len([r for r in results if r is not None])
        p = sum(1 for r in results if r is True)
        errs = sum(1 for r in results if r is None)
        suffix = f"  ({errs} provider_error)" if errs else ""
        print(f"  {cat:<22} {p}/{n}{suffix}")

    print("=" * 56)

    if len(provider_errors) > _PROVIDER_ERROR_LIMIT:
        print(
            f"  INFRA OUTAGE — {len(provider_errors)} provider errors exceeds limit "
            f"({_PROVIDER_ERROR_LIMIT}); results are not meaningful"
        )
        return 4

    if total == 0:
        print("  No scorable cases — GATE FAIL (all cases errored)")
        return 1

    if pct < fail_under:
        print(f"  GATE FAIL — {pct}% is below the {fail_under}% threshold")
        return 1
    print(f"  GATE PASS — {pct}% >= {fail_under}%")
    return 0


def save_results(scored: List[Dict[str, Any]]) -> None:
    RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    scorable = [s for s in scored if not s.get("provider_error")]
    passed = sum(1 for s in scorable if s["passed"])
    payload = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_cases": len(scored),
        "scorable": len(scorable),
        "passed": passed,
        "provider_errors": sum(1 for s in scored if s.get("provider_error")),
        "cases": scored,
    }
    RESULTS_FILE.write_text(json.dumps(payload, indent=2))
    print(f"\n  Results saved to {RESULTS_FILE}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
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
    args = parser.parse_args()

    if not os.getenv("GROQ_API_KEY"):
        print("ERROR: GROQ_API_KEY is not set — evals require a live Groq key.")
        print("Set it in backend/.env or export it before running.")
        sys.exit(2)

    # Use eval.db unless DATABASE_URL was explicitly set in the shell
    # (e.g. CI sets it at the job level).  A value that came only from
    # .env is treated as a dev-DB pointer and overridden here so local
    # runs never write bookings/cancels into dentalai.db.
    if args.reseed or not _DB_URL_FROM_SHELL:
        os.environ["DATABASE_URL"] = "sqlite:///./eval.db"

    from app.agent.agent import run_agent as _run_agent
    global run_agent
    run_agent = _run_agent

    if args.reseed:
        from app.db.seed import run_seed
        print("Reseeding database…")
        run_seed()

    cases = json.loads(CASES_FILE.read_text())
    if args.category:
        cases = [c for c in cases if c["category"] == args.category]
        if not cases:
            print(f"No cases found for category '{args.category}'")
            sys.exit(3)

    print(f"\nDentalAI Eval Harness — {len(cases)} cases")
    print(f"Threshold: {args.fail_under}%  |  Delay: {args.delay}s\n")

    scored = run_cases(cases, delay=args.delay)

    if not args.no_save:
        save_results(scored)

    exit_code = print_summary(scored, args.fail_under)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
