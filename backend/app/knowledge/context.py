"""Business knowledge for a question, or none (RAG R6).

Knowledge is retrieved only for data sources with a catalog: the knowledge pack describes the
retail business, not the 12-row sample. Retrieval helps but is never required, so when the
embedding model or the index is unavailable the question goes ahead without knowledge and the
failure is logged.
"""
import logging

from app.access import uses_catalog
from app.knowledge.embeddings import EmbeddingError
from app.knowledge.retrieval import retrieve
from app.knowledge.store import KnowledgeUnavailable

logger = logging.getLogger("bi_agent")


def knowledge_for(question, role):
    if not uses_catalog():
        return []
    try:
        return retrieve(question, role)
    except (EmbeddingError, KnowledgeUnavailable) as e:
        logger.warning("knowledge retrieval failed", extra={"error": type(e).__name__, "detail": str(e)[:200]})
        return []
