"""M3 retrieval eval: does search find the right clinic document?

Spends no Groq tokens. Needs only COHERE_API_KEY (and RAG_DATABASE_URL for --pg).

    cd backend
    python evals/run_retrieval_eval.py            # compare chunk granularities in memory
    python evals/run_retrieval_eval.py --pg       # score the table that is actually deployed

Questions are in retrieval_questions.json: answerable ones are labelled with the
document that answers them; unanswerable ones are covered by no document.

Reported per configuration:
  hit@1 / hit@k  - expected document is the top result / within the top k chunks
  MRR@10         - mean reciprocal rank of the first chunk from the expected document
  threshold table - for each minimum-similarity cut-off: share of answerable
                    questions still answered with the right document, and share of
                    unanswerable questions correctly rejected (nothing above cut-off)

The questions and documents are synthetic and few, so these numbers are
optimistic. Choosing a threshold from this same set is also optimistic.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

sys.path.insert(0, str(Path(__file__).parent.parent))

QUESTIONS_FILE = Path(__file__).parent / "retrieval_questions.json"
RESULTS_FILE = Path(__file__).parent / "results" / "retrieval-latest.json"
THRESHOLDS = [0.0, 0.2, 0.3, 0.4, 0.5, 0.6]
RANK_DEPTH = 10

# ranker(question) -> [(source, similarity), ...] best first
Ranker = Callable[[str], List[Tuple[str, float]]]


def first_rank(expected: str, ranked: Sequence[Tuple[str, float]]) -> Optional[int]:
    """1-based rank of the first result from the expected document, else None."""
    for i, (source, _) in enumerate(ranked, start=1):
        if source == expected:
            return i
    return None


def evaluate(
    answerable: List[Dict[str, str]],
    unanswerable: List[str],
    ranker: Ranker,
    k: int = 4,
    thresholds: Sequence[float] = tuple(THRESHOLDS),
) -> Dict[str, Any]:
    ranks = []
    misses = []
    ranked_answerable = []
    for item in answerable:
        ranked = ranker(item["question"])
        ranked_answerable.append(ranked)
        r = first_rank(item["source"], ranked)
        ranks.append(r)
        if r is None or r > k:
            misses.append({"question": item["question"], "expected": item["source"],
                           "rank": r, "top": ranked[0][0] if ranked else None})
    n = len(answerable)
    ranked_unanswerable = [ranker(q) for q in unanswerable]
    top_unanswerable = [r[0][1] if r else 0.0 for r in ranked_unanswerable]

    table = []
    for t in thresholds:
        answered = sum(
            1 for item, ranked in zip(answerable, ranked_answerable)
            if any(src == item["source"] and sc >= t for src, sc in ranked[:k])
        )
        rejected = sum(1 for top in top_unanswerable if top < t)
        table.append({
            "threshold": t,
            "answerable_answered": answered / n if n else 0.0,
            "unanswerable_rejected": rejected / len(unanswerable) if unanswerable else None,
        })
    return {
        "n_answerable": n,
        "n_unanswerable": len(unanswerable),
        "k": k,
        "hit_at_1": sum(1 for r in ranks if r == 1) / n if n else 0.0,
        "hit_at_k": sum(1 for r in ranks if r is not None and r <= k) / n if n else 0.0,
        "mrr_at_10": sum(1.0 / r for r in ranks if r is not None and r <= RANK_DEPTH) / n if n else 0.0,
        "misses": misses,
        "unanswerable_top_scores": [round(x, 3) for x in top_unanswerable],
        "thresholds": table,
    }


def print_report(name: str, res: Dict[str, Any]) -> None:
    print("\n== %s ==" % name)
    print("answerable=%d unanswerable=%d k=%d" % (res["n_answerable"], res["n_unanswerable"], res["k"]))
    print("hit@1 %.0f%%   hit@%d %.0f%%   MRR@10 %.3f" % (
        res["hit_at_1"] * 100, res["k"], res["hit_at_k"] * 100, res["mrr_at_10"]))
    print("min score | answerable answered | unanswerable rejected")
    for row in res["thresholds"]:
        rej = "n/a" if row["unanswerable_rejected"] is None else "%.0f%%" % (row["unanswerable_rejected"] * 100)
        print("   %.2f   |        %3.0f%%         |        %s" % (
            row["threshold"], row["answerable_answered"] * 100, rej))
    print("top similarity of unanswerable questions:", res["unanswerable_top_scores"])
    for m in res["misses"]:
        print("  MISS: %r expected=%s rank=%s top=%s" % (m["question"], m["expected"], m["rank"], m["top"]))


def _memory_ranker(embedder: Any, by_heading: bool, max_words: int) -> Ranker:
    from app.rag.chunker import load_chunks
    from app.rag.store import InMemoryStore

    chunks = load_chunks(by_heading=by_heading, max_words=max_words)
    vecs = embedder.embed([c.content for c in chunks], "search_document")
    store = InMemoryStore()
    store.sync(chunks, {c.content_hash: v for c, v in zip(chunks, vecs)})

    def rank(question: str) -> List[Tuple[str, float]]:
        v = embedder.embed([question], "search_query")[0]
        return [(c.source, s) for c, s in store.search(v, RANK_DEPTH)]

    return rank


def _pg_ranker(embedder: Any, store: Any) -> Ranker:
    def rank(question: str) -> List[Tuple[str, float]]:
        v = embedder.embed([question], "search_query")[0]
        return [(c.source, s) for c, s in store.search(v, RANK_DEPTH)]

    return rank


def main() -> int:
    ap = argparse.ArgumentParser(description="Retrieval eval for clinic docs")
    ap.add_argument("--pg", action="store_true", help="score the deployed pgvector table")
    ap.add_argument("--k", type=int, default=4)
    ap.add_argument("--no-save", action="store_true")
    args = ap.parse_args()

    from app.rag.embeddings import get_embedder

    embedder = get_embedder()
    if embedder is None:
        print("ERROR: COHERE_API_KEY is not set (backend/.env or environment).")
        return 2
    data = json.loads(QUESTIONS_FILE.read_text())
    answerable, unanswerable = data["answerable"], data["unanswerable"]

    configs = []  # type: List[Tuple[str, Ranker]]
    if args.pg:
        from app.rag.store import get_store

        store = get_store()
        if store is None:
            print("ERROR: RAG_DATABASE_URL is not set.")
            return 2
        configs.append(("deployed pgvector table (%d rows)" % store.count(), _pg_ranker(embedder, store)))
    else:
        configs.append(("per-section chunks (default)", _memory_ranker(embedder, True, 150)))
        configs.append(("one chunk per document", _memory_ranker(embedder, False, 150)))

    results = {}
    for name, ranker in configs:
        res = evaluate(answerable, unanswerable, ranker, k=args.k)
        results[name] = res
        print_report(name, res)
    if not args.no_save:
        RESULTS_FILE.parent.mkdir(exist_ok=True)
        RESULTS_FILE.write_text(json.dumps(results, indent=2))
        print("\nSaved %s" % RESULTS_FILE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
