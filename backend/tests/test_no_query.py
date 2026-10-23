from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.bi import service
from app.agents import sql as sql_agent
from app.bi.text_to_sql import NO_QUERY, build_prompt, is_no_query
from app.llm import get_llm
from app.main import app
from routed_llm import RoutedLLM

client = TestClient(app)
TODAY = date(2026, 10, 19)


@pytest.fixture(autouse=True)
def clear_llm_override():
    yield
    app.dependency_overrides.pop(get_llm, None)


@pytest.mark.parametrize("text", ["NO_QUERY", " no_query \n", "NO_QUERY;", "NO_QUERY."])
def test_a_decline_is_recognised(text):
    assert is_no_query(text)


@pytest.mark.parametrize("text", ["SELECT 'NO_QUERY'", "", "NO_QUERY please", "SELECT 1"])
def test_other_text_is_not_a_decline(text):
    assert not is_no_query(text)


@pytest.mark.integration
def test_prompt_tells_the_model_how_to_decline():
    prompt = build_prompt("hello", TODAY)
    assert prompt.startswith("You write PostgreSQL")  # RoutedLLM routes on this opening
    assert NO_QUERY in prompt


def test_a_declined_question_never_validates_or_runs_a_query(monkeypatch):
    monkeypatch.setattr(sql_agent, "generate_sql", lambda q, g, t, **kw: "NO_QUERY")

    def fail(*args, **kwargs):
        raise AssertionError("must not run")

    monkeypatch.setattr(sql_agent, "validate_sql", fail)
    monkeypatch.setattr(sql_agent, "run_readonly", fail)
    out = service.answer_question("hello", fail, TODAY)
    assert out["sql"] == "" and out["rows"] == [] and out["columns"] == []
    assert out["answer"] == service.NO_QUERY_ANSWER
    assert out["answer_source"] == "fallback"
    assert out["chart"] is None


@pytest.mark.integration
def test_ask_returns_the_decline_message_and_audits_it(audit_events):
    app.dependency_overrides[get_llm] = lambda: RoutedLLM("NO_QUERY")
    r = client.post("/ask", json={"message": "hello"})
    assert r.status_code == 200
    body = r.json()
    assert body["sql"] == "" and body["rows"] == []
    assert body["answer"] == service.NO_QUERY_ANSWER
    [event] = [e for e in audit_events if e["event"] == "ask"]
    assert event["detail"]["sql"] == "" and event["detail"]["row_count"] == 0


@pytest.mark.integration
def test_ask_sql_returns_no_sql_when_declined():
    app.dependency_overrides[get_llm] = lambda: RoutedLLM("NO_QUERY")
    r = client.post("/ask/sql", json={"message": "hello"})
    assert r.status_code == 200
    assert r.json()["sql"] == ""
