import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.access import AccessError, tables_for
from app.appdb import User
from app.auth import current_user
from app.bi.schema import get_schema, metrics_text
from app.bi.sql_guard import SQLRejected, validate_sql
from app.bi.text_to_sql import build_prompt
from app.db import DBError, TrustedSQL, run_readonly
from app.llm import get_llm
from app.main import app
from routed_llm import RoutedLLM

client = TestClient(app)

TOTAL = (
    "SELECT SUM(amount) AS revenue FROM orders WHERE status = 'completed' "
    "AND order_date >= '2026-09-01' AND order_date < '2026-10-01'"
)


def test_limited_role_sees_only_regions():
    assert tables_for("limited") == ("regions",)


def test_unknown_role_is_an_error():
    with pytest.raises(AccessError):
        tables_for("admin")


def test_validator_uses_the_roles_table_list():
    with pytest.raises(SQLRejected):
        validate_sql("SELECT * FROM orders", ("regions",))
    assert validate_sql("SELECT * FROM regions", ("regions",))


@pytest.mark.integration
def test_database_refuses_orders_for_the_limited_login():
    with pytest.raises(DBError):
        run_readonly(TrustedSQL("SELECT * FROM orders"), role="limited")
    assert run_readonly(TrustedSQL("SELECT name FROM regions"), role="limited")["rows"]


@pytest.mark.integration
def test_limited_role_schema_prompt_and_metrics():
    assert set(get_schema("limited")) == {"regions"}
    assert metrics_text("limited") == ""
    assert "orders(" not in build_prompt("q", date(2026, 10, 19), "limited")


@pytest.mark.integration
def test_unknown_role_is_refused_before_connecting():
    with pytest.raises(AccessError):
        run_readonly(TrustedSQL("SELECT 1"), role="admin")


@pytest.fixture(autouse=True)
def clear_llm_override():
    yield
    app.dependency_overrides.pop(get_llm, None)


def as_role(role):
    app.dependency_overrides[current_user] = lambda: User(username=f"t-{role}", role=role)


@pytest.mark.integration
def test_limited_user_cannot_query_orders_through_ask():
    app.dependency_overrides[get_llm] = lambda: RoutedLLM(TOTAL)
    as_role("limited")
    r = client.post("/ask", json={"message": "revenue in September 2026"})
    assert r.status_code == 422


@pytest.mark.integration
def test_analyst_gets_the_golden_number_through_ask():
    app.dependency_overrides[get_llm] = lambda: RoutedLLM(TOTAL, answer="September revenue was 810.")
    as_role("analyst")
    r = client.post("/ask", json={"message": "revenue in September 2026"})
    assert r.status_code == 200
    assert r.json()["rows"] == [[810.0]]