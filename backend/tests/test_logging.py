"""Tests for the structured logging and PHI redaction layer.

All tests are offline — no API key or running server required.

Run with: cd backend && py -m pytest tests/test_logging.py -v
"""

import json
import logging
import io

import pytest

from app.logging_config import (
    PhiRedactingFilter,
    RequestIdFilter,
    configure_logging,
    request_id_var,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _capture_log(message: str, level: int = logging.INFO) -> dict:
    """Emit one log line through a fresh handler and return it parsed as JSON."""
    from pythonjsonlogger import jsonlogger

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    formatter = jsonlogger.JsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s %(request_id)s",
        rename_fields={"asctime": "timestamp", "levelname": "level", "name": "logger"},
    )
    handler.setFormatter(formatter)
    handler.addFilter(RequestIdFilter())
    handler.addFilter(PhiRedactingFilter())

    logger = logging.getLogger("_test_logging")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    logger.log(level, message)
    raw = stream.getvalue().strip()
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Structured output
# ---------------------------------------------------------------------------


def test_output_is_valid_json():
    record = _capture_log("hello world")
    assert record["message"] == "hello world"
    assert "timestamp" in record
    assert "level" in record
    assert "logger" in record


def test_request_id_defaults_to_dash():
    record = _capture_log("check default id")
    assert record["request_id"] == "-"


def test_request_id_flows_from_contextvar():
    token = request_id_var.set("test-req-abc")
    try:
        record = _capture_log("check injected id")
    finally:
        request_id_var.reset(token)
    assert record["request_id"] == "test-req-abc"


def test_task_name_not_in_output():
    record = _capture_log("taskName check")
    assert "taskName" not in record


# ---------------------------------------------------------------------------
# PHI redaction — double-quoted JSON strings
# ---------------------------------------------------------------------------


def test_email_redacted_in_json():
    record = _capture_log('{"email": "jane@example.com", "name": "Jane"}')
    assert "jane@example.com" not in record["message"]
    assert '"email": "***"' in record["message"]


def test_phone_redacted_in_json():
    record = _capture_log('{"phone": "555-1234"}')
    assert "555-1234" not in record["message"]
    assert '"phone": "***"' in record["message"]


def test_dob_redacted_in_json():
    record = _capture_log('{"dob": "1990-01-01"}')
    assert "1990-01-01" not in record["message"]
    assert '"dob": "***"' in record["message"]


def test_name_not_redacted():
    record = _capture_log('{"name": "Jane Doe", "email": "jane@example.com"}')
    assert "Jane Doe" in record["message"]


# ---------------------------------------------------------------------------
# PHI redaction — single-quoted Python repr (agent tool-call logs)
# ---------------------------------------------------------------------------


def test_email_redacted_in_python_repr():
    record = _capture_log("input={'email': 'jane@example.com', 'phone': '555-1'}")
    assert "jane@example.com" not in record["message"]
    assert "555-1" not in record["message"]


def test_dob_redacted_in_python_repr():
    record = _capture_log("input={'dob': '1990-01-01', 'first_name': 'Jane'}")
    assert "1990-01-01" not in record["message"]
    assert "Jane" in record["message"]


# ---------------------------------------------------------------------------
# Non-PHI lines pass through unchanged
# ---------------------------------------------------------------------------


def test_non_phi_line_unchanged():
    msg = "[AGENT] tool_call=check_available_slots input_keys=['date_from', 'date_to']"
    record = _capture_log(msg)
    assert record["message"] == msg


def test_event_line_with_ids_unchanged():
    msg = "[EVENT] appointment.booked event_id=42 patient_id=3 | appointment_type=cleaning"
    record = _capture_log(msg)
    assert record["message"] == msg
