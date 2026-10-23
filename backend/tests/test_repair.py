"""GR-WF-01: one bounded repair when the model's SQL fails for a fixable reason; never for a rule."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import limits
from app.bi import service
from app.bi.sql_guard import SQLRejected
from app.db import DBAccessError, DBQueryError, DBTimeoutError
from app.llm import get_llm
from app.main import app
from routed_llm import RoutedLLM

TODAY = date(2026, 10, 15)
GOOD = "SELECT name AS region, count(*) AS n FROM regions GROUP BY name"
ROWS = {"columns": ["region", "n"], "rows": [["North", 1], ["South", 1]], "truncated": False}
client = TestClient(app)


class Model:
    """Answers SQL prompts from a list, in order, and records them."""

    def __init__(self, *sqls):
        self.sqls, self.sql_prompts = list(sqls), []

    def __call__(self, prompt):
        if prompt.startswith("You write PostgreSQL"):
            self.sql_prompts.append(prompt)
            return self.sqls.pop(0)
        return "There are two regions."


@pytest.fixture(autouse=True)
def clear_llm_override():
    yield
    app.dependency_overrides.pop(get_llm, None)


def runs(monkeypatch, *outcomes):
    """run_readonly returns or raises each outcome in turn."""
    calls = []

    def run(sql, **kw):
        calls.append(sql)
        outcome = outcomes[len(calls) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(service, "run_readonly", run)
    return calls


# ---- repaired once -------------------------------------------------------------------------------------

def test_a_query_the_database_rejects_is_repaired_once(monkeypatch):
    calls = runs(monkeypatch, DBQueryError("The query failed.", detail='column "quarter" does not exist'), ROWS)
    model = Model("SELECT quarter FROM regions", GOOD)
    out = service.answer_question("regions", model, TODAY)
    assert len(model.sql_prompts) == 2 and len(calls) == 2
    repair = model.sql_prompts[1]
    assert 'column "quarter" does not exist' in repair and "SELECT quarter FROM regions" in repair
    assert out["rows"] == ROWS["rows"] and out["sql_repairs"] == 1


@pytest.mark.parametrize("bad", [
    "SELECT made_up_fn(name) FROM regions",            # function not on the allowlist
    "SELECT count(*) FROM orders, regions",             # join without a condition
    "SELEC name FROM regions",                          # does not parse
])
def test_a_fixable_rejection_is_repaired_once(monkeypatch, bad):
    runs(monkeypatch, ROWS)
    model = Model(bad, GOOD)
    out = service.answer_question("regions", model, TODAY)
    assert len(model.sql_prompts) == 2 and out["sql_repairs"] == 1
    assert "previous query" in model.sql_prompts[1].lower()


def test_no_repair_needed_means_one_attempt(monkeypatch):
    runs(monkeypatch, ROWS)
    model = Model(GOOD)
    assert service.answer_question("regions", model, TODAY)["sql_repairs"] == 0
    assert len(model.sql_prompts) == 1


# ---- never more than once, never for a rule -----------------------------------------------------------

def test_a_second_failure_is_final(monkeypatch):
    runs(monkeypatch, DBQueryError("x", detail="a"), DBQueryError("x", detail="b"))
    model = Model("SELECT bad1 FROM regions", "SELECT bad2 FROM regions")
    with pytest.raises(DBQueryError):
        service.answer_question("regions", model, TODAY)
    assert len(model.sql_prompts) == 2


@pytest.mark.parametrize("bad", [
    "SELECT note FROM internal_notes",                  # table not permitted
    "DELETE FROM orders",                               # not read-only
    "SELECT * FROM pg_catalog.pg_user",                 # schema-qualified
    "SELECT * FROM orders FOR UPDATE",                  # locking
])
def test_rule_violations_are_never_retried(monkeypatch, bad):
    runs(monkeypatch, ROWS)
    model = Model(bad, GOOD)
    with pytest.raises(SQLRejected):
        service.answer_question("regions", model, TODAY)
    assert len(model.sql_prompts) == 1


def test_personal_data_is_never_retried(monkeypatch):
    runs(monkeypatch, ROWS)
    monkeypatch.setattr(service, "tables_for", lambda role: ("customers",))
    monkeypatch.setattr(service, "denied_columns", lambda role: frozenset({("customers", "email")}))
    model = Model("SELECT email FROM customers", "SELECT customer_id FROM customers")
    with pytest.raises(SQLRejected):
        service.answer_question("emails", model, TODAY)
    assert len(model.sql_prompts) == 1


@pytest.mark.parametrize("error", [DBAccessError("denied"), DBTimeoutError("slow")])
def test_access_errors_and_timeouts_are_never_retried(monkeypatch, error):
    runs(monkeypatch, error, ROWS)
    model = Model(GOOD, GOOD)
    with pytest.raises(type(error)):
        service.answer_question("regions", model, TODAY)
    assert len(model.sql_prompts) == 1


def test_repairs_can_be_switched_off_but_not_raised(monkeypatch):
    monkeypatch.setenv("SQL_REPAIR_ATTEMPTS", "0")
    assert limits.sql_repair_attempts() == 0
    runs(monkeypatch, DBQueryError("x", detail="a"), ROWS)
    model = Model("SELECT bad FROM regions", GOOD)
    with pytest.raises(DBQueryError):
        service.answer_question("regions", model, TODAY)
    assert len(model.sql_prompts) == 1
    monkeypatch.setenv("SQL_REPAIR_ATTEMPTS", "5")
    assert limits.sql_repair_attempts() == 1                   # the policy is the ceiling


# ---- reported ---------------------------------------------------------------------------------------------

def test_ask_reports_and_audits_the_repair(monkeypatch, audit_events):
    runs(monkeypatch, DBQueryError("x", detail='column "quarter" does not exist'), ROWS)
    llm = RoutedLLM("SELECT quarter FROM regions")
    sqls = iter(["SELECT quarter FROM regions", GOOD])
    original = llm.generate

    def generate(prompt):
        result = original(prompt)
        if prompt.startswith("You write PostgreSQL"):
            result = result.__class__(text=next(sqls), input_tokens=1, output_tokens=1)
        return result

    llm.generate = generate
    app.dependency_overrides[get_llm] = lambda: llm
    r = client.post("/ask", json={"message": "regions"})
    assert r.status_code == 200 and r.json()["sql_repairs"] == 1
    assert audit_events[-1]["event"] == "ask" and audit_events[-1]["detail"]["sql_repairs"] == 1
