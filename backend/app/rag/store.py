"""Vector stores: pgvector on Postgres (production) and in-memory (tests, eval).

Both expose the same small interface so ingest, retrieval and tests do not
care which one they talk to. psycopg2 is imported lazily so the rest of the
app (and CI) never needs a Postgres driver unless RAG is actually used.
"""

import math
import os
from typing import Dict, List, Optional, Sequence, Set, Tuple

from .chunker import Chunk
from .embeddings import EMBED_DIM

Hit = Tuple[Chunk, float]  # (chunk, cosine similarity, higher is closer)


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class InMemoryStore:
    def __init__(self) -> None:
        self._rows = {}  # type: Dict[str, Tuple[Chunk, List[float]]]

    def init_schema(self) -> None:
        pass

    def existing_hashes(self) -> Set[str]:
        return set(self._rows)

    def sync(self, chunks: List[Chunk], vectors: Dict[str, List[float]]) -> Tuple[int, int]:
        """Make the store match ``chunks``. Returns (inserted, deleted).

        ``vectors`` maps content_hash -> embedding for chunks not yet stored.
        """
        wanted = {c.content_hash: c for c in chunks}
        deleted = [h for h in self._rows if h not in wanted]
        for h in deleted:
            del self._rows[h]
        inserted = 0
        for h, chunk in wanted.items():
            if h not in self._rows:
                self._rows[h] = (chunk, list(vectors[h]))
                inserted += 1
        return inserted, len(deleted)

    def search(self, vector: Sequence[float], k: int) -> List[Hit]:
        scored = [(c, cosine(vector, v)) for c, v in self._rows.values()]
        scored.sort(key=lambda hit: hit[1], reverse=True)
        return scored[:k]

    def count(self) -> int:
        return len(self._rows)


def _vec(v: Sequence[float]) -> str:
    return "[" + ",".join("%.8g" % x for x in v) + "]"


class PgVectorStore:
    def __init__(self, url: str, dim: int = EMBED_DIM) -> None:
        from sqlalchemy import create_engine

        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]
        self.dim = dim
        self.engine = create_engine(
            url, pool_pre_ping=True, connect_args={"connect_timeout": 5}
        )

    def init_schema(self) -> None:
        from sqlalchemy import text

        with self.engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.execute(text(
                "CREATE TABLE IF NOT EXISTS doc_chunks ("
                " id BIGSERIAL PRIMARY KEY,"
                " source TEXT NOT NULL,"
                " title TEXT NOT NULL,"
                " heading TEXT NOT NULL,"
                " content TEXT NOT NULL,"
                " content_hash TEXT NOT NULL UNIQUE,"
                " embedding vector(%d) NOT NULL,"
                " created_at TIMESTAMPTZ NOT NULL DEFAULT now())" % self.dim
            ))

    def existing_hashes(self) -> Set[str]:
        from sqlalchemy import text

        with self.engine.connect() as conn:
            return {r[0] for r in conn.execute(text("SELECT content_hash FROM doc_chunks"))}

    def sync(self, chunks: List[Chunk], vectors: Dict[str, List[float]]) -> Tuple[int, int]:
        from sqlalchemy import text

        wanted = {c.content_hash: c for c in chunks}
        have = self.existing_hashes()
        stale = [h for h in have if h not in wanted]
        inserted = 0
        with self.engine.begin() as conn:
            for h in stale:
                conn.execute(text("DELETE FROM doc_chunks WHERE content_hash = :h"), {"h": h})
            for h, c in wanted.items():
                if h in have:
                    continue
                vec = vectors[h]
                if len(vec) != self.dim:
                    raise ValueError(
                        "embedding has %d dimensions but the table expects %d" % (len(vec), self.dim)
                    )
                conn.execute(
                    text(
                        "INSERT INTO doc_chunks (source, title, heading, content, content_hash, embedding)"
                        " VALUES (:s, :t, :hd, :c, :h, CAST(:e AS vector))"
                        " ON CONFLICT (content_hash) DO NOTHING"
                    ),
                    {"s": c.source, "t": c.title, "hd": c.heading, "c": c.content,
                     "h": h, "e": _vec(vec)},
                )
                inserted += 1
        return inserted, len(stale)

    def search(self, vector: Sequence[float], k: int) -> List[Hit]:
        from sqlalchemy import text

        sql = text(
            "SELECT source, title, heading, content,"
            " 1 - (embedding <=> CAST(:q AS vector)) AS score"
            " FROM doc_chunks ORDER BY embedding <=> CAST(:q AS vector) LIMIT :k"
        )
        with self.engine.connect() as conn:
            rows = conn.execute(sql, {"q": _vec(vector), "k": k}).fetchall()
        return [(Chunk(r[0], r[1], r[2], r[3]), float(r[4])) for r in rows]

    def count(self) -> int:
        from sqlalchemy import text

        with self.engine.connect() as conn:
            return int(conn.execute(text("SELECT count(*) FROM doc_chunks")).scalar() or 0)


def get_store() -> Optional[PgVectorStore]:
    url = os.getenv("RAG_DATABASE_URL")
    return PgVectorStore(url) if url else None
