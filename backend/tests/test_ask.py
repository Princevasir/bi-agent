import pytest
from fastapi.testclient import TestClient

from app.db import run_readonly
from app.llm import get_llm
from app.llm.base import LLMResult
from app.main import app

client = TestClient(app)

REVENUE_BY_REGION = """SELECT r.name AS region_name, SUM(o.amount) AS revenue
FROM orders o
JOIN regions r ON o.region_id = r.id
WHERE o.status = 'completed' AND o.order_date BETWEEN '2026-09-01' AND '2026-09-30'
GROUP BY r.name;"""

SEPTEMBER_REVENUE = (
    "SELECT SUM(amount) AS revenue FROM orders "
    "WHERE status = 'completed' AND order_date >= '2026-09-01' AND order_date < '2026-10-01'"
)


class ScriptedLLM:
    def __init__(self, text):
        self.text = text

    def generate(self, prompt):
        return LLMResult(text=self.text, input_tokens=1, output_tokens=1)


def script(text):
    app.dependency_overrides[get_llm] = lambda: ScriptedLLM(text)


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


def order_count():
    return run_readonly("SELECT count(*) FROM orders")["rows"]


@pytest.mark.integration
@pytest.mark.parametrize("bad_sql", [
    "DROP TABLE orders",
    "DELETE FROM orders",
    "SELECT * FROM internal_notes",
    "I cannot help with that.",
])
def test_malicious_sql_is_rejected_and_data_untouched(bad_sql):
    script(bad_sql)
    r = client.post("/ask", json={"message": "anything"})
    assert r.status_code == 422
    assert r.json() == {"detail": "The generated query was rejected."}
    assert order_count() == [[12]]


@pytest.mark.integration
def test_september_revenue_is_810():
    script(SEPTEMBER_REVENUE)
    r = client.post("/ask", json={"message": "What was revenue in September 2026?"})
    assert r.status_code == 200
    assert r.json()["rows"] == [[810.0]]
    assert r.json()["truncated"] is False


@pytest.mark.integration
def test_revenue_by_region_matches_seed():
    script(REVENUE_BY_REGION)
    r = client.post("/ask", json={"message": "Revenue by region in September 2026?"})
    assert r.status_code == 200
    assert r.json()["columns"] == ["region_name", "revenue"]
    assert sorted(r.json()["rows"]) == [["North", 270.0], ["South", 300.0], ["West", 240.0]]