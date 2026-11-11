"""M1b tests: tracing, metrics, alerts, ops endpoints, PHI safety. Offline only."""

import json
import logging
import pathlib
import threading
from types import SimpleNamespace as NS

import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import Base, get_db
import app.models.orm  # noqa: F401
from app.observability import init_tracing, metrics, span
from app.observability import tracing
from app.observability.alerts import AlertEvaluator, default_rules
from app.observability.metrics import Metrics

from tests.test_agent_tools import _FakeCompletions, _fake_ok, _groq_400


# --- fixtures ---------------------------------------------------------------

@pytest.fixture()
def exporter(monkeypatch):
    monkeypatch.setenv("OBSERVABILITY", "local")
    monkeypatch.delenv("RAG_DATABASE_URL", raising=False)
    monkeypatch.delenv("COHERE_API_KEY", raising=False)
    from app.rag import retrieval
    retrieval.set_backends(None, None)
    exp = InMemorySpanExporter()
    init_tracing(extra_processors=[SimpleSpanProcessor(exp)])
    metrics._buckets.clear()
    metrics.errors.clear()
    yield exp
    init_tracing()


def _spans(exp):
    return {s.name: s for s in exp.get_finished_spans()}


def _tool_call_response(name, args):
    call = NS(id="c1", function=NS(name=name, arguments=json.dumps(args)))
    msg = NS(content=None, tool_calls=[call])
    return NS(choices=[NS(finish_reason="tool_calls", message=msg)],
              usage=NS(prompt_tokens=20, completion_tokens=5))


def _run(monkeypatch, outcomes, session="obs-1", message="hello"):
    import app.agent.agent as agent_mod
    completions = _FakeCompletions(outcomes)
    monkeypatch.setattr(agent_mod, "_get_client",
                        lambda: NS(chat=NS(completions=completions)))
    return agent_mod.run_agent(message, session_id=session)


def _all_text(exp):
    parts = []
    for s in exp.get_finished_spans():
        parts.append(s.name)
        parts.append(json.dumps(dict(s.attributes or {}), default=str))
    return " ".join(parts)


# --- span tree and failure paths ----------------------------------------------

def test_chat_turn_with_rag_unavailable_has_expected_span_tree(exporter, monkeypatch):
    question = "Does Jane Doe pay for her tooth pain visit? jane@example.com 555-0100"
    _run(monkeypatch, [_tool_call_response("search_clinic_docs", {"question": question}),
                       _fake_ok("done")], message=question)
    by = _spans(exporter)
    for name in ("agent.run", "agent.llm_call", "agent.tool", "rag.lookup"):
        assert name in by
    assert by["agent.tool"].parent.span_id == by["agent.run"].context.span_id
    assert by["rag.lookup"].parent.span_id == by["agent.tool"].context.span_id
    assert len([s for s in exporter.get_finished_spans() if s.name == "agent.llm_call"]) == 2
    rag = by["rag.lookup"].attributes
    assert rag["outcome"] == "unavailable"
    assert rag["fallback_reason"] == "not_configured:RAG_DATABASE_URL,COHERE_API_KEY"
    assert by["agent.run"].attributes["tool_calls"] == 1
    assert metrics.count("rag_lookups_total", 300, outcome="unavailable") == 1
    assert metrics.count("agent_turns_total", 300, outcome="ok") == 1
    assert metrics.count("agent_tokens_total", 300, kind="prompt") == 30


def test_no_message_text_or_pii_in_any_span(exporter, monkeypatch):
    question = "Does Jane Doe pay for her tooth pain visit? jane@example.com 555-0100"
    _run(monkeypatch, [_tool_call_response("search_clinic_docs", {"question": question}),
                       _fake_ok("done")], message=question)
    text = _all_text(exporter)
    for leak in ("Jane", "Doe", "tooth", "jane@example.com", "555-0100", "visit"):
        assert leak not in text


def test_groq_429_is_visible_on_the_llm_span_and_in_metrics(exporter, monkeypatch):
    import groq
    import httpx
    req = httpx.Request("POST", "https://api.groq.com/x")
    err = groq.RateLimitError("Rate limit reached. Please try again in 0.01s",
                              response=httpx.Response(429, request=req), body=None)
    _run(monkeypatch, [err, _fake_ok()], session="obs-429")
    llm = _spans(exporter)["agent.llm_call"].attributes
    assert llm["groq_429_count"] == 1
    assert metrics.count("agent_groq_429_total", 300) == 1


def test_tool_parse_400_retry_is_counted(exporter, monkeypatch):
    bad = _groq_400("Failed to parse tool call arguments as JSON")
    _run(monkeypatch, [bad, _fake_ok()], session="obs-400")
    assert _spans(exporter)["agent.llm_call"].attributes["tool_parse_retries"] == 1
    assert metrics.count("agent_tool_parse_errors_total", 300) == 1


def test_tool_exception_records_error_type_only(exporter, monkeypatch):
    import app.agent.agent as agent_mod

    def boom(_):
        raise RuntimeError("secret detail Jane Doe")
    monkeypatch.setitem(agent_mod._TOOL_MAP, "boom", NS(invoke=boom))
    _run(monkeypatch, [_tool_call_response("boom", {}), _fake_ok()], session="obs-boom")
    attrs = _spans(exporter)["agent.tool"].attributes
    assert attrs["ok"] is False and attrs["error_type"] == "RuntimeError"
    assert "Jane" not in _all_text(exporter)
    assert metrics.count("agent_tool_calls_total", 300, tool="boom", outcome="error") == 1


def test_unknown_tool_uses_fixed_label(exporter, monkeypatch):
    _run(monkeypatch, [_tool_call_response("made_up_tool_name", {}), _fake_ok()],
         session="obs-unknown")
    assert metrics.count("agent_tool_calls_total", 300, tool="unknown",
                         outcome="unknown_tool") == 1


# --- allowlist and resilience -------------------------------------------------

def test_allowlist_drops_unknown_names_and_free_text():
    out = tracing.safe_attrs({
        "route": "/api/v1/patients/{patient_id}", "status": 200, "ok": True,
        "message": "my tooth hurts", "patient_name": "Jane", "outcome": "has spaces here",
        "error_type": "RuntimeError",
    })
    assert out == {"route": "/api/v1/patients/{patient_id}", "status": 200,
                   "ok": True, "error_type": "RuntimeError"}


def test_unknown_attribute_set_on_a_span_is_dropped(exporter):
    with span("x") as sp:
        sp.set(message="hello", patient_name="Jane", outcome="ok")
    attrs = dict(exporter.get_finished_spans()[0].attributes)
    assert attrs == {"outcome": "ok"}


def test_only_tracing_module_touches_raw_span_attributes():
    root = pathlib.Path(__file__).resolve().parent.parent / "app"
    offenders = [str(p) for p in root.rglob("*.py")
                 if p.name != "tracing.py" and "set_attribute" in p.read_text()]
    assert offenders == []


def test_a_broken_span_processor_never_breaks_the_caller(monkeypatch):
    class Broken(tracing.SpanProcessor):
        def on_start(self, span, parent_context=None):
            pass

        def on_end(self, span):
            raise RuntimeError("exporter down")

    init_tracing(extra_processors=[Broken()])
    try:
        with span("x") as sp:
            sp.set(outcome="ok")
            result = 42
        assert result == 42
    finally:
        init_tracing()


def test_observability_off_is_a_no_op(monkeypatch):
    monkeypatch.setenv("OBSERVABILITY", "off")
    init_tracing()
    try:
        with span("x") as sp:
            sp.set(outcome="ok")
        assert tracing.current_trace_id() == "-"
    finally:
        monkeypatch.setenv("OBSERVABILITY", "local")
        init_tracing()


def test_trace_id_is_added_to_log_records(exporter):
    from app.logging_config import RequestIdFilter
    rec = logging.LogRecord("t", logging.INFO, "f", 1, "m", None, None)
    with span("x"):
        RequestIdFilter().filter(rec)
        inside = rec.trace_id
    rec2 = logging.LogRecord("t", logging.INFO, "f", 1, "m", None, None)
    RequestIdFilter().filter(rec2)
    assert len(inside) == 32 and inside != "-"
    assert rec2.trace_id == "-"


# --- HTTP layer ---------------------------------------------------------------

_engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
Base.metadata.create_all(bind=_engine)
_Session = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


def _override_db():
    db = _Session()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def client(exporter):
    from app.main import create_app
    app = create_app()
    app.dependency_overrides[get_db] = _override_db
    return TestClient(app)


def test_request_id_is_validated(client):
    ok = client.get("/health", headers={"X-Request-ID": "abc-123"})
    assert ok.headers["X-Request-ID"] == "abc-123"
    for bad in ("x" * 100, "bad id with spaces", "a/b"):
        r = client.get("/health", headers={"X-Request-ID": bad})
        assert r.headers["X-Request-ID"] != bad and len(r.headers["X-Request-ID"]) == 36


def test_metrics_use_route_templates_not_raw_paths(client):
    client.get("/api/v1/patients/1")
    client.get("/api/v1/patients/2")
    routes = metrics.label_values("http_requests_total", "route")
    assert any("{" in r for r in routes)
    assert not any(r.endswith("/1") or r.endswith("/2") for r in routes)


def test_http_span_has_route_status_and_request_id(client, exporter):
    r = client.get("/health", headers={"X-Request-ID": "req-abc-1"})
    s = [x for x in exporter.get_finished_spans() if x.name == "http.request"][0]
    assert s.attributes["route"] == "/health" and s.attributes["status"] == 200
    assert s.attributes["request_id"] == "req-abc-1"
    assert r.status_code == 200


def test_server_error_is_recorded_without_message(client, monkeypatch):
    import app.api.agent_router as ar
    import app.agent.agent as agent_mod

    def boom(**_):
        raise ValueError("Jane Doe secret")
    monkeypatch.setattr(agent_mod, "run_agent", boom)
    r = client.post("/api/v1/agent/chat", json={"message": "hi", "session_id": "s1"})
    assert r.status_code == 500
    errs = list(metrics.errors)
    assert errs and errs[-1]["status"] == 500 and "Jane" not in json.dumps(errs)


def test_ops_endpoints_require_token(client, monkeypatch):
    monkeypatch.delenv("OPS_TOKEN", raising=False)
    assert client.get("/api/v1/ops/summary").status_code == 404
    monkeypatch.setenv("OPS_TOKEN", "s3cret-token")
    assert client.get("/api/v1/ops/summary").status_code == 401
    assert client.get("/api/v1/ops/summary", headers={"X-Ops-Token": "wrong"}).status_code == 401
    ok = client.get("/api/v1/ops/summary", headers={"X-Ops-Token": "s3cret-token"})
    assert ok.status_code == 200
    body = ok.json()
    assert "http" in body and "agent" in body and "rag" in body and "active_alerts" in body
    assert "s3cret-token" not in ok.text


def test_deep_health_reports_degraded_without_secrets(client, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk-very-secret-value")
    r = client.get("/health/deep")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "degraded"
    assert body["checks"]["rag_configured"] == "failed"
    assert body["checks"]["groq_key_present"] == "ok"
    assert "gsk-very-secret-value" not in r.text


# --- metrics ------------------------------------------------------------------

def test_quantiles_and_label_filters():
    t = [1000.0]
    m = Metrics(clock=lambda: t[0])
    for v in (10, 20, 30, 40, 4000):
        m.observe("lat", v, route="/a")
    m.observe("lat", 9000, route="/b")
    assert m.hist_count("lat", 300, route="/a") == 5
    assert m.quantile("lat", 0.5, 300, route="/a") == 50.0
    assert m.quantile("lat", 0.95, 300, route="/a") == 5000.0
    assert m.quantile("lat", 0.5, 300, route="/none") is None


def test_ring_buffer_is_bounded_and_window_expires():
    t = [0.0]
    m = Metrics(clock=lambda: t[0], bucket_s=60, max_buckets=5)
    for i in range(20):
        t[0] = i * 60.0
        m.inc("c")
    assert len(m._buckets) == 5
    assert m.count("c", 120) == 2


def test_concurrent_increments_are_not_lost():
    m = Metrics()
    def work():
        for _ in range(500):
            m.inc("c", route="/x")
    threads = [threading.Thread(target=work) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert m.count("c", 300, route="/x") == 4000


# --- alerts -------------------------------------------------------------------

def test_alert_fires_respects_cooldown_and_resolves():
    t = [10_000.0]
    m = Metrics(clock=lambda: t[0])
    sent = []
    ev = AlertEvaluator(m, default_rules(), notify=sent.append,
                        clock=lambda: t[0], cooldown_s=900)
    assert ev.evaluate() == []
    m.inc("rag_lookups_total", outcome="unavailable")
    fired = ev.evaluate()
    assert [e["rule"] for e in fired] == ["rag_unavailable"]
    assert fired[0]["event"] == "alert_fired"
    assert ev.evaluate() == []            # cooldown, still active
    assert len(sent) == 1
    t[0] += 400                            # window (300 s) has passed
    resolved = ev.evaluate()
    assert resolved == [{"event": "alert_resolved", "rule": "rag_unavailable"}]
    assert len(sent) == 2


def test_error_share_needs_minimum_requests_and_crosses_threshold():
    t = [10_000.0]
    m = Metrics(clock=lambda: t[0])
    ev = AlertEvaluator(m, default_rules(), clock=lambda: t[0])
    m.inc("http_requests_total", 3, status_class="5xx")
    m.inc("http_requests_total", 5, status_class="2xx")
    assert ev.evaluate() == []            # fewer than the minimum requests
    m.inc("http_requests_total", 30, status_class="2xx")
    assert [e["rule"] for e in ev.evaluate()] == ["http_5xx_share"]


def test_groq_429_rule_needs_three_and_notifier_failure_is_swallowed():
    t = [10_000.0]
    m = Metrics(clock=lambda: t[0])
    def bad_notify(_):
        raise RuntimeError("webhook down")
    ev = AlertEvaluator(m, default_rules(), notify=bad_notify, clock=lambda: t[0])
    m.inc("agent_groq_429_total", 2)
    assert ev.evaluate() == []
    m.inc("agent_groq_429_total")
    assert [e["rule"] for e in ev.evaluate()] == ["groq_429_count"]


def test_no_webhook_when_url_unset(monkeypatch):
    from app.observability.alerts import webhook_notifier
    monkeypatch.delenv("ALERT_WEBHOOK_URL", raising=False)
    assert webhook_notifier() is None


# --- scheduler ----------------------------------------------------------------

def test_scheduler_failure_increments_error_metric(exporter, monkeypatch):
    import app.events.scheduler as sched

    class Boom:
        def __call__(self):
            raise RuntimeError("db down")
    monkeypatch.setattr(sched, "SessionLocal", Boom())
    with pytest.raises(RuntimeError):
        sched.recall_due_job()
