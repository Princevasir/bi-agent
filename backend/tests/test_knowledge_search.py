"""Demo gap D10: GET /knowledge/search, the backend route behind the MCP search_knowledge tool."""
import pytest
from fastapi.testclient import TestClient

from app.knowledge.retrieval import Hit
from app.main import app, get_knowledge


# ---- the backend route the second tool uses -------------------------------------------------------------------

def hit():
    return Hit(chunk_id="rule-fiscal-calendar#0", document_id="rule-fiscal-calendar", title="Fiscal calendar",
               doc_type="rule", owner="Finance", version=1, source="x.md", content="The fiscal year runs from 1 February.",
               token_count=9, score=0.86)


def test_knowledge_search_returns_the_role_s_documents_and_is_audited(audit_events):
    asked = []
    app.dependency_overrides[get_knowledge] = lambda: (lambda q, role: asked.append((q, role)) or [hit()])
    r = TestClient(app).get("/knowledge/search", params={"q": "fiscal year"})
    assert r.status_code == 200
    assert r.json()["hits"][0] == {"document_id": "rule-fiscal-calendar", "title": "Fiscal calendar", "doc_type": "rule",
                                   "owner": "Finance", "version": 1, "score": 0.86,
                                   "content": "The fiscal year runs from 1 February."}
    assert asked == [("fiscal year", "analyst")]
    assert audit_events[-1]["event"] == "knowledge_search"


@pytest.mark.parametrize("q", ["", "x" * 501])
def test_knowledge_search_needs_a_sensible_query(q):
    assert TestClient(app).get("/knowledge/search", params={"q": q}).status_code == 422
