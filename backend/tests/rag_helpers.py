"""Test doubles for M3 RAG tests: a deterministic embedder that needs no network."""

import hashlib
import math
import re
from typing import List

DIM = 64


class FakeEmbedder:
    """Hashed bag-of-words. Texts sharing words get similar vectors."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0
        self.texts_embedded = 0

    def embed(self, texts: List[str], input_type: str) -> List[List[float]]:
        self.calls += 1
        if self.fail:
            raise RuntimeError("embeddings down")
        self.texts_embedded += len(texts)
        out = []
        for text in texts:
            vec = [0.0] * DIM
            for word in re.findall(r"[a-z0-9$]+", text.lower()):
                h = int(hashlib.md5(word.encode()).hexdigest(), 16)
                vec[h % DIM] += 1.0
            norm = math.sqrt(sum(x * x for x in vec)) or 1.0
            out.append([x / norm for x in vec])
        return out
