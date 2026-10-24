"""GR-SQL-03: the planner's estimate is checked before a generated query runs (EXPLAIN, never ANALYZE).

Thresholds were tuned on the full retail data (24 October 2026): every validated example and demo
query plans at most cost 81,373 and 616,532 rows in any plan node, while a product-level self-join
of order_items plans 2.46M cost and 314M rows and held the database for the full 5-second timeout.
"""
import pytest
from fastapi.testclient import TestClient

from app import limits, policy
from app.db import QueryTooExpensiveError, TrustedSQL, plan_problem, run_readonly
from app.llm import get_llm
from app.main import app
from app.sqltypes import ValidatedSQL
from routed_llm import RoutedLLM

ORDERS = "SELECT status, COUNT(*) AS n FROM orders GROUP BY status"


def plan(cost, rows, *children):
    return {"Total Cost": cost, "Plan Rows": rows, "Plans": list(children)}


# ---- the decision ---------------------------------------------------------------------------------------

def test_a_cheap_plan_passes():
    assert plan_problem(plan(36_080, 1, plan(20_000, 513_734)), max_cost=1_000_000, max_rows=10_000_000) is None


def test_the_biggest_node_counts_not_the_final_row():
    # A join explosion hides under an aggregate that returns one row.
    problem = plan_problem(plan(2_461_026, 1, plan(2_400_000, 314_236_718)), max_cost=10**9, max_rows=10_000_000)
    assert "314,236,718 rows" in problem


def test_an_expensive_plan_is_reported_with_its_estimate():
    assert "cost 2,461,026" in plan_problem(plan(2_461_026, 1), max_cost=1_000_000, max_rows=10**12)


# ---- the limits -----------------------------------------------------------------------------------------

def test_the_limits_come_from_the_policy():
    assert policy.get().sql["max_plan_cost"] == 1_000_000 and policy.get().sql["max_plan_rows"] == 10_000_000
    assert limits.sql_max_plan_cost() == 1_000_000 and limits.sql_max_plan_rows() == 10_000_000


def test_the_environment_may_only_lower_them(monkeypatch):
    monkeypatch.setenv("SQL_MAX_PLAN_ROWS", "5")
    assert limits.sql_max_plan_rows() == 5
    monkeypatch.setenv("SQL_MAX_PLAN_COST", str(10**12))
    assert limits.sql_max_plan_cost() == 1_000_000


# ---- in the one execution path ----------------------------------------------------------------------------

@pytest.mark.integration
def test_a_generated_query_over_the_limit_never_runs(monkeypatch):
    monkeypatch.setenv("SQL_MAX_PLAN_ROWS", "1")
    with pytest.raises(QueryTooExpensiveError) as e:
        run_readonly(ValidatedSQL(ORDERS))
    assert e.value.estimate["rows"] >= 1 and e.value.estimate["cost"] > 0


@pytest.mark.integration
def test_generated_queries_within_the_limits_run():
    assert run_readonly(ValidatedSQL(ORDERS))["rows"]


@pytest.mark.integration
def test_code_authored_queries_are_not_cost_checked(monkeypatch):
    monkeypatch.setenv("SQL_MAX_PLAN_ROWS", "1")
    assert run_readonly(TrustedSQL(ORDERS))["rows"]


@pytest.mark.integration
def test_ask_explains_a_rejected_expensive_question(monkeypatch, audit_events):
    monkeypatch.setenv("SQL_MAX_PLAN_ROWS", "1")
    app.dependency_overrides[get_llm] = lambda: RoutedLLM(ORDERS)
    try:
        r = TestClient(app).post("/ask", json={"message": "How many orders by status?"})
    finally:
        app.dependency_overrides.pop(get_llm, None)
    assert r.status_code == 422
    assert r.json() == {"detail": "That question would scan too much data; try a shorter period or a grouping."}
    event = audit_events[-1]
    assert event["event"] == "sql_rejected" and event["detail"]["guardrail"] == "GR-SQL-03"
    assert event["detail"]["category"] == "cost" and event["detail"]["estimate"]["rows"] >= 1
