"""Wiring: deep health checks and the shared alert evaluator."""

import os
from typing import Any, Dict, Optional

from sqlalchemy import text

from app.observability.alerts import AlertEvaluator, default_rules, webhook_notifier
from app.observability.metrics import metrics


def deep_health() -> Dict[str, Any]:
    """Per-check status. Never returns secrets or values, only ok/failed."""
    checks: Dict[str, str] = {}
    try:
        from app.db.session import engine
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:  # noqa: BLE001
        checks["database"] = "failed"
    try:
        from app.rag.retrieval import is_configured
        checks["rag_configured"] = "ok" if is_configured() else "failed"
    except Exception:  # noqa: BLE001
        checks["rag_configured"] = "failed"
    checks["groq_key_present"] = "ok" if os.getenv("GROQ_API_KEY") else "failed"
    status = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    return {"status": status, "checks": checks}


_evaluator: Optional[AlertEvaluator] = None


def get_evaluator() -> AlertEvaluator:
    global _evaluator
    if _evaluator is None:
        _evaluator = AlertEvaluator(
            metrics,
            default_rules(health=lambda: deep_health()["status"] == "ok"),
            notify=webhook_notifier(),
        )
    return _evaluator


def evaluate_alerts() -> None:
    from app.observability import config
    if config.mode() == "off":
        return
    get_evaluator().evaluate()
