"""F1: labels, numbers, the big-number card and friendly status messages."""
import pytest

from client import BackendError
from presentation import (DECLINE_PREFIX, format_number, is_declined, is_no_data, pretty_label, source_line,
                          single_value, status_for, STEPS, total_seconds, trace_lines)


@pytest.mark.parametrize("raw,pretty", [("revenue", "Revenue"), ("region_name", "Region name"),
                                        ("total_revenue", "Total revenue"), ("count", "Count")])
def test_pretty_label(raw, pretty):
    assert pretty_label(raw) == pretty


@pytest.mark.parametrize("value,text", [(1380, "1,380"), (810.0, "810"), (135.5, "135.50"),
                                        (1234567.891, "1,234,567.89"), (None, "—"), ("South", "South")])
def test_format_number(value, text):
    assert format_number(value) == text


def test_single_value_cards():
    assert single_value(["revenue"], [[810.0]]) == ("Revenue", "810")
    assert single_value(["region_name", "revenue"], [["South", 300]]) == ("Revenue · South", "300")
    assert single_value(["revenue"], [[810], [570]]) is None
    assert single_value(["name"], [["North"]]) is None
    assert single_value(["revenue"], [[None]]) is None


def test_declined_and_no_data_answers_are_recognised():
    declined = {"sql": "", "rows": [], "answer": DECLINE_PREFIX + " Try something like ..."}
    assert is_declined(declined) and not is_no_data(declined)
    empty = {"sql": "SELECT 1", "rows": [], "answer": "No matching data was found."}
    assert is_no_data(empty) and not is_declined(empty)
    normal = {"sql": "SELECT 1", "rows": [[1]], "answer": "There is 1."}
    assert not is_declined(normal) and not is_no_data(normal)


@pytest.mark.parametrize("status,detail,kind,icon", [
    (422, "The generated query was too broad to run safely. Try a more specific question.", "warning", "🔍"),
    (422, "The generated query was rejected.", "warning", "🛡️"),
    (422, "The result is too large to show. Try a narrower question.", "warning", "🔍"),
    (403, "Access denied.", "error", "🔒"),
    (429, "Too many sign-in attempts.", "warning", "⏳"),
    (504, "The database query timed out.", "warning", "⏱️"),
    (503, "The language model is unavailable.", "error", "⚠️"),
    (None, "Could not reach the backend.", "error", "⚠️"),
])
def test_status_for_errors(status, detail, kind, icon):
    s = status_for(BackendError(detail, status_code=status))
    assert (s["kind"], s["icon"]) == (kind, icon)
    assert s["text"] == detail


# ---- D3: sources and "How I answered" ---------------------------------------------------------------

SOURCES = [
    {"document_id": "sql-average-order-value", "title": "Average order value by month", "doc_type": "sql_example",
     "owner": "Sales Analytics", "version": 1, "score": 0.79},
    {"document_id": "metric-average-order-value", "title": "Average order value", "doc_type": "metric",
     "owner": "Sales Analytics", "version": 2, "score": 0.73},
    {"document_id": "metric-average-order-value", "title": "Average order value", "doc_type": "metric",
     "owner": "Sales Analytics", "version": 2, "score": 0.70},
]
TRACE = [
    {"agent": "Coordinator", "step": "route", "ms": 0.4},
    {"agent": "Knowledge", "step": "find_knowledge", "ms": 61.0},
    {"agent": "SQL", "step": "write_sql", "ms": 18234.5},
    {"agent": "SQL", "step": "check_sql", "ms": 3.2},
    {"agent": "SQL", "step": "execute", "ms": 412.0},
    {"agent": "Analyst", "step": "explain", "ms": 9120.0},
    {"agent": "Analyst", "step": "ground", "ms": 0.2},
    {"agent": "Chart", "step": "draw", "ms": 0.3},
]


def test_sources_are_listed_once_each_with_type_and_version():
    assert source_line(SOURCES) == ("Sources: Average order value by month (SQL example, v1) · "
                                    "Average order value (metric, v2)")


def test_no_sources_means_no_line():
    assert source_line([]) is None and source_line(None) is None


def test_each_step_is_told_in_plain_words_with_its_time():
    lines = trace_lines(TRACE)
    assert lines[0] == ("Coordinator", "Understood the question and chose the agents", "0.0 s")
    assert lines[1] == ("Knowledge", "Looked up business definitions, rules and example queries", "0.1 s")
    assert lines[2] == ("SQL", "Wrote the SQL query", "18.2 s")
    assert [a for a, _, _ in lines] == ["Coordinator", "Knowledge", "SQL", "SQL", "SQL", "Analyst", "Analyst", "Chart"]


def test_every_backend_step_has_a_plain_description():
    for step in ("route", "rewrite", "find_knowledge", "catalog_answer", "write_sql", "second_opinion", "check_sql",
                 "explain_knowledge", "check_citations",
                 "execute", "declined", "explain", "ground", "no_rows", "draw", "redraw"):
        assert step in STEPS, step                              # a written description, not the fallback
        assert trace_lines([{"agent": "X", "step": step, "ms": 1}])[0][1] == STEPS[step]


def test_an_unknown_step_or_missing_time_still_shows():
    assert trace_lines([{"agent": "SQL", "step": "something_new"}]) == [("SQL", "Something new", "")]


def test_the_total_time_is_the_sum_of_the_steps():
    assert total_seconds(TRACE) == "27.8 s" and total_seconds([]) == ""
