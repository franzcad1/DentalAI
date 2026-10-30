"""Structured logging configuration for DentalAI.

Sets up JSON-formatted logs so every line is machine-readable and can be
ingested by any log aggregator (Datadog, CloudWatch, Loki) without a
custom parser.

Three layers of PHI protection:
1. Source discipline: agent.py logs input_keys only; bus.py logs ID fields only.
2. PhiRedactingFilter: scrubs email/phone/dob from log messages at emit time.
   Covers both JSON  "email": "value"  and Python-repr  'email': 'value'  using
   a backreference so values containing the other quote character are handled
   correctly. Also covers URL query-string form  email=value.
3. PhiRedactingJsonFormatter: overrides formatException so SQLAlchemy
   IntegrityError messages (which embed parameter tuples) are scrubbed before
   they are serialised into the JSON exc_text field.

Uvicorn's access log is suppressed because RequestIdMiddleware already emits a
structured request-completed line with method, path, status, and duration_ms.
This also eliminates query-string leaks from the uvicorn access line format
'GET /patients?email=… HTTP/1.1'.
"""

import contextvars
import logging
import re
import sys

from pythonjsonlogger import jsonlogger

# ---------------------------------------------------------------------------
# Per-request trace ID
# ---------------------------------------------------------------------------

# Set by RequestIdMiddleware on each incoming request.
# Defaults to "-" in scheduler threads and seed scripts that have no request
# context — that is expected and safe.
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)

# ---------------------------------------------------------------------------
# PHI patterns
# ---------------------------------------------------------------------------

_PHI_FIELDS = ("email", "phone", "dob")

# Matches key-value pairs in JSON or Python repr.
# Group 1 captures everything up to the opening value quote (key + colon).
# Group 3 captures the opening value quote so we can use it as the closing
# quote in the replacement — this handles values that contain the OTHER quote
# character, e.g. 'email': "o'brien@x.com".
_PHI_KV = re.compile(
    r'((["\'])(?:' + "|".join(_PHI_FIELDS) + r')\2\s*:\s*)(["\'])((?:(?!\3).)*)\3',
    re.IGNORECASE,
)

# Matches URL query-string form: email=a@b.com, phone=555, dob=1990-01-01.
# Stops at whitespace, &, quotes, or < so it doesn't eat the rest of the line.
_PHI_QS = re.compile(
    r'((?:' + "|".join(_PHI_FIELDS) + r')=)[^\s&"\'<>]+',
    re.IGNORECASE,
)

# Exception messages from DB adapters (e.g. SQLAlchemy IntegrityError) embed raw
# parameter values WITHOUT a field-name context, e.g.:
#   ValueError: parameters: ('Jane', '1990-01-01', 'jane@example.com', '(555) 123-4567')
# The patterns below catch email, ISO dates, and phone numbers as bare values.
_EMAIL_BARE = re.compile(r'[\w.+%-]+@[\w.-]+\.[a-zA-Z]{2,}')

# Only match dates in single or double quotes to avoid redacting file paths and
# version strings that happen to contain four-digit sequences.
_DATE_QUOTED = re.compile(r'(["\'])(\d{4}-\d{2}-\d{2})\1')

# Covers the most common North-American phone formats:
#   (555) 123-4567   — seed data format
#   555-123-4567     — hyphen-separated
#   555.123.4567     — dot-separated
#   +1-555-123-4567  — with country code
# Using word-boundary / paren anchors keeps this from matching shorter IDs or
# timestamps (HH:MM:SS is 2-2-2, not 3-3-4 digits).
_PHONE_BARE = re.compile(
    r'(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b'
)


def _redact(text: str) -> str:
    """Apply key-value and query-string PHI redaction patterns to *text*."""
    text = _PHI_KV.sub(r'\1\3***\3', text)
    text = _PHI_QS.sub(r'\1***', text)
    return text


def _redact_exc(text: str) -> str:
    """Stronger redaction for exception text and any message that may embed bare values.

    Adds email, quoted-date, and phone patterns on top of the standard key-value
    pass because database adapters embed raw parameter tuples without field-name
    context, and log.error("fail: %s", exc) exposes the exception message directly.

    Order matters: _PHONE_BARE runs before _PHI_QS so that a space-formatted phone
    in a query-string value (phone=(555) 123-4567) is replaced whole before _PHI_QS
    can stop at the space and leave the trailing digits exposed.
    """
    text = _PHI_KV.sub(r'\1\3***\3', text)
    text = _EMAIL_BARE.sub('***', text)
    text = _DATE_QUOTED.sub(r'\1***\1', text)
    text = _PHONE_BARE.sub('***', text)
    text = _PHI_QS.sub(r'\1***', text)
    return text


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------


class RequestIdFilter(logging.Filter):
    """Inject the current request_id into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()  # type: ignore[attr-defined]
        return True


class PhiRedactingFilter(logging.Filter):
    """Scrub PHI field values from log messages and exception text before formatting.

    Handles three surfaces:
    - record.msg / args: the main log message
    - record.exc_info: pre-formats the traceback and redacts it, then clears
      exc_info so the formatter uses our version instead of reformatting it
    - record.exc_text: redacts any already-cached exception text

    Never drops a record — always returns True.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        # Use the stronger _redact_exc on the message too: logger.error("fail: %s", exc)
        # exposes bare exception text (including email / phone from parameter tuples)
        # directly in the message line without any key-value context.
        msg = record.getMessage()
        redacted = _redact_exc(msg)
        if redacted != msg:
            record.msg = redacted
            record.args = ()

        # Pre-format exception info, redact it, then clear exc_info so the
        # formatter (json-logger) uses our exc_text rather than reformatting.
        if record.exc_info:
            import traceback as _tb
            raw = "".join(_tb.format_exception(*record.exc_info))
            record.exc_text = _redact_exc(raw)
            record.exc_info = None  # prevent formatter re-formatting
        elif record.exc_text:
            record.exc_text = _redact_exc(record.exc_text)

        return True


# ---------------------------------------------------------------------------
# Formatter
# ---------------------------------------------------------------------------


class PhiRedactingJsonFormatter(jsonlogger.JsonFormatter):
    """JSON formatter that redacts PHI from exception text.

    The base JsonFormatter calls formatException() after the message filter
    runs, so exc_info (e.g. SQLAlchemy IntegrityError with parameter tuples)
    would bypass PhiRedactingFilter. Overriding formatException and format
    here closes that gap.
    """

    def formatException(self, exc_info) -> str:  # type: ignore[override]
        return _redact_exc(super().formatException(exc_info))

    def format(self, record: logging.LogRecord) -> str:
        # Pre-populate exc_text with the redacted version so the parent's
        # format() uses our scrubbed text rather than regenerating it.
        if record.exc_info and not record.exc_text:
            record.exc_text = self.formatException(record.exc_info)
        return super().format(record)


# ---------------------------------------------------------------------------
# Handler factory (used by configure_logging and tests)
# ---------------------------------------------------------------------------

# taskName was added to LogRecord in Python 3.12. python-json-logger 2.0.7's
# default RESERVED_ATTRS predates that, so it would appear in JSON output on
# 3.12+. Import the default list and extend it.
try:
    from pythonjsonlogger.jsonlogger import RESERVED_ATTRS as _BASE_RESERVED
    _RESERVED_ATTRS = list(_BASE_RESERVED) + ["taskName"]
except ImportError:  # pragma: no cover — older library version
    _RESERVED_ATTRS = ["taskName"]


def _make_handler() -> logging.StreamHandler:  # type: ignore[type-arg]
    """Build and return a configured JSON stream handler.

    Exported so tests can create an identical handler pointed at a
    StringIO buffer rather than stdout.
    """
    handler = logging.StreamHandler(sys.stdout)
    formatter = PhiRedactingJsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s %(request_id)s",
        rename_fields={
            "asctime": "timestamp",
            "levelname": "level",
            "name": "logger",
        },
        datefmt="%Y-%m-%dT%H:%M:%S",
        reserved_attrs=_RESERVED_ATTRS,
    )
    handler.setFormatter(formatter)
    handler.addFilter(RequestIdFilter())
    handler.addFilter(PhiRedactingFilter())
    return handler


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def configure_logging() -> None:
    """Replace all handlers with a single structured JSON handler.

    Call once at application startup, before any other imports that might
    create loggers, so the entire process produces one uniform JSON stream.
    """
    handler = _make_handler()

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)

    # Repoint uvicorn's error logger at our handler.
    for name in ("uvicorn", "uvicorn.error"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.addHandler(handler)
        lg.propagate = False

    # Suppress uvicorn's access log entirely — RequestIdMiddleware already
    # emits a structured request-completed line (method, path, status,
    # duration_ms). Keeping the access log would also leak query strings
    # such as ?email=… in its 'GET /path?email=… HTTP/1.1' format.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
