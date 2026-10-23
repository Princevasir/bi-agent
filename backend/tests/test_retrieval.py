"""RAG R5: retrieving knowledge chunks, filtered by role, status, type and embedding model."""
import json
import shutil
from pathlib import Path

import psycopg
import pytest

from app import policy
from app.knowledge import retrieval
from app.knowledge.documents import KNOWLEDGE_DIR, load
from app.knowledge.embeddings import FakeEmbedder
from app.knowledge.ingest import ingest
from evals import retrieval as reval
from test_ingest import ADMIN, WRITER, test_schema  # noqa: F401  (the throwaway schema fixture)

APP = "postgresql://app_rw:app_dev_pw@localhost:5433/appdb"
CASES = Path(__file__).resolve().parents[1] / "evals" / "retrieval_cases.json"


@pytest.fixture
def index(test_schema, tmp_path):
    pack = tmp_path / "knowledge"
    shutil.copytree(KNOWLEDGE_DIR, pack)
    ingest(pack, FakeEmbedder(768), url=WRITER, schema=test_schema)
    with psycopg.connect(ADMIN, autocommit=True) as conn:
        conn.execute(f"GRANT USAGE ON SCHEMA {test_schema} TO app_rw")
        conn.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA {test_schema} TO app_rw")
    return test_schema


def find(question, role="analyst", **kw):
    # The policy threshold is calibrated for nomic-embed-text; fake-embedder scores are not comparable.
    kw.setdefault("min_similarity", 0.0)
    return retrieval.retrieve(question, role, embedder=FakeEmbedder(768), url=APP, schema="knowledge_test", **kw)


# ---- the component ------------------------------------------------------------------------------------------

@pytest.mark.integration
def test_relevant_chunks_come_back_with_their_source(index):
    hits = find("fiscal calendar fiscal year starts 1 February FY2025")
    assert hits[0].document_id == "rule-fiscal-calendar"
    h = hits[0]
    assert h.title == "Fiscal calendar" and h.doc_type == "rule" and h.owner == "Finance" and h.version == 1
    assert 0 < h.score <= 1 and "1 February" in h.content


@pytest.mark.integration
def test_limited_users_never_get_analyst_only_knowledge(index):
    analyst_only = {d.id for d in load(KNOWLEDGE_DIR) if "limited" not in d.access_groups}
    for q in ("revenue completed orders cancelled", "fiscal year", "products and prices", "tent supply incident"):
        assert not {h.document_id for h in find(q, role="limited", top_k=20)} & analyst_only


@pytest.mark.integration
def test_superseded_documents_are_never_retrieved(index):
    hits = find("exclude cancelled and staff orders staff accounts", top_k=20)
    assert "rule-exclude-cancelled-orders-v1" not in {h.document_id for h in hits}


@pytest.mark.integration
def test_types_and_result_count_can_be_limited(index):
    hits = find("revenue", types=("sql_example",), top_k=3)
    assert len(hits) == 3 and {h.doc_type for h in hits} == {"sql_example"}


@pytest.mark.integration
def test_weak_matches_are_dropped(index):
    assert find("zzzz qqqq", min_similarity=0.5) == []


@pytest.mark.integration
def test_vectors_from_another_model_are_never_compared(index):
    class Other(FakeEmbedder):
        def __init__(self):
            super().__init__(768)
            self.model_id = "other:768"

    assert retrieval.retrieve("revenue", "analyst", embedder=Other(), url=APP, schema="knowledge_test") == []


@pytest.mark.integration
def test_the_context_size_is_capped(index):
    hits = find("revenue orders customers stores", top_k=20, max_context_tokens=300)
    assert sum(h.token_count for h in hits) <= 300 and hits


def test_settings_come_from_the_policy():
    k = policy.get().knowledge
    assert k["top_k"] >= 1 and 0 <= k["min_similarity"] < 1 and k["max_context_tokens"] > 0


# ---- the retrieval evaluation ---------------------------------------------------------------------------------

def test_metrics():
    assert reval.recall_at_k(["a", "b", "c"], {"a", "x"}, 3) == 0.5
    assert reval.precision_at_k(["a", "b", "c", "d"], {"a", "c"}, 4) == 0.5
    assert reval.reciprocal_rank(["b", "a"], {"a"}) == 0.5
    assert reval.reciprocal_rank(["b"], {"a"}) == 0.0


def test_the_labelled_questions_are_valid():
    cases = json.loads(CASES.read_text())["cases"]
    docs = {d.id: d for d in load(KNOWLEDGE_DIR)}
    assert len(cases) >= 30
    assert len({c["id"] for c in cases}) == len(cases)
    for c in cases:
        assert c["relevant"], c["id"]
        for doc_id in c["relevant"]:
            assert doc_id in docs and docs[doc_id].status == "active", (c["id"], doc_id)
            assert c.get("role", "analyst") in docs[doc_id].access_groups, (c["id"], doc_id)


# ---- the calibrated threshold, on the real local model and the real index ---------------------------------------

@pytest.mark.integration
@pytest.mark.parametrize("question,expected", [
    ("hello", None), ("What's the weather in Paris tomorrow?", None), ("Write me a poem about the sea", None),
    ("How many orders were cancelled in 2025?", "rule-exclude-cancelled-orders"),
    ("What was revenue by region in 2025?", "sql-revenue-by-region"),
])
def test_off_topic_questions_retrieve_nothing_and_data_questions_still_do(question, expected):
    from app.knowledge.embeddings import EmbeddingError, OllamaEmbedder
    try:
        hits = retrieval.retrieve(question, "analyst", embedder=OllamaEmbedder(
            "http://localhost:11434/v1", "nomic-embed-text", 768), url=APP)
    except EmbeddingError as err:
        pytest.skip(f"local Ollama not available: {err}")
    if expected is None:
        assert hits == []
    else:
        assert expected in {h.document_id for h in hits}
