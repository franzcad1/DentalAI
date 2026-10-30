"""Structured logging configuration for DentalAI.

Sets up JSON-formatted logs so every line is machine-readable and can be
ingested by any log aggregator (Datadog, CloudWatch, Loki) without a
custom parser.

Two filters are attached to the handler:
- RequestIdFilter: injects the per-request trace ID from a ContextVar into
  every log record so all lines for one HTTP call share the same request_id.
- PhiRedactingFilter: scrubs email, phone, and dob values before the record
  is formatted — prevents incidental PHI disclosure in application logs
  (Ontario PHIPA requirement for healthcare data).

Uvicorn's own loggers are reconfigured to use the same handler so the entire
process produces a single uniform stream rather than mixing plain-text and
JSON lines.
"""

import contextvars
import logging
import re
import sys
from typing import Any

from pythonjsonlogger import jsonlogger

# Holds the current request's trace ID. Set by RequestIdMiddleware on each
# incoming request; defaults to "-" when called outside an HTTP context
# (e.g. background scheduler jobs, seed scripts).
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)

# PHI field names that must never appear as plain values in logs.
_PHI_FIELDS = ("email", "phone", "dob")

# Matches both JSON  "email": "value"  and Python-repr  'email': 'value'
# so the filter catches tool-call dicts logged via %s formatting as well as
# structured JSON strings.
_PHI_PATTERN = re.compile(
    r'(["\'](?:' + "|".join(_PHI_FIELDS) + r')["\']\s*:\s*)["\'][^"\']*["\']',
    re.IGNORECASE,
)


class RequestIdFilter(logging.Filter):
    """Inject the current request_id into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()  # type: ignore[attr-defined]
        return True


class PhiRedactingFilter(logging.Filter):
    """Scrub PHI field values from log messages before formatting.

    Replaces the value of email, phone, and dob keys in both JSON strings
    and Python-repr dicts with "***". Never drops a record.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        redacted = _PHI_PATTERN.sub(r'\1"***"', msg)
        if redacted != msg:
            record.msg = redacted
            record.args = ()
        return True


def _make_handler() -> logging.StreamHandler:  # type: ignore[type-arg]
    handler = logging.StreamHandler(sys.stdout)
    formatter = jsonlogger.JsonFormatter(
        # taskName is injected by python-json-logger in some versions and adds
        # noise — exclude it by listing only the fields we actually want.
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s %(request_id)s",
        rename_fields={
            "asctime": "timestamp",
            "levelname": "level",
            "name": "logger",
        },
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    handler.setFormatter(formatter)
    handler.addFilter(RequestIdFilter())
    handler.addFilter(PhiRedactingFilter())
    return handler


def configure_logging() -> None:
    """Replace all handlers with a single structured JSON handler.

    Call this once at application startup, before any other imports that
    might create loggers, so the entire process uses one consistent format.

    Also reconfigures uvicorn's loggers so they emit JSON through the same
    handler rather than mixing plain-text access lines with our JSON stream.
    """
    handler = _make_handler()

    # Root logger — catches everything not explicitly configured below.
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)

    # Uvicorn uses three loggers. Repoint them at our handler so the process
    # produces a single uniform JSON stream.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv_logger = logging.getLogger(name)
        uv_logger.handlers.clear()
        uv_logger.addHandler(handler)
        uv_logger.propagate = False
