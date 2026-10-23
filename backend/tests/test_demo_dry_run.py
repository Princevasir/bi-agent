"""Demo gap D8: the demo scenarios as an automated dry run (evals/demo.py, evals/demo_cases.json)."""
import json
from pathlib import Path

import pytest

from evals import demo

CASES = json.loads((Path(__file__).resolve().parents[1] / "evals" / "demo_cases.json").read_text())["cases"]
DATA = {"route": "data", "sql": "SELECT 1", "columns": ["v"], "rows": [[376.09]], "answer": "376.09",
        "answer_source": "llm", "chart": None, "sources": [{"document_id": "sql-average-order-value"}], "trace": []}


def problems(expect, body=None, status=200, refs=None, model_calls=1):
    return demo.check(expect, status, DATA if body is None else body, refs or {}, model_calls)


# ---- the checks --------------------------------------------------------------------------------------------

def test_a_matching_answer_has_no_problems():
    assert problems({"route": "data", "rows_sql": "aov", "sources_include": ["sql-average-order-value"]},
                    refs={"aov": [[376.0940196]]}) == []


def test_each_mismatch_is_reported():
    found = problems({"route": "knowledge", "rows_sql": "aov", "sources_include": ["metric-revenue"]},
                     refs={"aov": [[206.0]]})
    assert len(found) == 3 and any("route" in p for p in found) and any("metric-revenue" in p for p in found)


def test_rows_ignore_labels_and_order():
    body = {**DATA, "rows": [["West", 2.0], ["North", 1.0]]}
    assert problems({"rows_sql": "r"}, body, refs={"r": [[1.0], [2.0]]}) == []
    assert problems({"rows_sql": "r"}, body, refs={"r": [[1.0], [3.0]]}) != []


def test_first_row_only():
    body = {**DATA, "rows": [[2025, 39905806.83], [2024, 1.0]]}
    assert problems({"first_row_sql": "fy"}, body, refs={"fy": [[39905806.83]]}) == []


def test_citations_must_be_in_the_answer():
    body = {**DATA, "route": "knowledge", "answer": "A supplier was late [doc-incident-q1-2026-tent-supply]."}
    assert problems({"cites": ["doc-incident-q1-2026-tent-supply"]}, body) == []
    assert problems({"cites": ["rule-fiscal-calendar"]}, body) != []


def test_chart_type_and_model_calls():
    body = {**DATA, "chart": {"type": "pie"}}
    assert problems({"chart": "pie", "model_calls": 0}, body, model_calls=0) == []
    assert problems({"chart": "bar", "model_calls": 0}, body, model_calls=2) != [] and \
        len(problems({"chart": "bar", "model_calls": 0}, body, model_calls=2)) == 2


def test_declined_means_no_sql_no_rows_and_the_decline_message():
    declined = {**DATA, "sql": "", "rows": [], "columns": [], "answer": "I can only answer questions about the data"}
    assert problems({"declined": True}, declined) == []
    assert problems({"declined": True}) != []


def test_refused_accepts_a_rejection_or_a_decline_but_never_rows():
    assert problems({"refused": True}, {"detail": "Personal data is not available."}, status=422) == []
    declined = {**DATA, "sql": "", "rows": [], "answer": "I can only answer questions about the data"}
    assert problems({"refused": True}, declined) == []
    assert problems({"refused": True}) != []                         # an answer with rows is not a refusal


def test_tables_that_must_never_be_read():
    body = {**DATA, "sql": "SELECT SUM(line_total) FROM order_items"}
    assert problems({"never_tables": ["orders", "order_items"]}, body) != []
    assert problems({"never_tables": ["orders"]}, {**DATA, "sql": "SELECT name FROM regions"}) == []


def test_status_and_plain_errors():
    assert problems({"status": [502, 503, 504]}, {"detail": "The language model request failed."}, status=502) == []
    assert problems({"status": [502, 503, 504]}, {"detail": "Traceback (most recent call last): ..."}, status=502) != []
    assert problems({"status": [200]}, status=500) != []


def test_row_count_answer_source_and_sources_count():
    body = {**DATA, "rows": [[1]] * 29, "answer_source": "catalog", "sources": []}
    assert problems({"row_count": 29, "answer_source": ["catalog"], "sources_count": 0}, body) == []
    assert len(problems({"row_count": 3, "answer_source": ["llm"], "sources_count": 1}, body)) == 3


def test_unknown_expectations_are_refused():
    with pytest.raises(ValueError, match="frobnicate"):
        problems({"frobnicate": 1})


# ---- the scenarios -------------------------------------------------------------------------------------------

def test_the_demo_has_at_least_five_scenarios_with_happy_and_unhappy_paths():
    assert len(CASES) >= 10 and len({c["id"] for c in CASES}) == len(CASES)
    kinds = {k for c in CASES for k in c["expect"]}
    assert {"rows_sql", "cites", "declined", "refused", "chart"} <= kinds
    assert {c.get("setup") for c in CASES} >= {"knowledge_down", "model_down"}
    assert any(c.get("role") == "limited" for c in CASES)


def test_every_scenario_is_well_formed():
    seen = set()
    for c in CASES:
        assert c.get("role", "analyst") in ("analyst", "limited"), c["id"]
        assert c.get("setup") in (None, "knowledge_down", "model_down"), c["id"]
        assert set(c["expect"]) <= demo.EXPECTATIONS, c["id"]
        assert c.get("follows") in (None, *seen), c["id"]                    # follows an earlier case
        for key in ("rows_sql", "first_row_sql"):
            if key in c["expect"]:
                assert c["expect"][key] in demo.REFERENCE_SQL, c["id"]
        seen.add(c["id"])


def test_reference_queries_are_fixed_code_not_model_text():
    from app.sqltypes import TrustedSQL
    assert all(isinstance(demo.trusted(name), TrustedSQL) for name in demo.REFERENCE_SQL)
