import json

import pytest

from evals import run as runner
from evals.harness import load_cases
from routed_llm import RoutedLLM

CASES = {c["id"]: c for c in load_cases()}


def result(case_id, kind, passed):
    return {"id": case_id, "kind": kind, "passed": passed, "reason": "ok" if passed else "x"}


# ---- repeating and summarising ----

def test_a_case_passes_when_most_attempts_pass():
    outcomes = iter([True, False, True])
    case = {"id": "a", "kind": "answer"}
    [row] = runner.run_suite([case], lambda c: result(c["id"], c["kind"], next(outcomes)), repeat=3)
    assert row["passed"] and row["attempts"] == 3 and row["passes"] == 2


def test_a_case_fails_when_most_attempts_fail():
    outcomes = iter([False, True, False])
    case = {"id": "a", "kind": "answer"}
    [row] = runner.run_suite([case], lambda c: result(c["id"], c["kind"], next(outcomes)), repeat=3)
    assert not row["passed"]


def test_summary_separates_safety_failures_and_known_gaps():
    rows = [
        {"id": "a", "kind": "answer", "passed": True},
        {"id": "b", "kind": "answer", "passed": False},
        {"id": "s", "kind": "safety", "passed": False},
        {"id": "g", "kind": "known_gap", "passed": False},
    ]
    summary = runner.summarize(rows)
    assert summary["scored"] == 3 and summary["passed"] == 1
    assert summary["failed"] == ["b", "s"]
    assert summary["safety_failures"] == ["s"]
    assert summary["known_gaps"] == {"g": False}


# ---- baseline ----

def test_baseline_comparison_finds_regressions_improvements_and_new_cases():
    rows = [{"id": "a", "passed": False}, {"id": "b", "passed": True}, {"id": "c", "passed": True}]
    baseline = {"cases": {"a": True, "b": False}}
    diff = runner.compare_to_baseline(rows, baseline)
    assert diff == {"regressions": ["a"], "improvements": ["b"], "new": ["c"]}


def test_exit_code_rules():
    clean = {"safety_failures": []}
    no_diff = {"regressions": [], "improvements": [], "new": []}
    assert runner.exit_code(clean, no_diff, []) == 0
    assert runner.exit_code({"safety_failures": ["s"]}, no_diff, []) == 1
    assert runner.exit_code(clean, {**no_diff, "regressions": ["a"]}, []) == 1
    assert runner.exit_code(clean, no_diff, ["orders: 12 -> 11"]) == 1


# ---- command line ----

def test_refuses_to_run_with_the_fake_model(monkeypatch, capsys):
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    assert runner.main(["--case", "rev-sep"]) == 2
    assert "fake" in capsys.readouterr().err


def test_unknown_case_id_is_an_error(monkeypatch, capsys):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    assert runner.main(["--case", "no-such-case"]) == 2
    assert "no-such-case" in capsys.readouterr().err


@pytest.mark.integration
def test_end_to_end_writes_a_report_and_a_baseline(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setattr(runner, "get_llm", lambda: RoutedLLM(CASES["rev-sep"]["reference_sql"]))
    baseline = tmp_path / "baseline.json"
    args = ["--case", "rev-sep", "--out", str(tmp_path), "--baseline", str(baseline)]

    assert runner.main(args + ["--update-baseline"]) == 0
    assert json.loads(baseline.read_text())["cases"] == {"rev-sep": True}

    assert runner.main(args) == 0
    [report] = sorted(tmp_path.glob("report-*.json"))[-1:]
    data = json.loads(report.read_text())
    assert data["summary"]["passed"] == 1
    assert data["cases"][0]["id"] == "rev-sep" and data["cases"][0]["passed"]
    assert data["integrity_problems"] == []


@pytest.mark.integration
def test_a_regression_against_the_baseline_fails_the_run(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setattr(runner, "get_llm", lambda: RoutedLLM("SELECT 1"))
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"cases": {"rev-sep": True}}))
    assert runner.main(["--case", "rev-sep", "--out", str(tmp_path), "--baseline", str(baseline)]) == 1


def test_time_and_tokens_are_totals_across_attempts():
    spent = iter([(1.0, 100), (2.0, 200), (3.0, 300)])

    def run_one(case):
        secs, toks = next(spent)
        return {**result(case["id"], case["kind"], True), "seconds": secs, "tokens": toks}

    [row] = runner.run_suite([{"id": "a", "kind": "answer"}], run_one, repeat=3)
    assert row["seconds"] == 6.0 and row["tokens"] == 600


def test_summary_counts_validator_rejections_outside_safety_cases():
    rows = [
        {"id": "a", "kind": "answer", "passed": True, "attempt_reasons": ["ok", "error: SQLRejected: x", "ok"]},
        {"id": "b", "kind": "follow_up", "passed": False,
         "attempt_reasons": ["error: SQLRejected: y", "error: SQLRejected: y", "ok"]},
        {"id": "s", "kind": "safety", "passed": True, "attempt_reasons": ["blocked: SQLRejected"] * 3},
        {"id": "c", "kind": "answer", "passed": True, "reason": "ok"},
    ]
    summary = runner.summarize(rows)
    assert summary["rejected_attempts"] == 3
    assert summary["non_safety_attempts"] == 7


# ---- provider errors are "not scored", never failures (found when OpenRouter ran out of credit) ----

def _attempt(passed, reason="ok", not_scored=False):
    return {"id": "x", "kind": "answer", "passed": passed, "reason": reason, "not_scored": not_scored,
            "seconds": 1.0, "tokens": 10}


def test_a_provider_error_is_not_scored(monkeypatch):
    from app.llm.base import LLMConfigError
    from evals import harness

    def broken(*a, **kw):
        raise LLMConfigError("Provider rejected the request: HTTP 402")

    monkeypatch.setattr(harness, "answer_question", broken)
    case = {"id": "safe-delete", "kind": "safety", "role": "analyst", "turns": ["Delete all orders"]}
    result = harness.run_case(case, lambda p: "", None)
    assert result["not_scored"] is True and result["passed"] is False
    assert result["reason"] == "not scored: provider error (LLMConfigError)"


def test_majority_uses_only_scored_attempts():
    case = {"id": "x", "kind": "answer"}
    results = iter([_attempt(False, "not scored", True), _attempt(True), _attempt(False, "rows differ")])
    rows = runner.run_suite([case], lambda c: next(results), repeat=3)
    assert rows[0]["passes"] == 1 and rows[0]["scored_attempts"] == 2
    assert rows[0]["not_scored"] is False


def test_a_case_with_no_scored_attempt_is_not_scored():
    results = iter([_attempt(False, "not scored", True)] * 3)
    rows = runner.run_suite([{"id": "x", "kind": "safety"}], lambda c: next(results), repeat=3)
    assert rows[0]["not_scored"] is True


def test_not_scored_cases_are_neither_failures_nor_regressions():
    rows = [
        {"id": "a", "kind": "answer", "passed": True, "not_scored": False},
        {"id": "s", "kind": "safety", "passed": False, "not_scored": True},
        {"id": "b", "kind": "answer", "passed": False, "not_scored": True},
    ]
    summary = runner.summarize(rows)
    assert summary["scored"] == 1 and summary["passed"] == 1
    assert summary["failed"] == [] and summary["safety_failures"] == []
    assert summary["not_scored"] == ["s", "b"]
    diff = runner.compare_to_baseline(rows, {"cases": {"a": True, "s": True, "b": True}})
    assert diff["regressions"] == []


def test_an_incomplete_run_exits_with_2():
    no_diff = {"regressions": [], "improvements": [], "new": []}
    assert runner.exit_code({"safety_failures": [], "not_scored": ["s"]}, no_diff, []) == 2
    assert runner.exit_code({"safety_failures": ["t"], "not_scored": ["s"]}, no_diff, []) == 1


def test_each_model_has_its_own_baseline_file():
    assert runner.baseline_path("qwen/qwen-2.5-coder-32b-instruct").name == "qwen-qwen-2.5-coder-32b-instruct.json"
    assert runner.baseline_path("qwen2.5-coder:7b").name == "qwen2.5-coder-7b.json"
    assert runner.baseline_path("qwen2.5-coder:7b").parent.name == "baselines"


def test_baseline_merge_ignores_cases_that_were_not_scored():
    rows = [{"id": "a", "passed": True, "not_scored": False}, {"id": "s", "passed": False, "not_scored": True}]
    assert runner.merged_baseline_cases({"cases": {"s": True, "old": True}}, rows) == \
        {"a": True, "old": True, "s": True}


def test_repairs_are_counted_so_first_attempt_failures_stay_visible():
    results = iter([{**_attempt(True), "repairs": 1}, {**_attempt(True), "repairs": 0}, {**_attempt(True), "repairs": 1}])
    [row] = runner.run_suite([{"id": "x", "kind": "answer"}], lambda c: next(results), repeat=3)
    assert row["repairs"] == 2
    assert runner.summarize([row])["repairs"] == 2


def test_run_case_records_repairs(monkeypatch):
    from evals import harness
    monkeypatch.setattr(harness, "answer_question", lambda *a, **kw: {
        "sql": "SELECT 1", "columns": ["n"], "rows": [[1]], "answer": "1", "answer_source": "llm",
        "interpreted_as": "q", "truncated": False, "sql_repairs": 1})
    monkeypatch.setattr(harness, "reference_rows", lambda case: [[1]])
    case = {"id": "a", "kind": "answer", "role": "analyst", "turns": ["q"], "expected": [[1]]}
    assert harness.run_case(case, lambda p: "", None)["repairs"] == 1
