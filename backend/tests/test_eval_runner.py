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
