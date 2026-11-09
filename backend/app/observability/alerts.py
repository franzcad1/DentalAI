"""Alert rules and evaluator (M1b).

Thresholds below are PROVISIONAL defaults, overridable by environment
variables. They are to be replaced with values chosen from a measured
baseline (see the M1b design note, section 7). Alerts are logged as
structured lines and, if ALERT_WEBHOOK_URL is set, posted to that URL.
Alert text carries only the rule name, a fixed message and a number.
"""

import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from app.observability.config import float_env
from app.observability.metrics import Metrics

logger = logging.getLogger("app.alerts")


@dataclass
class Rule:
    name: str
    message: str
    value: Callable[[Metrics], Optional[float]]  # None means "not enough data"
    threshold: float


def default_rules(health: Optional[Callable[[], bool]] = None) -> List[Rule]:
    win = int(float_env("ALERT_WINDOW_S", 300))
    min_req = int(float_env("ALERT_MIN_REQUESTS", 20))

    def error_share(m: Metrics) -> Optional[float]:
        total = sum(m.count("http_requests_total", win, status_class=s)
                    for s in ("2xx", "3xx", "4xx", "5xx"))
        if total < min_req:
            return None
        return m.count("http_requests_total", win, status_class="5xx") / total

    def chat_p95(m: Metrics) -> Optional[float]:
        if m.hist_count("http_request_duration_ms", win, route="/api/v1/agent/chat") < 3:
            return None
        return m.quantile("http_request_duration_ms", 0.95, win, route="/api/v1/agent/chat")

    rules = [
        Rule("http_5xx_share", "HTTP 5xx share is above the threshold", error_share,
             float_env("ALERT_5XX_SHARE", 0.05)),
        Rule("chat_p95_latency_ms", "Chat p95 latency is above the threshold", chat_p95,
             float_env("ALERT_CHAT_P95_MS", 30000)),
        Rule("groq_429_count", "Groq rate limit (429) count is above the threshold",
             lambda m: float(m.count("agent_groq_429_total", win)),
             float_env("ALERT_GROQ_429", 3) - 1),
        Rule("rag_unavailable", "Knowledge lookups are failing (RAG unavailable)",
             lambda m: float(m.count("rag_lookups_total", win, outcome="unavailable")),
             0),
        Rule("tool_parse_errors", "Groq tool-call parse errors are above the threshold",
             lambda m: float(m.count("agent_tool_parse_errors_total", win)),
             float_env("ALERT_TOOL_PARSE_ERRORS", 3) - 1),
        Rule("scheduler_job_failed", "A scheduler job failed",
             lambda m: float(m.count("scheduler_job_runs_total", win, outcome="error")),
             0),
    ]
    if health is not None:
        rules.append(Rule("deep_health_degraded", "Deep health check reports degraded",
                          lambda m: 0.0 if health() else 1.0, 0))
    return rules


class AlertEvaluator:
    def __init__(self, metrics: Metrics, rules: List[Rule],
                 notify: Optional[Callable[[Dict[str, Any]], None]] = None,
                 clock: Callable[[], float] = time.time,
                 cooldown_s: float = 900) -> None:
        self.metrics = metrics
        self.rules = rules
        self.notify = notify
        self.clock = clock
        self.cooldown_s = cooldown_s
        self.active: Dict[str, float] = {}  # rule name -> last notified at

    def evaluate(self) -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = []
        now = self.clock()
        for rule in self.rules:
            try:
                value = rule.value(self.metrics)
            except Exception:  # noqa: BLE001
                continue
            firing = value is not None and value > rule.threshold
            if firing:
                last = self.active.get(rule.name)
                if last is None or now - last >= self.cooldown_s:
                    self.active[rule.name] = now
                    ev = {"event": "alert_fired", "rule": rule.name,
                          "message": rule.message, "value": value,
                          "threshold": rule.threshold}
                    events.append(ev)
                    logger.warning("alert_fired", extra={"alert": ev})
                    self._notify(ev)
            elif rule.name in self.active:
                del self.active[rule.name]
                ev = {"event": "alert_resolved", "rule": rule.name}
                events.append(ev)
                logger.info("alert_resolved", extra={"alert": ev})
                self._notify(ev)
        return events

    def _notify(self, ev: Dict[str, Any]) -> None:
        if self.notify is None:
            return
        try:
            self.notify(ev)
        except Exception as exc:  # noqa: BLE001
            logger.warning("alert notify failed (%s)", type(exc).__name__)


def webhook_notifier() -> Optional[Callable[[Dict[str, Any]], None]]:
    url = os.getenv("ALERT_WEBHOOK_URL")
    if not url:
        return None

    def _post(ev: Dict[str, Any]) -> None:
        import httpx
        text = "%s: %s" % (ev.get("event"), ev.get("rule"))
        httpx.post(url, json={"text": text, "content": text}, timeout=5.0)

    return _post
