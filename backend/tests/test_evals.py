from datetime import date

import pytest

from app.access import ROLE_TABLES, tables_for
from app.bi.sql_guard import validate_sql
from app.db import run_readonly
from evals.harness import (
    KINDS, as_generate, check_integrity, load_cases, rows_match, run_case, score_rows, tables_in,
)
from routed_llm import RoutedLLM

TODAY = date(2026, 10, 15)
CASES = load_cases()
BY_ID = {c["id"]: c for c in CASES}
WITH_REFERENCE = [c for c in CASES if "reference_sql" in c]


def model(sql, rewrite=""):
    return as_generate(RoutedLLM(sql, rewrite=rewrite))


# ---- dataset ----

def test_dataset_is_well_formed():
    assert len(CASES) == 23
    assert len(BY_ID) == len(CASES)
    for case in CASES:
        assert case["kind"] in KINDS
        assert case["role"] in ROLE_TABLES
        assert case["turns"] and all(isinstance(t, str) for t in case["turns"])
        if case["kind"] in ("answer", "first_row", "follow_up", "no_data"):
            assert "reference_sql" in case and "expected" in case
        if case["kind"] == "follow_up":
            assert len(case["turns"]) > 1
        if case["kind"] == "no_query":
            assert "reference_sql" not in case
        if case["kind"] == "safety":
            assert isinstance(case["forbidden_tables"], list)
            assert "forbidden" not in case  # data values would go stale when the data changes


@pytest.mark.integration
@pytest.mark.parametrize("case", WITH_REFERENCE, ids=lambda c: c["id"])
def test_reference_query_is_valid_and_matches_expected(case):
    sql = validate_sql(case["reference_sql"], tables_for(case["role"]))
    rows = run_readonly(sql, role=case["role"])["rows"]
    assert score_rows(case, rows)


# ---- scoring a run ----

@pytest.mark.integration
@pytest.mark.parametrize("case", WITH_REFERENCE, ids=lambda c: c["id"])
def test_a_perfect_model_passes(case):
    result = run_case(case, model(case["reference_sql"]), TODAY)
    assert result["passed"], result["reason"]


@pytest.mark.integration
def test_a_wrong_query_fails_with_a_reason():
    august = BY_ID["rev-sep"]["reference_sql"].replace("2026-09-01", "2026-08-01").replace(
        "2026-10-01", "2026-09-01")
    result = run_case(BY_ID["rev-sep"], model(august), TODAY)
    assert not result["passed"]
    assert "rows differ" in result["reason"]


@pytest.mark.integration
def test_reading_forbidden_data_counts_as_blocked():
    result = run_case(BY_ID["safe-notes"], model("SELECT note FROM internal_notes"), TODAY)
    assert result["passed"]
    assert result["reason"].startswith("blocked")


@pytest.mark.integration
def test_safety_fails_when_a_forbidden_table_is_queried():
    case = {"id": "t", "kind": "safety", "role": "analyst", "turns": ["x"],
            "forbidden_tables": ["orders"]}
    result = run_case(case, model(BY_ID["rev-sep"]["reference_sql"]), TODAY)
    assert not result["passed"]
    assert "forbidden table" in result["reason"]


@pytest.mark.integration
def test_expected_answer_comes_from_the_current_data_not_the_stored_value():
    stale = {**BY_ID["rev-sep"], "expected": [[999]]}  # as if the data had changed since
    result = run_case(stale, model(stale["reference_sql"]), TODAY)
    assert result["passed"], result["reason"]


@pytest.mark.integration
def test_a_no_data_case_is_scored_as_an_answer_once_data_exists():
    now_has_data = {**BY_ID["rev-april"], "reference_sql": BY_ID["rev-sep"]["reference_sql"]}
    assert run_case(now_has_data, model(BY_ID["rev-sep"]["reference_sql"]), TODAY)["passed"]
    assert not run_case(now_has_data, model(BY_ID["rev-april"]["reference_sql"]), TODAY)["passed"]


def test_tables_in_lists_real_tables_and_skips_cte_names():
    sql = ("WITH c AS (SELECT * FROM orders) "
           "SELECT r.name FROM c JOIN regions r ON r.id = c.region_id")
    assert tables_in(sql) == {"orders", "regions"}


@pytest.mark.integration
def test_known_gap_fails_while_a_query_still_runs():
    gap = {"id": "g", "kind": "known_gap", "role": "analyst", "turns": ["hello"], "expect": "no_query"}
    result = run_case(gap, model("SELECT name FROM regions"), TODAY)
    assert not result["passed"]


def test_greetings_and_change_requests_are_scored_as_declines():
    for case_id in ("non-data-hello", "small-talk", "decline-change"):
        assert BY_ID[case_id]["kind"] == "no_query"


@pytest.mark.integration
def test_a_no_query_case_passes_only_when_the_model_declines():
    case = BY_ID["non-data-hello"]
    assert run_case(case, model("NO_QUERY"), TODAY)["passed"]
    result = run_case(case, model("SELECT name FROM regions"), TODAY)
    assert not result["passed"] and "query ran" in result["reason"]


# ---- comparison rules ----

def test_column_order_names_and_extra_columns_are_ignored():
    assert rows_match([["North", 270]], [[270.0, "north", 1]])


def test_numbers_must_match_to_two_decimals():
    assert rows_match([[135]], [[135.004]])
    assert not rows_match([[135]], [[135.2]])


def test_month_labels_are_normalised_when_asked():
    actual = [["2026-08-01T00:00:00", 570.0], ["2026-09-01", 810.0]]
    assert rows_match([["2026-08", 570], ["2026-09", 810]], actual, month=True)
    assert not rows_match([["2026-08", 570], ["2026-09", 810]], actual)


def test_a_missing_or_extra_row_fails():
    assert not rows_match([["North", 270], ["South", 300]], [["North", 270]])
    assert not rows_match([["North", 270]], [["North", 270], ["South", 300]])


def test_nulls_compare_equal():
    assert rows_match([[None]], [[None]])


def test_integrity_check_reports_changes():
    before = {"orders": 12, "orders_amount": 1490.0, "regions": 3}
    assert check_integrity(before, dict(before)) == []
    assert check_integrity(before, {**before, "orders": 11}) == ["orders: 12 -> 11"]
