"""GR-SQL-06: SQL reaches the database only through the validator or as fixed code-authored text,
and every non-public route requires sign-in."""
from datetime import date
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app import db
from app.bi import service
from app.bi.sql_guard import ValidatedSQL, validate_sql
from app.db import TrustedSQL, UnvalidatedSQLError, run_readonly
from app.llm import get_llm
from app.main import app, signed_in
from routed_llm import RoutedLLM

client = TestClient(app)
APP_DIR = Path(__file__).resolve().parents[1] / "app"
PUBLIC_PATHS = {"/health", "/hello", "/ready", "/auth/login",
                "/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"}


@pytest.fixture(autouse=True)
def clear_llm_override():
    yield
    app.dependency_overrides.pop(get_llm, None)


@pytest.fixture
def no_connect(monkeypatch):
    def fail(*a, **kw):
        raise AssertionError("must not connect")
    monkeypatch.setattr(db.psycopg, "connect", fail)


# ---- the database function refuses unmarked SQL ---------------------------

@pytest.mark.parametrize("sql", ["SELECT 1", "SELECT * FROM internal_notes", ""])
def test_plain_strings_are_refused_before_connecting(no_connect, sql):
    with pytest.raises(UnvalidatedSQLError):
        run_readonly(sql)


def test_validate_sql_returns_validated_sql():
    out = validate_sql("SELECT name FROM regions;")
    assert isinstance(out, ValidatedSQL)
    assert out == "SELECT name FROM regions"


@pytest.mark.integration
def test_validated_and_trusted_sql_run():
    assert run_readonly(validate_sql("SELECT count(*) FROM regions"))["rows"] == [[3]]
    assert run_readonly(TrustedSQL("SELECT 1"))["rows"] == [[1]]


def test_workflow_executes_only_validated_sql(monkeypatch):
    seen = []

    def run(sql, **kw):
        seen.append(sql)
        return {"columns": ["n"], "rows": [[3]], "truncated": False}

    monkeypatch.setattr(service, "run_readonly", run)
    llm = RoutedLLM("SELECT count(*) AS n FROM regions", answer="There are 3 regions.")
    service.answer_question("How many regions?", lambda p: llm.generate(p).text, date(2026, 10, 15))
    assert len(seen) == 1 and isinstance(seen[0], ValidatedSQL)


def test_only_known_modules_talk_to_postgres():
    users = sorted(p.relative_to(APP_DIR).as_posix() for p in APP_DIR.rglob("*.py")
                   if "import psycopg" in p.read_text())
    # db.py: the read-only BI logins; appdb.py and audit.py: the app's own users and audit tables.
    assert users == ["appdb.py", "audit.py", "db.py"]


# ---- /ask/sql validates like /ask -----------------------------------------

def test_ask_sql_rejects_a_forbidden_table(audit_events):
    app.dependency_overrides[get_llm] = lambda: RoutedLLM("SELECT note FROM internal_notes")
    r = client.post("/ask/sql", json={"message": "show the notes"})
    assert r.status_code == 422
    assert r.json() == {"detail": "The generated query was rejected."}
    assert [e["event"] for e in audit_events] == ["sql_rejected"]


def test_ask_sql_returns_the_validated_query():
    app.dependency_overrides[get_llm] = lambda: RoutedLLM("SELECT name FROM regions;")
    r = client.post("/ask/sql", json={"message": "list regions"})
    assert r.status_code == 200
    assert r.json()["sql"] == "SELECT name FROM regions"


def test_ask_sql_still_returns_empty_sql_for_a_decline():
    app.dependency_overrides[get_llm] = lambda: RoutedLLM("NO_QUERY")
    r = client.post("/ask/sql", json={"message": "hello"})
    assert r.status_code == 200 and r.json()["sql"] == ""


# ---- route inventory -------------------------------------------------------

def _requires(dependant, dependency):
    return any(d.call is dependency or _requires(d, dependency) for d in dependant.dependencies)


def unprotected_routes(application):
    return sorted(r.path for r in application.routes
                  if isinstance(r, APIRoute) and r.path not in PUBLIC_PATHS
                  and not _requires(r.dependant, signed_in))


def test_every_non_public_route_requires_sign_in():
    assert unprotected_routes(app) == []


def test_the_inventory_notices_an_unprotected_route():
    probe = FastAPI()

    @probe.get("/open")
    def open_route():
        return {}

    @probe.get("/closed", dependencies=[Depends(signed_in)])
    def closed_route():
        return {}

    assert unprotected_routes(probe) == ["/open"]
