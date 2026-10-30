"""Tests for the structured logging and PHI redaction layer.

All tests are offline — no API key or running server required.

The helper _capture_log uses the real _make_handler() from logging_config,
so these tests exercise the actual production configuration rather than a
reimplemented copy of it.

Run with: cd backend && py -m pytest tests/test_logging.py -v
"""

import io
import json
import logging

import pytest

from app.logging_config import (
    PhiRedactingFilter,
    RequestIdFilter,
    _make_handler,
    request_id_var,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _capture_log(message: str, level: int = logging.INFO, **kwargs) -> dict:
    """Emit one log line through the real handler and return it as a dict.

    Replaces the handler's stdout stream with a StringIO buffer so we can
    inspect the output without touching sys.stdout.
    """
    handler = _make_handler()
    buf = io.StringIO()
    handler.stream = buf

    logger = logging.getLogger("_test_logging")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    logger.log(level, message, **kwargs)
    return json.loads(buf.getvalue().strip())


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
    # taskName is added to LogRecord in Python 3.12+. It should be excluded
    # via reserved_attrs in _make_handler so it never appears in JSON output.
    record = _capture_log("taskName check")
    assert "taskName" not in record


# ---------------------------------------------------------------------------
# PHI redaction — double-quoted JSON strings
# ---------------------------------------------------------------------------


def test_email_redacted_in_json():
    record = _capture_log('{"email": "jane@example.com", "name": "Jane"}')
    assert "jane@example.com" not in record["message"]
    assert "***" in record["message"]


def test_phone_redacted_in_json():
    record = _capture_log('{"phone": "555-1234"}')
    assert "555-1234" not in record["message"]


def test_dob_redacted_in_json():
    record = _capture_log('{"dob": "1990-01-01"}')
    assert "1990-01-01" not in record["message"]


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


def test_mixed_quotes_redacted():
    # Value uses different quote character than key — backreference handles this.
    record = _capture_log("""{'email': "o'brien@x.com"}""")
    assert "o'brien@x.com" not in record["message"]


# ---------------------------------------------------------------------------
# PHI redaction — URL query-string form (backstop for any log containing URLs)
# ---------------------------------------------------------------------------


def test_email_redacted_in_query_string():
    record = _capture_log("GET /patients?email=jane@example.com&name=jane HTTP/1.1")
    assert "jane@example.com" not in record["message"]


def test_phone_redacted_in_query_string():
    record = _capture_log("path=/search?phone=555-1234&limit=10")
    assert "555-1234" not in record["message"]


# ---------------------------------------------------------------------------
# PHI redaction — exception text (traceback with parameter tuples)
# ---------------------------------------------------------------------------


def test_exc_info_redacted():
    try:
        raise ValueError("parameters: ('Jane', '1990-01-01', 'jane@example.com')")
    except ValueError:
        import sys
        record = _capture_log("db error", exc_info=sys.exc_info())

    # exc_text is embedded in the JSON output; check the full serialised record
    raw = json.dumps(record)
    assert "jane@example.com" not in raw
    assert "1990-01-01" not in raw


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


# ---------------------------------------------------------------------------
# Middleware — request ID injection and response header
# ---------------------------------------------------------------------------


def test_middleware_echoes_supplied_request_id():
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    from starlette.testclient import TestClient

    from app.middleware import RequestIdMiddleware

    def homepage(request):
        return JSONResponse({"ok": True})

    app = Starlette(routes=[Route("/", homepage)])
    app.add_middleware(RequestIdMiddleware)

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/", headers={"X-Request-ID": "fixed-id-123"})
    assert response.headers.get("X-Request-ID") == "fixed-id-123"


def test_middleware_generates_id_when_absent():
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    from starlette.testclient import TestClient

    from app.middleware import RequestIdMiddleware

    def homepage(request):
        return JSONResponse({"ok": True})

    app = Starlette(routes=[Route("/", homepage)])
    app.add_middleware(RequestIdMiddleware)

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/")
    rid = response.headers.get("X-Request-ID", "")
    assert len(rid) == 36  # UUID4 format: 8-4-4-4-12


def test_middleware_injects_id_into_request_context():
    """The request_id_var ContextVar must hold the correct ID during the handler."""
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    from starlette.testclient import TestClient

    from app.logging_config import request_id_var
    from app.middleware import RequestIdMiddleware

    captured = {}

    def homepage(request):
        captured["id"] = request_id_var.get()
        return JSONResponse({"ok": True})

    app = Starlette(routes=[Route("/", homepage)])
    app.add_middleware(RequestIdMiddleware)

    client = TestClient(app, raise_server_exceptions=False)
    client.get("/", headers={"X-Request-ID": "ctx-test-99"})
    assert captured.get("id") == "ctx-test-99"
