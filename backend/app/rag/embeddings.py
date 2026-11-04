"""Embeddings client. One function, one provider (Cohere REST API).

The Cohere request/response shape below is written from the public v2 embed
docs and has NOT been run against the live API from this repo yet; the first
real ingest is the check. Texts and the API key are never logged.
"""

import os
import time
from typing import List, Optional

import httpx

COHERE_URL = "https://api.cohere.com/v2/embed"
DEFAULT_MODEL = "embed-english-v3.0"
EMBED_DIM = 1024          # embed-english-v3.0; verified at ingest from the response
_BATCH = 96               # Cohere's per-request text limit
_RETRY_STATUS = {429, 500, 502, 503, 504}


class EmbeddingError(RuntimeError):
    pass


class CohereEmbedder:
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL,
                 timeout: float = 15.0, retries: int = 3):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.retries = retries

    def embed(self, texts: List[str], input_type: str) -> List[List[float]]:
        """input_type: 'search_document' for chunks, 'search_query' for questions."""
        out = []  # type: List[List[float]]
        for start in range(0, len(texts), _BATCH):
            out.extend(self._post(texts[start:start + _BATCH], input_type))
        return out

    def _post(self, batch: List[str], input_type: str) -> List[List[float]]:
        payload = {
            "model": self.model,
            "texts": batch,
            "input_type": input_type,
            "embedding_types": ["float"],
        }
        headers = {"Authorization": "Bearer %s" % self.api_key}
        last = "no attempt"
        for attempt in range(self.retries + 1):
            try:
                resp = httpx.post(COHERE_URL, json=payload, headers=headers,
                                  timeout=self.timeout)
            except httpx.HTTPError as exc:
                last = type(exc).__name__
            else:
                if resp.status_code == 200:
                    vectors = resp.json()["embeddings"]["float"]
                    if len(vectors) != len(batch):
                        raise EmbeddingError("Cohere returned a different number of vectors")
                    return vectors
                last = "HTTP %d" % resp.status_code
                if resp.status_code not in _RETRY_STATUS:
                    raise EmbeddingError("Cohere request failed: %s" % last)
            if attempt < self.retries:
                time.sleep(2 ** attempt)
        raise EmbeddingError("Cohere request failed after retries: %s" % last)


def get_embedder() -> Optional[CohereEmbedder]:
    key = os.getenv("COHERE_API_KEY")
    if not key:
        return None
    return CohereEmbedder(key, model=os.getenv("COHERE_EMBED_MODEL", DEFAULT_MODEL))
