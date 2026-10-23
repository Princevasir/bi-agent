"""Retrieving business knowledge for a question (RAG R5).

Embeds the question with the same model as the index, then searches with the app's read-only login.
Only active documents shared with the user's role, embedded by the same model, and of the requested
types can come back, all filtered in SQL. Weak matches are dropped and the total size is capped,
with every setting from the [knowledge] section of the policy file.
"""
import os
from dataclasses import dataclass

from app import policy
from app.knowledge.embeddings import get_embedder
from app.knowledge.store import Reader


@dataclass(frozen=True)
class Hit:
    chunk_id: str
    document_id: str
    title: str
    doc_type: str
    owner: str
    version: int
    source: str
    content: str
    token_count: int
    score: float


def retrieve(question, role, top_k=None, types=None, min_similarity=None, max_context_tokens=None,
             embedder=None, url=None, schema="knowledge"):
    settings = policy.get().knowledge
    top_k = top_k or settings["top_k"]
    min_similarity = settings["min_similarity"] if min_similarity is None else min_similarity
    max_context_tokens = max_context_tokens or settings["max_context_tokens"]
    embedder = embedder or get_embedder()
    reader = Reader(url or os.getenv("APP_DATABASE_URL"), schema)
    rows = reader.search(embedder.embed_query(question), embedder.model_id, role, top_k, types)
    hits, used = [], 0
    for row in rows:
        hit = Hit(*row[:9], score=round(float(row[9]), 4))
        if hit.score < min_similarity:
            continue
        if used + hit.token_count > max_context_tokens:
            break
        hits.append(hit)
        used += hit.token_count
    return hits
