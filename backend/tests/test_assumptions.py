"""GR-ACC-03: the assumptions behind an answer (dates, filters) are read from the SQL and shown."""
from datetime import date

import pytest

from app.bi.assumptions import assumptions
from app.bi.service import answer_question
from routed_llm import RoutedLLM

TODAY = date(2026, 10, 24)


@pytest.mark.parametrize("sql,expected", [
    ("SELECT SUM(amount) FROM orders WHERE status = 'completed' AND order_date >= '2026-09-01' "
     "AND order_date < '2026-10-01'",
     ["Dates: 1 Sep 2026 to 30 Sep 2026 (order_date)", "status is completed"]),
    ("SELECT SUM(amount) FROM orders o WHERE o.status = 'completed' AND o.order_date BETWEEN '2026-08-01' AND '2026-08-31'",
     ["Dates: 1 Aug 2026 to 31 Aug 2026 (o.order_date)", "o.status is completed"]),
    ("SELECT SUM(oi.line_total) FROM orders o JOIN order_items oi ON oi.order_id = o.order_id "
     "WHERE o.status = 'completed' AND o.ordered_at >= '2025-02-01' AND o.ordered_at < '2026-02-01'",
     ["Dates: 1 Feb 2025 to 31 Jan 2026 (o.ordered_at)", "o.status is completed"]),
    ("SELECT COUNT(*) FROM orders WHERE channel IN ('web', 'app') AND EXTRACT(YEAR FROM order_date) = 2025",
     ["Year 2025 (order_date)", "channel is web or app"]),
    ("SELECT COUNT(*) FROM orders WHERE order_date >= '2026-01-01'", ["Dates: from 1 Jan 2026 (order_date)"]),
    ("SELECT COUNT(*) FROM orders WHERE order_date < '2026-01-01 00:00:00'", ["Dates: before 1 Jan 2026 (order_date)"]),
    ("SELECT name FROM regions", []),
    ("SELECT COUNT(*) FROM orders WHERE status <> 'cancelled'", ["status is not cancelled"]),
])
def test_assumptions_are_read_from_the_sql(sql, expected):
    assert assumptions(sql) == expected


def test_sql_that_cannot_be_read_gives_no_assumptions():
    assert assumptions("") == [] and assumptions("NOT SQL AT ALL (((") == []


@pytest.mark.integration
def test_every_data_answer_carries_its_assumptions():
    llm = RoutedLLM("SELECT SUM(amount) AS revenue FROM orders WHERE status = 'completed' "
                    "AND order_date >= '2026-09-01' AND order_date < '2026-10-01'", answer="Revenue was 810.")
    out = answer_question("What was revenue last month?", lambda p: llm.generate(p).text, TODAY)
    assert out["assumptions"] == ["Dates: 1 Sep 2026 to 30 Sep 2026 (order_date)", "status is completed"]


def test_answers_without_sql_have_none():
    out = answer_question("What tables can I see?", lambda p: "", TODAY)
    assert out["assumptions"] == []
