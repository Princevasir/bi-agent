from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.bi import service
from app.agents import sql as sql_agent
from app.bi.grounding import fallback_answer, is_grounded
from app.llm import get_llm
from app.llm.base import LLMResult
from app.main import app

from app.bi.sql_guard import SQLRejected
from app.bi.conversation import Turn

client = TestClient(app)

QUESTION = "What was revenue by region in September 2026?"
SQL = ("SELECT r.name, SUM(o.amount) FROM orders o "
       "JOIN regions r ON o.region_id = r.id GROUP BY r.name")
RESULT = {
    "columns": ["region", "revenue"],
    "rows": [["North", 270.0], ["South", 300.0], ["West", 240.0]],
    "truncated": False,
}


@pytest.fixture
def patched(monkeypatch):
    monkeypatch.setattr(sql_agent, "generate_sql", lambda q, g, t, **kw: SQL)
    monkeypatch.setattr(sql_agent, "run_readonly", lambda sql, **kw: RESULT)


def ask(generate):
    return service.answer_question(QUESTION, generate, date(2026, 10, 19))


def test_grounded_answer_is_used(patched):
    text = "South had the highest revenue at 300, ahead of North at 270 and West at 240."
    out = ask(lambda prompt: text)
    assert out["answer_source"] == "llm"
    assert out["answer"] == text


def test_invented_number_falls_back(patched):
    out = ask(lambda prompt: "Revenue in the South was 999.")
    assert out["answer_source"] == "fallback"
    assert "North" in out["answer"]


def test_empty_result_never_calls_llm(patched, monkeypatch):
    monkeypatch.setattr(sql_agent, "run_readonly",
                        lambda sql, **kw: {"columns": ["revenue"], "rows": [], "truncated": False})

    def fail(prompt):
        raise AssertionError("LLM must not be called for an empty result")

    out = ask(fail)
    assert out["answer"] == "The query returned no rows."
    assert out["answer_source"] == "fallback"


def test_truncated_result_adds_note(patched, monkeypatch):
    monkeypatch.setattr(sql_agent, "run_readonly", lambda sql, **kw: {**RESULT, "truncated": True})
    out = ask(lambda prompt: "South was highest at 300.")
    assert out["truncated"] is True
    assert "truncated" in out["answer"].lower()


@pytest.mark.parametrize("answer, value", [
    ("Total was 1,380.00.", 1380),
    ("Total was 1380", 1380.0),
])
def test_number_formats_match(answer, value):
    assert is_grounded(answer, "total?", [[value]])


def test_question_numbers_are_allowed():
    assert is_grounded("In 2026 revenue was 300.", QUESTION, [[300.0]])


def test_derived_number_is_rejected():
    assert not is_grounded("Revenue is up 42%.", QUESTION, [[300.0]])


def test_fallback_answer_for_empty_result():
    assert fallback_answer(["a"], []) == "The query returned no rows."


def test_single_null_row_is_treated_as_no_data(patched, monkeypatch):
    monkeypatch.setattr(sql_agent, "run_readonly", lambda sql, **kw: {
        "columns": ["revenue", "order_count"], "rows": [[None, 0]], "truncated": False})

    def fail(prompt):
        raise AssertionError("LLM must not be called when the result has no data")

    out = ask(fail)
    assert out["answer"] == "No matching data was found."
    assert out["answer_source"] == "fallback"


def test_null_in_a_multi_row_result_is_still_explained(patched, monkeypatch):
    monkeypatch.setattr(sql_agent, "run_readonly", lambda sql, **kw: {
        "columns": ["region", "revenue"], "rows": [["North", None], ["South", 5.0]], "truncated": False})
    out = ask(lambda prompt: "South was 5.")
    assert out["answer_source"] == "llm"


def test_rejected_sql_propagates_and_never_executes(monkeypatch):
    monkeypatch.setattr(sql_agent, "generate_sql", lambda q, g, t, **kw: "DROP TABLE orders")

    def fail(sql, **kw):
        raise AssertionError("must not execute rejected SQL")

    monkeypatch.setattr(sql_agent, "run_readonly", fail)
    with pytest.raises(SQLRejected):
        ask(lambda prompt: "")


def test_blank_rewrite_falls_back_to_original_question(monkeypatch):
    seen = []
    monkeypatch.setattr(sql_agent, "generate_sql", lambda q, g, t, **kw: seen.append(q) or SQL)
    monkeypatch.setattr(sql_agent, "run_readonly", lambda sql, **kw: RESULT)
    history = [Turn("first", "SELECT 1", [], [], "a")]
    out = service.answer_question("What about August?", lambda p: "", date(2026, 10, 19), history)
    assert seen == ["What about August?"]
    assert out["interpreted_as"] == "What about August?"


class SequenceLLM:
    def __init__(self, replies):
        self.replies = list(replies)

    def generate(self, prompt):
        return LLMResult(text=self.replies.pop(0), input_tokens=1, output_tokens=1)


SEPTEMBER_SQL = (
    "SELECT SUM(amount) AS revenue FROM orders WHERE status = 'completed' "
    "AND order_date >= '2026-09-01' AND order_date < '2026-10-01'"
)


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.mark.integration
def test_endpoint_returns_grounded_answer():
    llm = SequenceLLM([SEPTEMBER_SQL, "September revenue was 810."])
    app.dependency_overrides[get_llm] = lambda: llm
    r = client.post("/ask", json={"message": "What was revenue in September 2026?"})
    assert r.status_code == 200
    body = r.json()
    assert body["rows"] == [[810.0]]
    assert body["answer"] == "September revenue was 810."
    assert body["answer_source"] == "llm"


@pytest.mark.integration
def test_endpoint_falls_back_on_invented_number():
    llm = SequenceLLM([SEPTEMBER_SQL, "September revenue was 1,000."])
    app.dependency_overrides[get_llm] = lambda: llm
    r = client.post("/ask", json={"message": "What was revenue in September 2026?"})
    assert r.status_code == 200
    assert r.json()["answer_source"] == "fallback"
    assert "810" in r.json()["answer"]