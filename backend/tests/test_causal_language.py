"""GR-ACC-04: an answer from data never claims a cause for a "why" question."""
import logging
from datetime import date

import pytest

from app.agents.analyst import asks_why, claims_a_cause
from app.bi.service import answer_question
from routed_llm import RoutedLLM

TODAY = date(2026, 10, 24)
SQL = "SELECT SUM(amount) AS revenue FROM orders WHERE status = 'completed'"


@pytest.mark.parametrize("text", ["Why did revenue drop in August?", "why is South ahead?",
                                  "What caused the dip in September?", "What is the reason for lower sales?"])
def test_why_questions_are_recognised(text):
    assert asks_why(text)


@pytest.mark.parametrize("text", ["What was revenue in August?", "Show revenue by region", "Who sold the most?"])
def test_other_questions_are_not(text):
    assert not asks_why(text)


@pytest.mark.parametrize("answer", ["Revenue fell because fewer orders were placed.", "It dropped due to the sale ending.",
                                    "The dip was caused by stock-outs.", "Growth was driven by the South.",
                                    "This led to lower revenue.", "As a result of returns, revenue fell."])
def test_causal_claims_are_recognised(answer):
    assert claims_a_cause(answer)


def test_plain_descriptions_are_not():
    assert not claims_a_cause("Revenue was 570 in August and 810 in September.")


@pytest.mark.integration
def test_a_why_answer_that_claims_a_cause_falls_back_with_a_note(caplog):
    llm = RoutedLLM(SQL, answer="Revenue was 1380 because customers loved the sale.")
    with caplog.at_level(logging.WARNING):
        out = answer_question("Why was revenue 1380?", lambda p: llm.generate(p).text, TODAY)
    assert out["answer_source"] == "fallback" and "because" not in out["answer"]
    assert out["answer"].endswith("The data shows what happened, not why.")
    [record] = [r for r in caplog.records if r.message == "answer_fallback"]
    assert record.reason == "causal_claim" and record.guardrail == "GR-ACC-04"


@pytest.mark.integration
def test_causal_words_are_fine_when_nobody_asked_why():
    llm = RoutedLLM(SQL, answer="Revenue was 1380, due to completed orders only being counted.")
    assert answer_question("What was revenue?", lambda p: llm.generate(p).text, TODAY)["answer_source"] == "llm"


@pytest.mark.integration
def test_a_why_answer_that_only_describes_is_kept():
    llm = RoutedLLM(SQL, answer="Revenue was 1380 in total.")
    assert answer_question("Why was revenue 1380?", lambda p: llm.generate(p).text, TODAY)["answer_source"] == "llm"
