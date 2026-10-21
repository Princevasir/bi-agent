import os
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

from app import audit, main
from app.llm import get_llm
from app.main import app
from routed_llm import RoutedLLM

client = TestClient(app)
REAL_WRITE = audit._write  # captured at import, before conftest patches it

TOTAL = (
    "SELECT SUM(amount) AS revenue FROM orders WHERE status = 'completed' "
    "AND order_date >= '2026-09-01' AND order_date < '2026-10-01'"
)


@pytest.fixture(autouse=True)
def clear_llm_override():
    yield
    app.dependency_overrides.pop(get_llm, None)


def test_secret_fields_are_never_recorded(audit_events):
    audit.record("x", password="p", token="t", note="ok")
    assert audit_events[-1]["detail"] == {"note": "ok"}


def test_failed_login_is_audited_without_the_password(audit_events, monkeypatch):
    monkeypatch.setattr(main, "get_user", lambda name: None)
    r = client.post("/auth/login", json={"username": "Alice", "password": "hunter2-secret"})
    assert r.status_code == 401
    [event] = [e for e in audit_events if e["event"] == "login_failure"]
    assert event["username"] == "alice" and event["status_code"] == 401
    assert "hunter2-secret" not in repr(audit_events)


def test_audit_failure_does_not_break_the_request(monkeypatch):
    def broken(entry):
        raise RuntimeError("audit store down")

    monkeypatch.setattr(audit, "_write", broken)
    monkeypatch.setattr(main, "get_user", lambda name: None)
    r = client.post("/auth/login", json={"username": "a", "password": "b"})
    assert r.status_code == 401


@pytest.mark.integration
def test_ask_is_audited_without_result_data(audit_events):
    app.dependency_overrides[get_llm] = lambda: RoutedLLM(TOTAL, answer="September revenue was 810.")
    r = client.post("/ask", json={"message": "revenue in September 2026"})
    assert r.status_code == 200
    [event] = [e for e in audit_events if e["event"] == "ask"]
    assert event["username"] == "test-analyst" and event["role"] == "analyst"
    assert event["detail"]["row_count"] == 1
    assert "SUM(amount)" in event["detail"]["sql"]
    assert "rows" not in event["detail"] and "answer" not in event["detail"]


@pytest.mark.integration
def test_rejected_sql_is_audited(audit_events):
    app.dependency_overrides[get_llm] = lambda: RoutedLLM("DROP TABLE orders")
    assert client.post("/ask", json={"message": "x"}).status_code == 422
    assert [e["event"] for e in audit_events] == ["sql_rejected"]


@pytest.mark.integration
def test_audit_table_is_append_only_for_the_app_login():
    marker = f"test-{uuid.uuid4().hex[:8]}"
    REAL_WRITE({"request_id": marker, "username": None, "role": None,
                "event": "test", "status_code": None, "detail": {}})
    with psycopg.connect(os.environ["TEST_ADMIN_APP_URL"]) as conn:
        row = conn.execute("SELECT count(*) FROM audit.events WHERE request_id = %s",
                           (marker,)).fetchone()
    assert row[0] == 1
    with psycopg.connect(os.environ["APP_DATABASE_URL"]) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("DELETE FROM audit.events WHERE request_id = %s", (marker,))
