import pytest
from fastapi.testclient import TestClient

from app.bi.schema import get_schema, metrics_text, schema_text
from app.main import app

client = TestClient(app)

EXPECTED = {
    "orders": [
        ("id", "integer"),
        ("order_date", "date"),
        ("region_id", "integer"),
        ("status", "text"),
        ("amount", "numeric"),
    ],
    "regions": [("id", "integer"), ("name", "text")],
}


def as_pairs(schema):
    return {t: [(c["column"], c["type"]) for c in cols] for t, cols in schema.items()}


@pytest.mark.integration
def test_schema_has_only_allowed_tables_and_columns():
    assert as_pairs(get_schema()) == EXPECTED


@pytest.mark.integration
def test_internal_notes_is_absent():
    assert "internal_notes" not in get_schema()
    assert "internal_notes" not in schema_text()


def test_metrics_text_mentions_revenue():
    assert "revenue" in metrics_text()


@pytest.mark.integration
def test_schema_endpoint():
    r = client.get("/schema")
    assert r.status_code == 200
    assert as_pairs(r.json()) == EXPECTED