"""GR-WF-02: one deadline for the whole question; no new step starts once it has passed."""
import time
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import limits, policy
from app.bi.service import DeadlineExceeded, answer_question
from app.llm import get_llm
from app.main import app
from routed_llm import RoutedLLM

TODAY = date(2026, 10, 24)


class Slow(RoutedLLM):
    def __init__(self, *a, delay=0.6, **kw):
        super().__init__(*a, **kw)
        self.delay = delay

    def generate(self, prompt):
        time.sleep(self.delay)
        return super().generate(prompt)


def test_the_deadline_comes_from_the_policy(monkeypatch):
    assert policy.get().sql["deadline_seconds"] == 300 and limits.request_deadline_seconds() == 300
    monkeypatch.setenv("REQUEST_DEADLINE_SECONDS", "45")
    assert limits.request_deadline_seconds() == 45
    monkeypatch.setenv("REQUEST_DEADLINE_SECONDS", "9999")
    assert limits.request_deadline_seconds() == 300


@pytest.mark.integration
def test_a_slow_workflow_stops_before_its_next_step(monkeypatch):
    monkeypatch.setenv("REQUEST_DEADLINE_SECONDS", "1")
    llm = Slow("SELECT SUM(amount) AS revenue FROM orders WHERE status = 'completed'", delay=1.1)
    with pytest.raises(DeadlineExceeded):
        answer_question("What was revenue?", lambda p: llm.generate(p).text, TODAY)
    assert len(llm.prompts) == 1                       # the explain call never started


@pytest.mark.integration
def test_a_question_within_the_deadline_is_answered():
    llm = RoutedLLM("SELECT SUM(amount) AS revenue FROM orders WHERE status = 'completed'", answer="Revenue was 1380.")
    assert answer_question("What was revenue?", lambda p: llm.generate(p).text, TODAY)["answer"] == "Revenue was 1380."


@pytest.mark.integration
def test_ask_reports_a_missed_deadline_plainly(monkeypatch, audit_events):
    monkeypatch.setenv("REQUEST_DEADLINE_SECONDS", "1")
    app.dependency_overrides[get_llm] = lambda: Slow("SELECT SUM(amount) AS revenue FROM orders", delay=1.1)
    try:
        r = TestClient(app).post("/ask", json={"message": "What was revenue?"})
    finally:
        app.dependency_overrides.pop(get_llm, None)
    assert r.status_code == 504
    assert r.json() == {"detail": "That question took too long to answer. Please try a simpler question."}
    assert audit_events[-1]["event"] == "deadline_exceeded" and audit_events[-1]["detail"]["guardrail"] == "GR-WF-02"
