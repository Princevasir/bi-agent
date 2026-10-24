"""Adversarial evaluation (GR-EVAL-01): about 30 attacks through the real app on the retail data.

Direct and indirect injection (planted in a product and a campaign name), injection across
follow-ups, personal-data extraction, cross-role reads, cost bombs, data changes and prompt
disclosure. Each case must be refused, declined or answered safely, every time; the data must not
change. Exits 1 on any failure.

    cd backend && set -a && source ../.env && set +a && .venv/bin/python -m evals.adversarial [--repeat 3]
"""
import argparse
import json
import sys
import time
from collections import OrderedDict
from pathlib import Path

from evals import demo

HERE = Path(__file__).parent


def with_predecessors(cases, wanted):
    """The wanted cases plus every case they follow, in file order (a follow-up needs its conversation)."""
    by_id, keep = {c["id"]: c for c in cases}, set()
    for case_id in wanted:
        while case_id and case_id not in keep:
            keep.add(case_id)
            case_id = by_id[case_id].get("follows") if case_id in by_id else None
    return [c for c in cases if c["id"] in keep]


def summarize(rows):
    by_category, failed = OrderedDict(), []
    for r in rows:
        ok, total = by_category.get(r["category"], (0, 0))
        by_category[r["category"]] = (ok + bool(r["ok"]), total + 1)
        if not r["ok"] and r["id"] not in failed:
            failed.append(r["id"])
    return {"by_category": dict(by_category), "failed": failed}


def exit_code(summary, data_unchanged):
    return 1 if summary["failed"] or not data_unchanged else 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m evals.adversarial", description=__doc__.splitlines()[0])
    p.add_argument("--repeat", type=int, default=1, help="run every case this many times")
    p.add_argument("--case", action="append", default=[], help="run only this case (repeatable)")
    p.add_argument("--out", default=str(HERE / "reports"), help="folder for the JSON report")
    args = p.parse_args(argv)
    cases = json.loads((HERE / "adversarial_cases.json").read_text())["cases"]
    if args.case:
        cases = with_predecessors(cases, set(args.case))
    category = {c["id"]: c["category"] for c in cases}
    rows, unchanged = [], True
    for _ in range(args.repeat):
        results, same = demo.run(cases)
        unchanged = unchanged and same
        rows += [{**r, "category": category[r["id"]]} for r in results]
    summary = summarize(rows)
    print(f"{'case':26} {'category':20} {'result':8}  problem")
    for case in cases:
        mine = [r for r in rows if r["id"] == case["id"]]
        ok = sum(r["ok"] for r in mine)
        problem = next((("; ".join(r["problems"])) for r in mine if not r["ok"]), "")
        print(f"{case['id']:26} {case['category']:20} {'PASS' if ok == len(mine) else 'FAIL'} {ok}/{len(mine)}  {problem[:90]}")
    print()
    for cat, (ok, total) in summary["by_category"].items():
        print(f"{cat:20} {ok}/{total}")
    print(f"\npassed {len(rows) - sum(not r['ok'] for r in rows)}/{len(rows)} runs; "
          f"failed cases: {', '.join(summary['failed']) or 'none'}; data {'unchanged' if unchanged else 'CHANGED'}")
    Path(args.out).mkdir(parents=True, exist_ok=True)
    report = Path(args.out) / f"adversarial-{time.strftime('%Y%m%d-%H%M%S')}.json"
    report.write_text(json.dumps({"summary": summary, "data_unchanged": unchanged, "rows": rows}, indent=1, default=str))
    print(f"report: {report}")
    return exit_code(summary, unchanged)


if __name__ == "__main__":
    sys.exit(main())
