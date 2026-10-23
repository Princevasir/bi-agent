"""Ask the real model every evaluation question and compare with the saved baseline.

Usage (from backend/, database up, OpenRouter key in the environment):
    set -a; source ../.env; set +a
    .venv/bin/python -m evals.run [--repeat 3] [--case ID ...] [--update-baseline]
"""
import argparse
import json
import re
import os
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

from app.llm import get_llm
from app.llm.budget import TokenBudget
from evals.harness import check_integrity, integrity_snapshot, load_cases, run_case

HERE = Path(__file__).parent
DEFAULT_TODAY = "2026-10-15"
LOCAL_DATABASES = {
    "DATABASE_URL": "postgresql://bi_readonly:readonly_dev_pw@localhost:5433/analytics",
    "DATABASE_URL_LIMITED": "postgresql://bi_limited:limited_dev_pw@localhost:5433/analytics",
}


# ---- pure pieces (unit tested) ----

def run_suite(cases, run_one, repeat=1):
    """Run each case `repeat` times; it passes when most scored attempts pass.

    Attempts the provider could not answer are not scored; a case with none scored is not scored.
    """
    rows = []
    for case in cases:
        results = [run_one(case) for _ in range(repeat)]
        scored = [r for r in results if not r.get("not_scored")]
        passes = sum(1 for r in scored if r["passed"])
        passed = bool(scored) and passes * 2 > len(scored)
        shown = next((r for r in scored if r["passed"] == passed), scored[-1] if scored else results[-1])
        totals = {key: round(sum(r[key] for r in results), 2)
                  for key in ("seconds", "tokens") if key in shown}
        rows.append({**shown, **totals, "passed": passed, "passes": passes, "attempts": repeat,
                     "scored_attempts": len(scored), "not_scored": not scored,
                     "repairs": sum(r.get("repairs", 0) for r in results),
                     "attempt_reasons": [r["reason"] for r in results]})
    return rows


def summarize(rows):
    counted = [r for r in rows if not r.get("not_scored")]
    scored = [r for r in counted if r["kind"] != "known_gap"]
    attempts = [reason for r in counted if r["kind"] != "safety"
                for reason in r.get("attempt_reasons", [r.get("reason", "")])
                if not reason.startswith("not scored")]
    return {
        "scored": len(scored),
        "passed": sum(1 for r in scored if r["passed"]),
        "failed": [r["id"] for r in scored if not r["passed"]],
        "safety_failures": [r["id"] for r in scored if r["kind"] == "safety" and not r["passed"]],
        "known_gaps": {r["id"]: r["passed"] for r in counted if r["kind"] == "known_gap"},
        "not_scored": [r["id"] for r in rows if r.get("not_scored")],
        # GR-POL-02: how often the validator rejected the model's SQL where a query should have run.
        "rejected_attempts": sum(reason.startswith("error: SQLRejected") for reason in attempts),
        "non_safety_attempts": len(attempts),
        # GR-WF-01: attempts that only worked after one repair; first-attempt failures stay visible.
        "repairs": sum(r.get("repairs", 0) for r in counted),
    }


def compare_to_baseline(rows, baseline):
    before = baseline.get("cases", {})
    counted = [r for r in rows if not r.get("not_scored")]
    return {
        "regressions": [r["id"] for r in counted if before.get(r["id"]) is True and not r["passed"]],
        "improvements": [r["id"] for r in counted if before.get(r["id"]) is False and r["passed"]],
        "new": [r["id"] for r in counted if r["id"] not in before],
    }


def exit_code(summary, diff, integrity_problems):
    """1: a safety failure, regression or data change. 2: incomplete (cases not scored). 0: clean."""
    if summary["safety_failures"] or diff["regressions"] or integrity_problems:
        return 1
    return 2 if summary.get("not_scored") else 0


def merged_baseline_cases(baseline, rows):
    """The baseline's cases updated with this run's scored results; unscored cases keep their old value."""
    return dict(sorted({**baseline.get("cases", {}),
                        **{r["id"]: r["passed"] for r in rows if not r.get("not_scored")}}.items()))


def baseline_path(model):
    """Each model is compared only with its own accepted results."""
    return HERE / "baselines" / (re.sub(r"[^A-Za-z0-9._-]+", "-", model).strip("-") + ".json")


# ---- command line ----

def _parse(argv):
    p = argparse.ArgumentParser(prog="python -m evals.run", description=__doc__.splitlines()[0])
    p.add_argument("--repeat", type=int, default=1, help="ask each question this many times")
    p.add_argument("--case", action="append", default=[], help="run only this case ID (repeatable)")
    p.add_argument("--out", default=str(HERE / "reports"), help="folder for the JSON report")
    p.add_argument("--baseline", help="baseline file (default: evals/baselines/<model>.json)")
    p.add_argument("--update-baseline", action="store_true", help="accept this run as the baseline")
    p.add_argument("--today", default=DEFAULT_TODAY, help="date the workflow treats as today")
    p.add_argument("--max-tokens", type=int, default=200_000, help="stop calling the model after this")
    return p.parse_args(argv)


def _print_table(rows, summary, diff, problems, tokens):
    print(f"{'case':<18} {'kind':<10} {'result':<11} {'secs':>6} {'tokens':>7}  reason")
    for r in rows:
        mark = ("PASS" if r["passed"] else "FAIL") + f" {r['passes']}/{r['attempts']}"
        print(f"{r['id']:<18} {r['kind']:<10} {mark:<11} {r['seconds']:>6.1f} {r['tokens']:>7}  "
              f"{r['reason'][:70]}")
    print()
    print(f"passed {summary['passed']}/{summary['scored']} scored cases; tokens used {tokens}")
    print(f"safety failures: {summary['safety_failures'] or 'none'}")
    print(f"known gaps: {summary['known_gaps'] or 'none'}")
    if summary["not_scored"]:
        print(f"NOT SCORED (provider errors, run incomplete): {summary['not_scored']}")
    print(f"regressions: {diff['regressions'] or 'none'}; improvements: {diff['improvements'] or 'none'}")
    print(f"validator rejections where a query should run: "
          f"{summary['rejected_attempts']} of {summary['non_safety_attempts']} attempts")
    print(f"SQL repairs (first attempt failed, one retry used): {summary['repairs']}")
    print(f"data integrity: {problems or 'unchanged'}")


def main(argv=None):
    args = _parse(argv)
    if os.getenv("LLM_PROVIDER", "fake") == "fake":
        print("LLM_PROVIDER is 'fake'; an evaluation needs the real model. "
              "Load your .env first: set -a; source ../.env; set +a", file=sys.stderr)
        return 2

    cases = load_cases()
    if args.case:
        known = {c["id"] for c in cases}
        unknown = [c for c in args.case if c not in known]
        if unknown:
            print(f"unknown case ID: {', '.join(unknown)}", file=sys.stderr)
            return 2
        cases = [c for c in cases if c["id"] in args.case]

    for key, value in LOCAL_DATABASES.items():
        os.environ.setdefault(key, value)

    llm = get_llm()
    budget = TokenBudget(args.max_tokens)
    used = {"tokens": 0}

    def generate(prompt):
        budget.check()
        out = llm.generate(prompt)
        spent = out.input_tokens + out.output_tokens
        budget.record(spent)
        used["tokens"] += spent
        return out.text

    today = date.fromisoformat(args.today)

    def run_one(case):
        start, tokens_before = time.perf_counter(), used["tokens"]
        res = run_case(case, generate, today)
        return {**res, "seconds": round(time.perf_counter() - start, 2),
                "tokens": used["tokens"] - tokens_before}

    before = integrity_snapshot()
    rows = run_suite(cases, run_one, repeat=args.repeat)
    problems = check_integrity(before, integrity_snapshot())

    model = getattr(llm, "model", "unknown-model")
    bpath = Path(args.baseline) if args.baseline else baseline_path(model)
    baseline = json.loads(bpath.read_text()) if bpath.exists() else {"cases": {}}
    summary, diff = summarize(rows), compare_to_baseline(rows, baseline)
    now = datetime.now(timezone.utc)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {"created": now.isoformat(), "model": model, "today": args.today,
              "repeat": args.repeat, "tokens": used["tokens"], "summary": summary,
              "diff": diff, "integrity_problems": problems, "cases": rows}
    report_path = out_dir / f"report-{now:%Y%m%d-%H%M%S-%f}.json"
    report_path.write_text(json.dumps(report, indent=2, default=str) + "\n")

    _print_table(rows, summary, diff, problems, used["tokens"])
    print(f"report: {report_path}")

    print(f"model: {model}; baseline: {bpath}{'' if bpath.exists() else ' (none yet)'}")
    if args.update_baseline and summary["not_scored"]:
        print("incomplete run (cases not scored); baseline NOT updated", file=sys.stderr)
    elif args.update_baseline:
        bpath.parent.mkdir(parents=True, exist_ok=True)
        bpath.write_text(json.dumps(
            {"model": model, "updated": now.isoformat(), "today": args.today,
             "repeat": args.repeat, "cases": merged_baseline_cases(baseline, rows)}, indent=2) + "\n")
        print(f"baseline updated: {bpath}")
        diff = {**diff, "regressions": []}

    return exit_code(summary, diff, problems)


if __name__ == "__main__":
    sys.exit(main())
