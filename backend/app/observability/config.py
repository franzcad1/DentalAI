"""Environment switches for observability (M1b).

OBSERVABILITY=off|local|azure
  off    no spans, no metrics side effects beyond cheap counters
  local  spans are written as JSON log lines, metrics kept in memory (default)
  azure  local + export spans to Azure Application Insights when
         APPLICATIONINSIGHTS_CONNECTION_STRING is set
"""

import os
from typing import Optional


def mode() -> str:
    value = os.getenv("OBSERVABILITY", "local").strip().lower()
    return value if value in ("off", "local", "azure") else "local"


def ops_token() -> Optional[str]:
    return os.getenv("OPS_TOKEN") or None


def float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return float(default)
