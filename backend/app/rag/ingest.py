"""Load the clinic documents into the vector store.

    cd backend
    python -m app.rag.ingest --dry-run   # chunk only, needs no keys
    python -m app.rag.ingest --init      # create extension/table, then ingest

Needs RAG_DATABASE_URL and COHERE_API_KEY (backend/.env is read if present).
Idempotent: unchanged chunks are not re-embedded or duplicated; chunks that no
longer exist in the documents are deleted. Run it from your own machine, not on
Render.
"""

import argparse
import sys
from collections import Counter
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
except ImportError:
    pass

from .chunker import DEFAULT_MAX_WORDS, DEFAULT_OVERLAP, load_chunks
from .embeddings import EMBED_DIM, get_embedder
from .store import get_store


def ingest(chunks, embedder, store) -> dict:
    """Embed only chunks the store does not have, then sync. Returns counts."""
    have = store.existing_hashes()
    todo = []
    seen = set()
    for c in chunks:
        if c.content_hash not in have and c.content_hash not in seen:
            seen.add(c.content_hash)
            todo.append(c)
    vectors = {}
    if todo:
        embedded = embedder.embed([c.content for c in todo], "search_document")
        vectors = {c.content_hash: v for c, v in zip(todo, embedded)}
    inserted, deleted = store.sync(chunks, vectors)
    return {"chunks": len(chunks), "embedded": len(todo),
            "inserted": inserted, "deleted": deleted, "total": store.count()}


def main() -> int:
    p = argparse.ArgumentParser(description="Ingest clinic docs into pgvector")
    p.add_argument("--init", action="store_true", help="create extension and table first")
    p.add_argument("--dry-run", action="store_true", help="chunk only; no network or database")
    p.add_argument("--max-words", type=int, default=DEFAULT_MAX_WORDS)
    args = p.parse_args()

    chunks = load_chunks(max_words=args.max_words, overlap=DEFAULT_OVERLAP)
    per_doc = Counter(c.source for c in chunks)
    print("%d chunks from %d documents" % (len(chunks), len(per_doc)))
    if args.dry_run:
        for source, n in sorted(per_doc.items()):
            print("  %-26s %d" % (source, n))
        return 0

    embedder, store = get_embedder(), get_store()
    if embedder is None or store is None:
        print("ERROR: set RAG_DATABASE_URL and COHERE_API_KEY (backend/.env).")
        return 2
    if args.init:
        store.init_schema()
        print("Schema ready (vector extension + doc_chunks, %d dims)." % EMBED_DIM)
    result = ingest(chunks, embedder, store)
    print("embedded=%(embedded)d inserted=%(inserted)d deleted=%(deleted)d "
          "rows_in_table=%(total)d" % result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
