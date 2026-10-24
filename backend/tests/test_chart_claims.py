"""The answer never names a chart that is not the one shown (owner's report, 24 October 2026).

"Show me a pie chart of revenue for 2025 on a monthly basis" gave 12 months; a pie allows 2 to 8 parts,
so a line chart was drawn with a note, but the model's sentence began "A pie chart showing revenue ...".
"""
from datetime import date

import pytest

from app.agents import sql as sql_agent
from app.agents.chart import names_another_chart
from app.bi.service import answer_question
from routed_llm import RoutedLLM

TODAY = date(2026, 10, 24)
MONTHS = {"columns": ["month", "revenue"], "truncated": False,
          "rows": [[f"2025-{m:02d}-01", 1000.0 + m] for m in range(1, 13)]}
REGIONS = {"columns": ["region", "revenue"], "truncated": False,
           "rows": [["North", 270.0], ["South", 300.0], ["West", 240.0]]}


@pytest.mark.parametrize("answer,shown,expected", [
    ("A pie chart showing revenue for 2025 would display January - 1001.0.", "line", True),
    ("The bar graph shows South first.", "pie", True),
    ("The donut chart shows South first.", "donut", False),
    ("The line chart shows revenue rising to 1012.0 in December.", "line", False),
    ("Revenue rose every month, ending at 1012.0.", "line", False),
    ("Sales of the Ridgeline product line grew.", "bar", False),          # "line" alone is not a chart
    ("A scatter plot would show the spread.", "bar", True),
])
def test_chart_names_in_answers(answer, shown, expected):
    assert names_another_chart(answer, shown) is expected


def ask(monkeypatch, result, question, answer):
    monkeypatch.setattr(sql_agent, "run_readonly", lambda sql, **kw: result)
    llm = RoutedLLM("SELECT * FROM orders", answer=answer)
    return answer_question(question, lambda p: llm.generate(p).text, TODAY)


@pytest.mark.integration
def test_an_answer_naming_a_chart_that_did_not_fit_is_replaced(monkeypatch):
    out = ask(monkeypatch, MONTHS, "Show me a pie chart of revenue for 2025 on a monthly basis",
              "A pie chart showing revenue for the year 2025 on a monthly basis would display January - 1001.0.")
    assert out["chart"]["type"] == "line" and out["chart_note"]
    assert "pie chart" not in out["answer"].lower() and out["answer_source"] == "fallback"
    assert "1001.0" in out["answer"]                      # the plain answer still gives the numbers


@pytest.mark.integration
def test_an_answer_naming_the_chart_that_is_shown_is_kept(monkeypatch):
    out = ask(monkeypatch, REGIONS, "Show revenue by region as a pie chart", "The pie chart shows South led with 300.0.")
    assert out["chart"]["type"] == "pie" and out["answer"] == "The pie chart shows South led with 300.0."
