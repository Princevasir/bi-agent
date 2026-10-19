import pytest
from fastapi.testclient import TestClient

from app.db import DBError, run_readonly
from app.main import app

client = TestClient(app)


@pytest.mark.integration
def test_select_one():
    assert run_readonly("SELECT 1 AS result")["rows"] == [[1]]


@pytest.mark.integration
def test_known_aggregation():
    result = run_readonly("SELECT sum(amount) FROM orders WHERE status = 'completed'")
    assert result["rows"] == [[1380.0]]


@pytest.mark.integration
def test_db_ping_endpoint():
    r = client.get("/db/ping")
    assert r.status_code == 200
    assert r.json()["rows"] == [[1]]


def test_missing_database_url_raises(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(DBError):
        run_readonly("SELECT 1")