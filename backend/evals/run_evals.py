"""M2 Eval harness — score the agent against golden cases.

Usage:
    cd backend
    py evals/run_evals.py                   # run all cases
    py evals/run_evals.py --category recall # run one category
    py evals/run_evals.py --fail-under 80   # exit 1 if score < 80%

Each case checks:
  1. Tool coverage  — every expected tool was called at least once
  2. Tool order     — expected tools appear in the correct relative order
  3. Response text  — every required phrase appears in the final answer (case-insensitive)

A case passes only when all three checks pass.

Exit codes:
  0 — all cases pass or score >= --fail-under
  1 — score below --fail-under (CI gate trigger)
  2 — GROQ_API_KEY not set
"""

import argparse
import json
import os
import sys
import time
import traceback
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List

# Make sure the app package is importable when run from backend/
sys.path.insert(0, str(Path(__file__).parent.parent))

# Populated at runtime after API key check
run_agent: Callable = None  # type: ignore[assignment]


CASES_FILE = Path(__file__).parent / "cases.json"
RESULTS_FILE = Path(__file__).parent / "results" / "latest.json"

# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def _tools_called(result: Dict[str, Any]) -> List[str]:
    return [tc["tool"] for tc in result.get("tool_calls", [])]


def check_tool_coverage(expected: List[str], called: List[str]) -> bool:
    """Every expected tool must appear at least once."""
    if not expected:
        return True
    return all(t in called for t in expected)


def check_tool_order(expected: List[str], called: List[str]) -> bool:
    """Expected tools must appear in the correct relative order (subsequence check)."""
    if len(expected) <= 1:
        return True
    idx = 0
    for tool in called:
        if idx < len(expected) and tool == expected[idx]:
            idx += 1
    return idx == len(expected)


def check_response_text(required_phrases: List[str], response: str) -> bool:
    """All required phrases must appear in the response (case-insensitive)."""
    if not required_phrases:
        return True
    lower = response.lower()
    return all(p.lower() in lower for p in required_phrases)


def score_case(case: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    called = _tools_called(result)
    expected = case.get("expected_tools", [])
    phrases = case.get("response_contains", [])

    coverage = check_tool_coverage(expected, called)
    order = check_tool_order(expected, called)
    text = check_response_text(phrases, result.get("response", ""))

    passed = coverage and order and text
    return {
        "id": case["id"],
        "category": case["category"],
        "passed": passed,
        "checks": {
            "tool_coverage": coverage,
            "tool_order": order,
            "response_text": text,
        },
        "expected_tools": expected,
        "actual_tools": called,
        "response_snippet": result.get("response", "")[:120],
    }


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_cases(cases: List[Dict[str, Any]], delay: float = 1.5) -> List[Dict[str, Any]]:
    """Run each case and return scored results. delay avoids Groq TPM limits."""
    scored = []
    for i, case in enumerate(cases):
        session_id = f"eval-{uuid.uuid4().hex[:8]}"
        print(f"  [{i+1:02d}/{len(cases)}] {case['id']} ... ", end="", flush=True)
        try:
            result = run_agent(case["input"], session_id=session_id)
            outcome = score_case(case, result)
            status = "PASS" if outcome["passed"] else "FAIL"
            print(status)
            if not outcome["passed"]:
                _print_failure(outcome)
        except Exception:
            outcome = {
                "id": case["id"],
                "category": case["category"],
                "passed": False,
                "checks": {"tool_coverage": False, "tool_order": False, "response_text": False},
                "expected_tools": case.get("expected_tools", []),
                "actual_tools": [],
                "response_snippet": "",
                "error": traceback.format_exc(),
            }
            print("ERROR")
            print(f"     {traceback.format_exc().splitlines()[-1]}")
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


def print_summary(scored: List[Dict[str, Any]], fail_under: int) -> int:
    total = len(scored)
    passed = sum(1 for s in scored if s["passed"])
    pct = int(passed / total * 100) if total else 0

    print()
    print("=" * 56)
    print(f"  Result: {passed}/{total} passed  ({pct}%)")
    print("=" * 56)

    # Per-category breakdown
    categories: Dict[str, List[bool]] = {}
    for s in scored:
        categories.setdefault(s["category"], []).append(s["passed"])
    for cat, results in sorted(categories.items()):
        n = len(results)
        p = sum(results)
        print(f"  {cat:<20} {p}/{n}")

    print("=" * 56)

    if pct < fail_under:
        print(f"  GATE FAIL — {pct}% is below the {fail_under}% threshold")
        return 1
    print(f"  GATE PASS — {pct}% >= {fail_under}%")
    return 0


def save_results(scored: List[Dict[str, Any]]) -> None:
    RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total": len(scored),
        "passed": sum(1 for s in scored if s["passed"]),
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
    args = parser.parse_args()

    if not os.getenv("GROQ_API_KEY"):
        print("ERROR: GROQ_API_KEY is not set — evals require a live Groq key.")
        print("Set it in backend/.env or export it before running.")
        sys.exit(2)

    from app.agent.agent import run_agent as _run_agent  # noqa: E402
    global run_agent
    run_agent = _run_agent

    cases = json.loads(CASES_FILE.read_text())
    if args.category:
        cases = [c for c in cases if c["category"] == args.category]
        if not cases:
            print(f"No cases found for category '{args.category}'")
            sys.exit(0)

    print(f"\nDentalAI Eval Harness — {len(cases)} cases")
    print(f"Threshold: {args.fail_under}%  |  Delay: {args.delay}s\n")

    scored = run_cases(cases, delay=args.delay)

    if not args.no_save:
        save_results(scored)

    exit_code = print_summary(scored, args.fail_under)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
