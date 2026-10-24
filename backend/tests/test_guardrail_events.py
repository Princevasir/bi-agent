"""GR-OBS-01: every guardrail decision is recorded with its guardrail ID, a category, the request ID and latency."""
import pytest
from fastapi.testclient import TestClient

from app import main
from app.appdb import User
from app.auth import current_user
from app.bi.sql_guard import SQLRejected, validate_sql
from app.db import ResultTooLargeError
from app.agents import sql as sql_agent
from app.llm import get_llm
from app.llm.budget import TokenBudget
from app.main import app
from app.throttle import LoginThrottle
from routed_llm import RoutedLLM

client = TestClient(app)
TABLES = ("orders", "regions")


@pytest.mark.parametrize("sql,guardrail,category", [
    ("DROP TABLE orders", "GR-SQL-01", "statement"),
    ("SELECT 1; SELECT 2", "GR-SQL-01", "statement"),
    ("SELECT pg_sleep(10)", "GR-SQL-01", "function"),
    ("SELECT * FROM internal_notes", "GR-SQL-01", "table"),
    ("SELECT * FROM public.orders", "GR-SQL-01", "table"),
    ("SELECT * FROM orders FOR UPDATE", "GR-SQL-01", "statement"),
    ("SELECT * FROM generate_series(1, 10)", "GR-SQL-01", "function"),
    ("SELECT count(*) FROM orders, regions", "GR-SQL-02", "structure"),
])
def test_each_validator_rejection_names_its_guardrail(sql, guardrail, category):
    with pytest.raises(SQLRejected) as e:
        validate_sql(sql, TABLES)
    assert (e.value.guardrail, e.value.category) == (guardrail, category)


def test_personal_data_and_metric_rejections_name_theirs():
    with pytest.raises(SQLRejected) as e:
        validate_sql("SELECT email FROM customers", ("customers",), frozenset({("customers", "email")}))
    assert (e.value.guardrail, e.value.category) == ("GR-SQL-05", "personal_data")


def event_after(response_fn, audit_events):
    response_fn()
    return audit_events[-1]


def assert_decision(event, guardrail):
    d = event["detail"]
    assert d["guardrail"] == guardrail and d.get("category")
    assert event["request_id"] and isinstance(d["latency_ms"], (int, float)) and d["latency_ms"] >= 0


@pytest.fixture
def model():
    def use(sql):
        app.dependency_overrides[get_llm] = lambda: RoutedLLM(sql)
    yield use
    app.dependency_overrides.pop(get_llm, None)


def test_a_validator_rejection_is_recorded_with_its_guardrail(model, audit_events):
    model("DROP TABLE orders")
    client.post("/ask", json={"message": "anything"})
    assert_decision(audit_events[-1], "GR-SQL-01")
    assert audit_events[-1]["detail"]["category"] == "statement"


@pytest.mark.integration
def test_a_step_limit_is_recorded(model, audit_events, monkeypatch):
    from app import limits
    monkeypatch.setattr(limits, "sql_repair_attempts", lambda: 1000)
    model("SELECT ((( FROM orders")
    client.post("/ask", json={"message": "anything"})
    assert_decision(audit_events[-1], "step-limit")


def test_an_access_denial_is_recorded(audit_events):
    app.dependency_overrides[current_user] = lambda: User(username="x", role="intern")
    client.post("/ask", json={"message": "anything"})
    assert_decision(audit_events[-1], "role-access")


def test_a_login_lockout_is_recorded(monkeypatch, audit_events):
    monkeypatch.setattr(main, "throttle", LoginThrottle(max_failures=1))
    monkeypatch.setattr(main, "get_user", lambda name: None)
    client.post("/auth/login", json={"username": "mallory", "password": "wrong-password"})
    client.post("/auth/login", json={"username": "mallory", "password": "wrong-password"})
    assert_decision(audit_events[-1], "login-throttle")


def test_a_used_up_budget_is_recorded(model, monkeypatch, audit_events):
    monkeypatch.setattr(main, "budget", TokenBudget(1))
    model("SELECT 1")
    client.post("/chat", json={"message": "hi"})
    client.post("/chat", json={"message": "hi"})
    assert_decision(audit_events[-1], "token-budget")


def test_an_oversized_result_is_recorded(model, monkeypatch, audit_events):
    def too_big(sql, **kw):
        raise ResultTooLargeError("A single row is over the byte limit.")
    monkeypatch.setattr(sql_agent, "run_readonly", too_big)
    model("SELECT name FROM regions")
    client.post("/ask", json={"message": "regions"})
    assert_decision(audit_events[-1], "GR-SQL-04")


def test_ordinary_events_carry_latency_too(audit_events):
    client.post("/exports", json={"question": "q", "columns": ["a"], "row_count": 1})
    assert audit_events[-1]["detail"]["latency_ms"] >= 0
