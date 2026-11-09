"""Offline tests for M3 RAG. No API keys, no network.

The pgvector test at the bottom runs only when RAG_TEST_DATABASE_URL points at
a throwaway Postgres database whose URL contains "test" (the test drops the
doc_chunks table there).

Run with: cd backend && python -m pytest tests/test_rag.py -v
"""
import json
import logging
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.rag import retrieval
from app.rag.chunker import DOCS_DIR, chunk_markdown, load_chunks
from app.rag.ingest import ingest
from app.rag.store import InMemoryStore
from rag_helpers import DIM, FakeEmbedder


@pytest.fixture(autouse=True)
def _reset_backends(monkeypatch):
    monkeypatch.delenv("RAG_DATABASE_URL", raising=False)
    monkeypatch.delenv("COHERE_API_KEY", raising=False)
    retrieval.set_backends(None, None)
    yield
    retrieval.set_backends(None, None)


def _loaded_store():
    chunks = load_chunks()
    emb = FakeEmbedder()
    store = InMemoryStore()
    ingest(chunks, emb, store)
    return emb, store


# --- chunker ----------------------------------------------------------------

DOC = "# Title A\n\n## One\nfirst section text.\n\n## Two\nsecond section text.\n"


def test_chunk_per_section_with_title_prefix():
    chunks = chunk_markdown("doc", DOC)
    assert [c.heading for c in chunks] == ["One", "Two"]
    assert chunks[0].content == "Title A - One: first section text."
    assert all(c.title == "Title A" and c.source == "doc" for c in chunks)


def test_long_section_split_with_overlap_and_no_loss():
    words = ["w%d" % i for i in range(100)]
    chunks = chunk_markdown("d", "# T\n\n## H\n" + " ".join(words), max_words=40, overlap=10)
    assert len(chunks) > 1
    joined = " ".join(c.content for c in chunks)
    assert all(w in joined.split() for w in words)
    first_tail = chunks[0].content.split()[-10:]
    assert all(w in chunks[1].content.split() for w in first_tail)


def test_whole_document_mode_is_one_chunk():
    chunks = chunk_markdown("doc", DOC, by_heading=False)
    assert len(chunks) == 1
    assert "first section" in chunks[0].content and "second section" in chunks[0].content


def test_real_corpus_every_doc_chunked_and_hashes_unique():
    chunks = load_chunks()
    sources = {c.source for c in chunks}
    assert sources == {p.stem for p in DOCS_DIR.glob("*.md")}
    assert len({c.content_hash for c in chunks}) == len(chunks)
    assert all(c.title for c in chunks)


# --- ingest -----------------------------------------------------------------

def test_ingest_is_idempotent():
    chunks = load_chunks()
    emb, store = FakeEmbedder(), InMemoryStore()
    first = ingest(chunks, emb, store)
    assert first["inserted"] == len(chunks) == store.count()
    embedded_before = emb.texts_embedded
    second = ingest(chunks, emb, store)
    assert second["embedded"] == 0 and second["inserted"] == 0 and second["deleted"] == 0
    assert emb.texts_embedded == embedded_before
    assert store.count() == len(chunks)


def test_ingest_replaces_changed_chunks_and_drops_stale():
    chunks = load_chunks()
    emb, store = FakeEmbedder(), InMemoryStore()
    ingest(chunks, emb, store)
    changed = chunk_markdown("cancellation-policy", "# Cancellation and Late Policy\n\n## Notice required\nNow 48 hours notice.")
    kept = [c for c in chunks if c.source != "cancellation-policy"]
    result = ingest(kept + changed, emb, store)
    assert result["embedded"] == 1 and result["inserted"] == 1
    assert result["deleted"] == len([c for c in chunks if c.source == "cancellation-policy"])
    assert store.count() == len(kept) + 1


# --- retrieval --------------------------------------------------------------

def test_relevant_question_returns_right_document_first():
    emb, store = _loaded_store()
    hits = retrieval.search_docs("what is the late cancellation fee", embedder=emb, store=store, min_score=0.1)
    assert hits and hits[0][0].source == "cancellation-policy"
    assert hits[0][1] >= hits[-1][1]


def test_threshold_rejects_unrelated_question():
    emb, store = _loaded_store()
    assert retrieval.search_docs("zzzz qqqq xxxx", embedder=emb, store=store, min_score=0.3) == []


def test_top_k_respected():
    emb, store = _loaded_store()
    assert len(retrieval.search_docs("insurance billing", k=2, embedder=emb, store=store, min_score=0.0)) == 2


def test_format_hits_cites_source_title_and_empty_is_fixed_string():
    emb, store = _loaded_store()
    hits = retrieval.search_docs("late cancellation fee", embedder=emb, store=store, min_score=0.1)
    text = retrieval.format_hits(hits)
    assert "[Source: Cancellation and Late Policy]" in text and "$50" in text
    assert retrieval.format_hits([]) == retrieval.NO_INFO


def test_lookup_uses_injected_backends():
    emb, store = _loaded_store()
    retrieval.set_backends(emb, store)
    assert retrieval.is_configured()
    assert "$50" in retrieval.lookup("late cancellation fee")
    assert retrieval.lookup("zzzz qqqq xxxx") == retrieval.NO_INFO
    assert retrieval.lookup("   ") == retrieval.NO_INFO


def test_lookup_unavailable_when_not_configured():
    assert not retrieval.is_configured()
    assert retrieval.lookup("anything") == retrieval.UNAVAILABLE


def test_lookup_unavailable_on_error_and_never_logs_the_question(caplog):
    _, store = _loaded_store()
    retrieval.set_backends(FakeEmbedder(fail=True), store)
    with caplog.at_level(logging.WARNING):
        out = retrieval.lookup("my name is Jane Doe and my tooth hurts")
    assert out == retrieval.UNAVAILABLE
    assert "Jane" not in caplog.text and "tooth" not in caplog.text


# --- agent wiring -----------------------------------------------------------

def test_tool_registered_with_schema_and_dispatches_to_lookup():
    from app.agent.agent import OPENAI_TOOL_SCHEMAS, _TOOL_MAP, _SYSTEM_PROMPT

    names = [s["function"]["name"] for s in OPENAI_TOOL_SCHEMAS]
    assert "search_clinic_docs" in names
    assert "search_clinic_docs" in _SYSTEM_PROMPT
    emb, store = _loaded_store()
    retrieval.set_backends(emb, store)
    out = _TOOL_MAP["search_clinic_docs"].invoke({"question": "late cancellation fee"})
    assert "$50" in out


def test_tool_returns_unavailable_string_not_exception_when_unconfigured():
    from app.agent.agent import _TOOL_MAP

    assert _TOOL_MAP["search_clinic_docs"].invoke({"question": "hours?"}) == retrieval.UNAVAILABLE


# --- eval harness additions -------------------------------------------------

def test_knowledge_cases_are_well_formed():
    from evals.run_evals import CASES_FILE

    cases = json.loads(CASES_FILE.read_text())
    assert len({c["id"] for c in cases}) == len(cases)
    knowledge = [c for c in cases if c["category"] == "knowledge"]
    assert len(knowledge) == 6
    for c in knowledge:
        assert c["requires"] == "rag"
        assert c["expected_tools"] == ["search_clinic_docs"]
        assert "book_appointment" in c["forbidden_tools"]
    by_id = {c["id"]: c for c in cases}
    assert "search_clinic_docs" in by_id["slot-01"]["forbidden_tools"]


def test_filter_unavailable_skips_rag_cases_only_when_unconfigured():
    from evals.run_evals import filter_unavailable

    cases = [{"id": "a"}, {"id": "b", "requires": "rag"}]
    assert filter_unavailable(cases, True) == (cases, [])
    kept, skipped = filter_unavailable(cases, False)
    assert [c["id"] for c in kept] == ["a"] and [c["id"] for c in skipped] == ["b"]


def test_check_response_excludes():
    from evals.run_evals import check_response_excludes

    assert check_response_excludes(["$"], "I do not have pricing information")
    assert not check_response_excludes(["$"], "It costs $900")
    assert check_response_excludes([], "anything")


# --- retrieval eval metrics -------------------------------------------------

def test_first_rank_and_evaluate_metrics():
    from evals.run_retrieval_eval import evaluate, first_rank

    assert first_rank("a", [("b", 0.9), ("a", 0.5)]) == 2
    assert first_rank("z", [("b", 0.9)]) is None

    table = {
        "q1": [("a", 0.9), ("b", 0.2)],   # rank 1
        "q2": [("b", 0.8), ("a", 0.4)],   # rank 2
        "q3": [("c", 0.7)],               # miss
        "u1": [("b", 0.25)],              # unanswerable, weak match
        "u2": [("b", 0.55)],              # unanswerable, strong match (bad)
    }
    answerable = [{"question": "q1", "source": "a"}, {"question": "q2", "source": "a"},
                  {"question": "q3", "source": "a"}]
    res = evaluate(answerable, ["u1", "u2"], lambda q: table[q], k=2, thresholds=[0.0, 0.3, 0.6])
    assert res["hit_at_1"] == pytest.approx(1 / 3)
    assert res["hit_at_k"] == pytest.approx(2 / 3)
    assert res["mrr_at_10"] == pytest.approx((1 + 0.5) / 3)
    assert [m["question"] for m in res["misses"]] == ["q3"]
    rows = {r["threshold"]: r for r in res["thresholds"]}
    assert rows[0.0]["unanswerable_rejected"] == 0.0
    assert rows[0.3]["unanswerable_rejected"] == 0.5
    assert rows[0.6]["answerable_answered"] == pytest.approx(1 / 3)


# --- real Postgres + pgvector (optional) ------------------------------------

_PG = os.getenv("RAG_TEST_DATABASE_URL", "")


@pytest.mark.skipif("test" not in _PG, reason="set RAG_TEST_DATABASE_URL to a throwaway DB whose URL contains 'test'")
def test_pgvector_store_roundtrip_and_idempotent():
    from sqlalchemy import text
    from app.rag.store import PgVectorStore

    store = PgVectorStore(_PG, dim=DIM)
    with store.engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS doc_chunks"))
    try:
        store.init_schema()
        store.init_schema()  # idempotent
        chunks = load_chunks()
        emb = FakeEmbedder()
        first = ingest(chunks, emb, store)
        assert first["inserted"] == len(chunks) == store.count()
        second = ingest(chunks, emb, store)
        assert second["embedded"] == 0 and second["inserted"] == 0
        retrieval.set_backends(emb, store)
        hits = retrieval.search_docs("late cancellation fee", min_score=0.1)
        assert hits and hits[0][0].source == "cancellation-policy"
        assert "$50" in retrieval.lookup("late cancellation fee")
        # a chunk removed from the docs is deleted from the table
        result = ingest(chunks[1:], emb, store)
        assert result["deleted"] == 1 and store.count() == len(chunks) - 1
    finally:
        with store.engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS doc_chunks"))


def test_unavailable_log_names_missing_env_vars_but_no_secrets(caplog, monkeypatch):
    retrieval.set_backends(None, None)
    monkeypatch.delenv("RAG_DATABASE_URL", raising=False)
    monkeypatch.setenv("COHERE_API_KEY", "sk-secret-value")
    with caplog.at_level(logging.WARNING):
        assert retrieval.lookup("Where do I park?") == retrieval.UNAVAILABLE
    assert "RAG_DATABASE_URL" in caplog.text
    assert "COHERE_API_KEY" not in caplog.text
    assert "sk-secret-value" not in caplog.text


def test_unavailable_log_hides_driver_error_text(caplog):
    class Boom:
        def embed(self, *a):
            raise RuntimeError("postgresql://user:pw@host/db failed")

    retrieval.set_backends(Boom(), object())
    with caplog.at_level(logging.WARNING):
        retrieval.lookup("hours?")
    retrieval.set_backends(None, None)
    assert "pw@host" not in caplog.text and "RuntimeError" in caplog.text
