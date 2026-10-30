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
"""

import contextvars
import logging
import re
import sys

from pythonjsonlogger import jsonlogger

# Holds the current request's trace ID. Set by RequestIdMiddleware on each
# incoming request; defaults to "-" when called outside an HTTP context
# (e.g. background scheduler jobs).
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)

# Fields that must never appear as plain values in logs.
_PHI_FIELDS = ("email", "phone", "dob")
# Matches  "field": "any value"  in JSON strings (both single and nested).
_PHI_PATTERN = re.compile(
    r'("(?:' + "|".join(_PHI_FIELDS) + r')"\s*:\s*)"[^"]*"',
    re.IGNORECASE,
)


class RequestIdFilter(logging.Filter):
    """Inject the current request_id into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class PhiRedactingFilter(logging.Filter):
    """Scrub PHI field values from log messages before formatting.

    Replaces the value of email, phone, and dob keys in JSON-like strings
    with "***". Never drops a record — always returns True.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        redacted = _PHI_PATTERN.sub(r'\1"***"', msg)
        if redacted != msg:
            record.msg = redacted
            record.args = ()
        return True


def configure_logging() -> None:
    """Replace the root logger's handlers with a single structured JSON handler.

    Call this once at application startup before any loggers are used.
    Existing logger.info() / logger.warning() call sites need no changes —
    only the output format changes.
    """
    root = logging.getLogger()
    # Remove any handlers added by basicConfig or imported libraries.
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    formatter = jsonlogger.JsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s %(request_id)s",
        rename_fields={"asctime": "timestamp", "levelname": "level", "name": "logger"},
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    handler.setFormatter(formatter)
    handler.addFilter(RequestIdFilter())
    handler.addFilter(PhiRedactingFilter())

    root.addHandler(handler)
    root.setLevel(logging.INFO)
