"""Retrieval and the text returned to the agent's ``search_clinic_docs`` tool.

Failure policy: if RAG is not configured, Postgres is unreachable or the
embeddings call fails, the tool returns a fixed "unavailable" string and the
rest of the agent keeps working. Questions are never logged (they may contain
personal details); only the exception type and, for a missing setting, the names of the unset env vars are.
"""

import logging
import os
import time
from typing import Any, List, Optional

from .store import Hit

logger = logging.getLogger(__name__)

from app.observability import annotate, metrics, span


DEFAULT_TOP_K = 4
# Chosen from the first real retrieval eval run (see README, M3 Numbers): at 0.40
# every labelled question is still answered correctly, while 0.50 starts losing
# correct answers. A similarity cut-off alone does not separate unanswerable
# questions (their top scores overlap the answerable range), so the model is
# also told to say so when the retrieved text does not answer the question.
DEFAULT_MIN_SCORE = 0.40

NO_INFO = (
    "No relevant clinic information found. Tell the patient you do not have "
    "that information and suggest calling the office."
)
UNAVAILABLE = (
    "The clinic knowledge base is unavailable right now. Tell the patient "
    "you cannot look that up and suggest calling the office."
)

_embedder = None  # type: Any
_store = None  # type: Any


def set_backends(embedder: Any, store: Any) -> None:
    """Inject backends (tests). Pass (None, None) to reset to environment config."""
    global _embedder, _store
    _embedder, _store = embedder, store


def is_configured() -> bool:
    if _embedder is not None and _store is not None:
        return True
    return bool(os.getenv("RAG_DATABASE_URL") and os.getenv("COHERE_API_KEY"))


def _backends() -> Any:
    global _embedder, _store
    if _embedder is None or _store is None:
        from .embeddings import get_embedder
        from .store import get_store

        _embedder, _store = get_embedder(), get_store()
    if _embedder is None or _store is None:
        missing = [n for n in ("RAG_DATABASE_URL", "COHERE_API_KEY") if not os.getenv(n)]
        raise RuntimeError("RAG is not configured: not set: %s" % ", ".join(missing))
    return _embedder, _store


def search_docs(
    question: str,
    k: Optional[int] = None,
    min_score: Optional[float] = None,
    embedder: Any = None,
    store: Any = None,
) -> List[Hit]:
    """Top-k chunks with similarity >= min_score, best first."""
    if embedder is None or store is None:
        embedder, store = _backends()
    k = k or int(os.getenv("RAG_TOP_K", DEFAULT_TOP_K))
    if min_score is None:
        min_score = float(os.getenv("RAG_MIN_SCORE", DEFAULT_MIN_SCORE))
    t0 = time.perf_counter()
    vector = embedder.embed([question], "search_query")[0]
    t1 = time.perf_counter()
    raw = store.search(vector, k)
    t2 = time.perf_counter()
    hits = [(c, s) for c, s in raw if s >= min_score]
    annotate(embed_ms=round((t1 - t0) * 1000), search_ms=round((t2 - t1) * 1000),
             hits=len(hits), top_score=round(max([s for _, s in raw] or [0.0]), 2))
    return hits


def format_hits(hits: List[Hit]) -> str:
    if not hits:
        return NO_INFO
    return "\n\n".join("[Source: %s]\n%s" % (c.title, c.content) for c, _ in hits)


def _reason(exc: Exception) -> str:
    """Short, safe reason for the log. Only our own "not configured" message
    (it names env vars, never values) is shown; for anything else (driver or
    network errors can embed connection strings or keys) just the type."""
    if isinstance(exc, RuntimeError) and str(exc).startswith("RAG is not configured"):
        return str(exc)
    return "see exception type"


def _fallback_reason(exc: Exception) -> str:
    """Token-like reason for traces. Names the missing settings, never values."""
    text = str(exc)
    prefix = "RAG is not configured: not set: "
    if isinstance(exc, RuntimeError) and text.startswith(prefix):
        return "not_configured:" + text[len(prefix):].replace(" ", "")
    return "error"


def lookup(question: str) -> str:
    """Entry point used by the agent tool. Never raises."""
    if not question or not question.strip():
        return NO_INFO
    t0 = time.perf_counter()
    with span("rag.lookup") as sp:
        try:
            hits = search_docs(question)
            outcome = "hit" if hits else "no_hit"
            result = format_hits(hits)
        except Exception as exc:  # noqa: BLE001 - degrade, do not break the agent
            logger.warning("[RAG] lookup unavailable (%s): %s", type(exc).__name__, _reason(exc))
            outcome, result = "unavailable", UNAVAILABLE
            sp.set(error_type=type(exc).__name__, fallback_reason=_fallback_reason(exc))
        sp.set(outcome=outcome)
    metrics.inc("rag_lookups_total", outcome=outcome)
    metrics.observe("rag_lookup_duration_ms", (time.perf_counter() - t0) * 1000)
    return result
