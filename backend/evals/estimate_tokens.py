"""Offline token-cost estimator for DentalAI agent fixed overhead.

Uses len(s) // 4 as a rough chars→tokens approximation (GPT-style tokenisers
average ~4 chars/token for English prose; actual Groq counts will differ by ±15%).

Run from backend/:
    py evals/estimate_tokens.py

Does NOT call any external API. Does NOT require a database file.
"""
import json
import os
import sys

# Minimal env so agent.py imports without a real DB or API key
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("GROQ_API_KEY", "dummy-for-estimation")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agent.agent import _SYSTEM_PROMPT, OPENAI_TOOL_SCHEMAS  # noqa: E402


def _est(s: str) -> int:
    return max(1, len(s) // 4)


def main() -> None:
    schema_str = json.dumps(OPENAI_TOOL_SCHEMAS)
    sp_chars = len(_SYSTEM_PROMPT)
    sc_chars = len(schema_str)
    total_chars = sp_chars + sc_chars

    print("=" * 60)
    print("DentalAI Agent — Fixed Overhead Estimate")
    print("=" * 60)
    print(f"  System prompt : {sp_chars:>7,} chars  ~{_est(_SYSTEM_PROMPT):>5,} tokens")
    print(f"  Tool schemas  : {sc_chars:>7,} chars  ~{_est(schema_str):>5,} tokens")
    print(f"  TOTAL         : {total_chars:>7,} chars  ~{_est(_SYSTEM_PROMPT) + _est(schema_str):>5,} tokens")
    print()
    print(f"  Daily budget  :  200,000 tokens")
    print(f"  Note: fixed overhead is resent every API call but is only part of")
    print(f"  per-case cost; variable content (tool results, history) dominates.")
    print(f"  Run the smoke set and check prompt_tokens in latest.json for real numbers.")
    print()
    print("Per-tool breakdown:")
    for t in OPENAI_TOOL_SCHEMAS:
        f = t["function"]
        desc_chars = len(f.get("description", ""))
        param_chars = len(json.dumps(f.get("parameters", {})))
        total = desc_chars + param_chars
        print(
            f"  {f['name']:<35} "
            f"desc={desc_chars:>4}  params={param_chars:>4}  "
            f"≈{total // 4:>3} tokens"
        )


if __name__ == "__main__":
    main()
