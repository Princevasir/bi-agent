"""Demo gap D1: every run of the workflow stops within a fixed number of steps (max_steps in the policy)."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import limits, policy
from app.bi import service
from app.bi.conversation import Turn
from app.bi.service import StepLimitError, answer_question
from app.llm import get_llm
from app.llm.base import LLMResult
from app.main import app

TODAY = date(2026, 10, 24)
GOOD = "SELECT SUM(amount) AS revenue FROM orders WHERE status = 'completed'"
BAD = "SELECT ((( FROM orders"              # repairable: it cannot be parsed
HISTORY = [Turn(question="What was revenue in September?", sql=GOOD, columns=["revenue"], rows=[[810]],
                answer="810")]


class Scripted:
    """Answers SQL prompts from a list (the last one repeats), rewrites and explanations with fixed text."""

    def __init__(self, sql_answers, rewrite="What was revenue in total?", answer="Revenue was 1380."):
        self.sql_answers, self.rewrite, self.answer, self.calls = list(sql_answers), rewrite, answer, 0

    def generate(self, prompt):
        self.calls += 1
        if prompt.startswith("Rewrite"):
            text = self.rewrite
        elif prompt.startswith("You write PostgreSQL"):
            text = self.sql_answers.pop(0) if len(self.sql_answers) > 1 else self.sql_answers[0]
        else:
            text = self.answer
        return LLMResult(text=text, input_tokens=1, output_tokens=1)


def run(llm, history=None, question="What was revenue in total?"):
    return answer_question(question, lambda p: llm.generate(p).text, TODAY, history)


# ---- the limit ------------------------------------------------------------------------------------------

def test_the_step_limit_comes_from_the_policy():
    assert policy.get().sql["max_steps"] == 15
    assert limits.workflow_max_steps() == 15


def test_the_environment_may_only_lower_the_step_limit(monkeypatch):
    monkeypatch.setenv("WORKFLOW_MAX_STEPS", "8")
    assert limits.workflow_max_steps() == 8
    monkeypatch.setenv("WORKFLOW_MAX_STEPS", "500")
    assert limits.workflow_max_steps() == 15


# ---- the workflow ---------------------------------------------------------------------------------------

@pytest.mark.integration
def test_the_longest_legitimate_path_fits_within_the_limit():
    # route, rewrite, find knowledge, decline, second opinion, rejected SQL, repair, execute, explain, ground, draw
    llm = Scripted(["NO_QUERY", BAD, GOOD])
    out = run(llm, HISTORY)
    assert out["rows"] == [[1380]] and out["decline_retries"] == 1 and out["sql_repairs"] == 1
    assert len(out["trace"]) == 13 < limits.workflow_max_steps()


@pytest.mark.integration
def test_a_runaway_loop_is_stopped(monkeypatch):
    monkeypatch.setattr(limits, "sql_repair_attempts", lambda: 1000)   # a broken repair limit
    llm = Scripted([BAD])
    with pytest.raises(StepLimitError):
        run(llm)
    assert llm.calls <= limits.workflow_max_steps()


@pytest.mark.integration
def test_a_lower_limit_stops_earlier(monkeypatch):
    monkeypatch.setenv("WORKFLOW_MAX_STEPS", "3")
    with pytest.raises(StepLimitError):
        run(Scripted([GOOD]))


def test_graph_runs_pass_the_limit_to_langgraph(monkeypatch):
    seen = {}

    class Graph:
        def invoke(self, state, config=None):
            seen.update(config or {})
            return {"route": "data", "trace": [], "sql": "", "columns": [], "rows": [], "truncated": False, "answer": "x",
                    "answer_source": "fallback"}

    monkeypatch.setattr(service, "build_graph", lambda *a, **kw: Graph())
    run(Scripted([GOOD]))
    assert seen["recursion_limit"] == 15


# ---- the API --------------------------------------------------------------------------------------------

@pytest.mark.integration
def test_ask_explains_a_stopped_run_and_audits_it(monkeypatch, audit_events):
    monkeypatch.setattr(limits, "sql_repair_attempts", lambda: 1000)
    app.dependency_overrides[get_llm] = lambda: Scripted([BAD])
    try:
        r = TestClient(app).post("/ask", json={"message": "What was revenue in total?"})
    finally:
        app.dependency_overrides.pop(get_llm, None)
    assert r.status_code == 422
    assert r.json() == {"detail": "I could not answer that within the step limit. Try asking more simply."}
    assert [e["event"] for e in audit_events][-1] == "step_limit"
