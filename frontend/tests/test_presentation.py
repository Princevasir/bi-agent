"""F1: labels, numbers, the big-number card and friendly status messages."""
import pytest

from client import BackendError
from presentation import (DECLINE_PREFIX, format_number, is_declined, is_no_data, pretty_label,
                          single_value, status_for)


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
