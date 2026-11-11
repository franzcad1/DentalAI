"""Tracing helpers (M1b).

One choke point, `span()`, creates spans, and one function, `safe_attrs()`,
decides which attributes may be recorded. Attribute NAMES must be on an
allowlist and VALUES must be numbers, booleans or short token-like strings
(no spaces), so message text, names, emails and free-form exception messages
cannot be attached by accident. Telemetry failures are swallowed: tracing must
never break a request.
"""

import logging
import re
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional

from app.observability import config

try:  # OpenTelemetry is optional so an install problem never stops the app.
    from opentelemetry import trace as _otel_trace
    from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    _OTEL = True
except Exception:  # pragma: no cover - exercised only when the package is missing
    _otel_trace = None  # type: ignore[assignment]
    SpanProcessor = object  # type: ignore[assignment,misc]
    _OTEL = False

logger = logging.getLogger("app.trace")

ALLOWED_ATTRS = frozenset({
    "route", "method", "status", "status_class", "request_id",
    "turns", "tool_calls", "prompt_tokens", "completion_tokens", "outcome",
    "model", "attempt", "iteration", "finish_reason", "groq_429_count",
    "groq_429_wait_s", "tool_parse_retries", "tool_name", "ok", "error_type",
    "embed_ms", "search_ms", "hits", "top_score", "fallback_reason",
    "job", "rows_selected", "session_hash",
})

_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.:/{}=,\-]{1,100}$")


def safe_attrs(attrs: Dict[str, Any]) -> Dict[str, Any]:
    """Keep only allowlisted names with number, bool or token-like string values."""
    out: Dict[str, Any] = {}
    for key, value in attrs.items():
        if key not in ALLOWED_ATTRS:
            continue
        if isinstance(value, bool) or isinstance(value, (int, float)):
            out[key] = value
        elif isinstance(value, str) and _TOKEN_RE.match(value):
            out[key] = value
    return out


class _LogSpanProcessor(SpanProcessor):  # type: ignore[misc,valid-type]
    """Write each finished span as one JSON log line (the 'local' exporter)."""

    def on_start(self, span: Any, parent_context: Any = None) -> None:
        return None

    def on_end(self, span: Any) -> None:
        try:
            duration_ms = round((span.end_time - span.start_time) / 1e6, 1)
            logger.info(
                "span",
                extra={
                    "span_name": span.name,
                    "span_duration_ms": duration_ms,
                    "span_attrs": dict(span.attributes or {}),
                },
            )
        except Exception:  # noqa: BLE001
            pass

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True


_tracer: Any = None
_provider: Any = None


def init_tracing(extra_processors: Optional[list] = None) -> None:
    """(Re)build the tracer from the environment. Safe to call more than once."""
    global _tracer, _provider
    _tracer = _provider = None
    if config.mode() == "off" or not _OTEL:
        return
    try:
        provider = TracerProvider()
        provider.add_span_processor(_LogSpanProcessor())
        for proc in extra_processors or []:
            provider.add_span_processor(proc)
        if config.mode() == "azure":
            import os
            conn = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
            if conn:
                from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter
                provider.add_span_processor(
                    BatchSpanProcessor(AzureMonitorTraceExporter.from_connection_string(conn))
                )
            else:
                logger.warning("[OBS] OBSERVABILITY=azure but APPLICATIONINSIGHTS_CONNECTION_STRING is not set")
        _provider = provider
        _tracer = provider.get_tracer("dentalai")
    except Exception as exc:  # noqa: BLE001
        logger.warning("[OBS] tracing disabled (%s)", type(exc).__name__)
        _tracer = _provider = None


class SpanHandle:
    """Small wrapper so callers never touch the raw span."""

    def __init__(self, span: Any = None) -> None:
        self._span = span

    def set(self, **attrs: Any) -> None:
        if self._span is None:
            return
        try:
            for k, v in safe_attrs(attrs).items():
                self._span.set_attribute(k, v)
        except Exception:  # noqa: BLE001
            pass

    def fail(self, error_type: str) -> None:
        self.set(ok=False, error_type=error_type)


@contextmanager
def span(name: str, **attrs: Any) -> Iterator[SpanHandle]:
    if _tracer is None:
        yield SpanHandle(None)
        return
    try:
        cm = _tracer.start_as_current_span(
            name, record_exception=False, set_status_on_exception=False
        )
        raw = cm.__enter__()
    except Exception:  # noqa: BLE001
        yield SpanHandle(None)
        return
    handle = SpanHandle(raw)
    handle.set(**attrs)
    try:
        yield handle
    except BaseException as exc:
        handle.fail(type(exc).__name__)
        raise
    finally:
        try:
            cm.__exit__(None, None, None)
        except Exception:  # noqa: BLE001
            pass


def annotate(**attrs: Any) -> None:
    """Add allowlisted attributes to the current span, if there is one."""
    if _tracer is None or not _OTEL:
        return
    try:
        current = _otel_trace.get_current_span()
        SpanHandle(current).set(**attrs)
    except Exception:  # noqa: BLE001
        pass


def current_trace_id() -> str:
    if not _OTEL:
        return "-"
    try:
        ctx = _otel_trace.get_current_span().get_span_context()
        return format(ctx.trace_id, "032x") if ctx.is_valid else "-"
    except Exception:  # noqa: BLE001
        return "-"
