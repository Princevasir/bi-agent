"""Database errors are classified honestly: a broken query is not a broken database."""
import pytest
from fastapi.testclient import TestClient

from app.bi import service
from app.agents import sql as sql_agent
from app.db import DBAccessError, DBError, DBQueryError, TrustedSQL, run_readonly
from app.llm import get_llm
from app.main import app
from routed_llm import RoutedLLM

client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_llm_override():
    yield
    app.dependency_overrides.pop(get_llm, None)


@pytest.mark.integration
@pytest.mark.parametrize("sql", [
    "SELECT id FROM orders JOIN regions ON regions.id = orders.region_id",   # ambiguous column
    "SELECT no_such_column FROM orders",
    "SELECT * FROM orders WHERE order_date > 'not a date'",
    "SELEC 1",
])
def test_errors_in_the_query_are_query_errors(sql):
    with pytest.raises(DBQueryError):
        run_readonly(TrustedSQL(sql))


@pytest.mark.integration
def test_permission_denied_is_an_access_error():
    with pytest.raises(DBAccessError):
        run_readonly(TrustedSQL("SELECT * FROM internal_notes"))


@pytest.mark.integration
def test_both_are_still_database_errors_for_existing_handlers():
    assert issubclass(DBQueryError, DBError) and issubclass(DBAccessError, DBError)


@pytest.mark.parametrize("error,status,detail", [
    (DBQueryError("x"), 422, "The generated query could not run. Try rephrasing the question."),
    (DBAccessError("x"), 403, "You don't have access to that data."),
    (DBError("x"), 503, "The database is unavailable."),
])
def test_each_kind_gets_its_own_message(monkeypatch, audit_events, error, status, detail):
    def fail(*a, **kw):
        raise error

    monkeypatch.setattr(sql_agent, "run_readonly", fail)
    app.dependency_overrides[get_llm] = lambda: RoutedLLM("SELECT name FROM regions")
    r = client.post("/ask", json={"message": "regions"})
    assert (r.status_code, r.json()["detail"]) == (status, detail)
    assert audit_events[-1]["event"] == "db_error"
