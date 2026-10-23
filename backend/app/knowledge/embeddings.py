"""Embeddings for the knowledge index (RAG R3).

One interface, two implementations: OllamaEmbedder calls a local Ollama server through its
OpenAI-compatible /v1/embeddings endpoint; FakeEmbedder makes deterministic vectors for tests.
Every vector is checked (count, size, finite numbers) before it can reach the index, and each
embedder names its model (model_id) so the index never mixes vectors from two models.
"""
import hashlib
import math
import os
import re

import httpx

from app import policy

BATCH = 32
WORD = re.compile(r"[a-z0-9]+")


class EmbeddingError(Exception):
    """The embedding model could not be reached or returned something unusable."""


def _check(vectors, count, dimensions):
    if len(vectors) != count:
        raise EmbeddingError(f"The embedding model returned {len(vectors)} vectors, expected {count}.")
    for v in vectors:
        if len(v) != dimensions:
            raise EmbeddingError(f"The embedding model returned {len(v)} numbers per vector, expected {dimensions}.")
        if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in v):
            raise EmbeddingError("The embedding model returned numbers that are not finite.")
    return vectors


class OllamaEmbedder:
    def __init__(self, base_url, model, dimensions, client=None, timeout=60.0):
        self.url = f"{base_url.rstrip('/')}/embeddings"
        self.model, self.dimensions = model, dimensions
        self.model_id = f"ollama:{model}"
        self.client = client or httpx.Client(timeout=httpx.Timeout(timeout, connect=5.0))
        # nomic-embed-text is trained with task prefixes; without them retrieval quality drops.
        self.prefixes = ("search_document: ", "search_query: ") if "nomic" in model else ("", "")

    def _embed(self, texts):
        out = []
        for start in range(0, len(texts), BATCH):
            batch = texts[start:start + BATCH]
            try:
                resp = self.client.post(self.url, json={"model": self.model, "input": batch})
                resp.raise_for_status()
                data = resp.json()["data"]
                vectors = [d["embedding"] for d in sorted(data, key=lambda d: d["index"])]
            except httpx.TimeoutException as e:
                raise EmbeddingError("The embedding model timed out.") from e
            except httpx.HTTPStatusError as e:
                raise EmbeddingError(f"The embedding model refused the request: HTTP {e.response.status_code}.") from e
            except httpx.HTTPError as e:
                raise EmbeddingError("Could not reach the embedding model.") from e
            except (KeyError, TypeError, ValueError) as e:
                raise EmbeddingError("The embedding model returned an unexpected response.") from e
            out += _check(vectors, len(batch), self.dimensions)
        return out

    def embed_documents(self, texts):
        return self._embed([self.prefixes[0] + t for t in texts])

    def embed_query(self, text):
        return self._embed([self.prefixes[1] + text])[0]


class FakeEmbedder:
    """Deterministic bag-of-words vectors: free, offline, and related text still lands close."""

    def __init__(self, dimensions):
        self.dimensions = dimensions
        self.model_id = f"fake:{dimensions}"

    def _vector(self, text):
        v = [0.0] * self.dimensions
        for word in WORD.findall(text.lower()):
            digest = hashlib.sha256(word.encode()).digest()
            v[int.from_bytes(digest[:4], "big") % self.dimensions] += 1.0 if digest[4] % 2 else -1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    def embed_documents(self, texts):
        return [self._vector(t) for t in texts]

    def embed_query(self, text):
        return self._vector(text)


def get_embedder():
    """The embedder chosen by EMBEDDING_PROVIDER (ollama by default), sized by the policy file."""
    dimensions = policy.get().knowledge["embedding_dimensions"]
    provider = os.getenv("EMBEDDING_PROVIDER", "ollama")
    if provider == "fake":
        return FakeEmbedder(dimensions)
    if provider == "ollama":
        return OllamaEmbedder(os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
                              os.getenv("EMBEDDING_MODEL", "nomic-embed-text"), dimensions)
    raise EmbeddingError(f"Unknown EMBEDDING_PROVIDER: {provider}")
