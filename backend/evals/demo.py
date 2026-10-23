"""Demo dry run (demo gap D8): every live-demo scenario through the real app, model, data and knowledge.

Runs in-process against the local stack: the retail database, the knowledge index and the model named
by LLM_PROVIDER (with LLM_FALLBACK_PROVIDER if set). Signs in as the scenario's role, follows up in the
same conversation where a scenario says so, and deliberately breaks things (knowledge index down,
model down) to show graceful failure. Expected numbers come from fixed reference queries on the
current data. Exits 1 if any scenario fails or the data changed.

    cd backend && set -a && source ../.env && set +a && .venv/bin/python -m evals.demo
"""
import argparse
import os
import re
import sys
import time

from evals.harness import first_row_matches, rows_match, tables_in

EXPECTATIONS = {"status", "route", "rows_sql", "first_row_sql", "sources_include", "sources_count", "cites",
                "chart", "model_calls", "declined", "refused", "never_tables", "row_count", "answer_source"}
DECLINE_PREFIX = "I can only answer"
UNPLAIN = re.compile(r"Traceback|Exception|psycopg|sqlglot|File \"", re.IGNORECASE)

REVENUE = "SUM(oi.line_total) FROM orders o JOIN order_items oi ON oi.order_id = o.order_id WHERE o.status = 'completed'"
REFERENCE_SQL = {
    "aov_2025": "SELECT SUM(oi.line_total) / COUNT(DISTINCT o.order_id) FROM orders o JOIN order_items oi "
                "ON oi.order_id = o.order_id WHERE o.status = 'completed' "
                "AND o.ordered_at >= '2025-01-01' AND o.ordered_at < '2026-01-01'",
    "revenue_by_region_2025": "SELECT SUM(oi.line_total) FROM orders o JOIN order_items oi ON oi.order_id = o.order_id "
                              "LEFT JOIN stores s ON s.store_id = o.store_id "
                              "LEFT JOIN customer_addresses a ON a.address_id = o.shipping_address_id "
                              "LEFT JOIN countries c ON c.country_id = COALESCE(s.country_id, a.country_id) "
                              "LEFT JOIN regions r ON r.region_id = c.region_id "
                              "WHERE o.status = 'completed' AND o.ordered_at >= '2025-01-01' "
                              "AND o.ordered_at < '2026-01-01' GROUP BY r.region_id",
    "revenue_fy2025": f"SELECT {REVENUE} AND o.ordered_at >= '2025-02-01' AND o.ordered_at < '2026-02-01'",
    "revenue_fy2024": f"SELECT {REVENUE} AND o.ordered_at >= '2024-02-01' AND o.ordered_at < '2025-02-01'",
}


def trusted(name):
    """Reference queries are fixed text written here, never model output (GR-SQL-06)."""
    from app.sqltypes import TrustedSQL
    return TrustedSQL(REFERENCE_SQL[name])


def _declined(body):
    return not body.get("sql") and not body.get("rows") and str(body.get("answer", "")).startswith(DECLINE_PREFIX)


def check(expect, status, body, refs, model_calls):
    """Problems with one answer, as short sentences; an empty list means the scenario passed."""
    unknown = set(expect) - EXPECTATIONS
    if unknown:
        raise ValueError(f"Unknown expectation: {', '.join(sorted(unknown))}")
    out, rows = [], body.get("rows") or []
    if "status" in expect and status not in expect["status"]:
        out.append(f"status {status}, expected {expect['status']}")
    if status != 200 and UNPLAIN.search(str(body.get("detail", ""))):
        out.append("the error message is not plain")
    if "route" in expect and body.get("route") != expect["route"]:
        out.append(f"route {body.get('route')}, expected {expect['route']}")
    if "rows_sql" in expect and not rows_match(refs[expect["rows_sql"]], rows):
        out.append(f"rows differ from {expect['rows_sql']}: got {rows[:4]}")
    if "first_row_sql" in expect and not first_row_matches(refs[expect["first_row_sql"]], rows):
        out.append(f"first row differs from {expect['first_row_sql']}: got {rows[:2]}")
    sources = [s["document_id"] for s in body.get("sources") or []]
    for doc in expect.get("sources_include", []):
        if doc not in sources:
            out.append(f"source {doc} missing")
    if "sources_count" in expect and len(sources) != expect["sources_count"]:
        out.append(f"{len(sources)} sources, expected {expect['sources_count']}")
    for doc in expect.get("cites", []):
        if f"[{doc}]" not in str(body.get("answer", "")):
            out.append(f"answer does not cite {doc}")
    if "chart" in expect and (body.get("chart") or {}).get("type") != expect["chart"]:
        out.append(f"chart {(body.get('chart') or {}).get('type')}, expected {expect['chart']}")
    if "model_calls" in expect and model_calls != expect["model_calls"]:
        out.append(f"{model_calls} model calls, expected {expect['model_calls']}")
    if expect.get("declined") and not _declined(body):
        out.append("not declined")
    if expect.get("refused") and not (status in (403, 422) or _declined(body)):
        out.append(f"not refused (status {status}, {len(rows)} rows)")
    read = tables_in(body["sql"]) if body.get("sql") else set()
    for table in expect.get("never_tables", []):
        if table in read:
            out.append(f"read {table}")
    if "row_count" in expect and len(rows) != expect["row_count"]:
        out.append(f"{len(rows)} rows, expected {expect['row_count']}")
    if "answer_source" in expect and body.get("answer_source") not in expect["answer_source"]:
        out.append(f"answer source {body.get('answer_source')}, expected {expect['answer_source']}")
    return out


# ---- running the scenarios against the local stack ---------------------------------------------------------

LOCAL = {   # local development logins (as in tests/conftest.py); the stack's ports on this machine
    "APP_DATABASE_URL": "postgresql://app_rw:app_dev_pw@localhost:5433/appdb",
    "DATABASE_URL": "postgresql://bi_readonly:readonly_dev_pw@localhost:5433/analytics",
    "DATABASE_URL_LIMITED": "postgresql://bi_limited:limited_dev_pw@localhost:5433/analytics",
    "RETAIL_DATABASE_URL": "postgresql://retail_analyst:retail_analyst_dev_pw@localhost:5433/retail",
    "RETAIL_DATABASE_URL_LIMITED": "postgresql://retail_limited:retail_limited_dev_pw@localhost:5433/retail",
    "JWT_SECRET": "dry-run-only-" + "x" * 32,
}


class Counting:
    def __init__(self, llm):
        self.llm, self.calls = llm, 0

    def generate(self, prompt):
        self.calls += 1
        return self.llm.generate(prompt)


def _returning(value):
    """A dependency override without parameters: FastAPI would treat parameters as request inputs."""
    def dependency():
        return value
    return dependency


def run(cases):
    for name, value in LOCAL.items():
        os.environ.setdefault(name, value)
    os.environ["DATA_SOURCE"] = "retail"
    from fastapi.testclient import TestClient

    from app import audit
    from app.appdb import User
    from app.auth import current_user
    from app.db import run_readonly
    from app.knowledge import context
    from app.knowledge.embeddings import EmbeddingError
    from app.llm import get_llm
    from app.llm.openrouter import OpenRouterLLM
    from app.main import app
    from app.sqltypes import TrustedSQL

    audit._write = lambda entry: None             # a rehearsal: keep it out of the audit trail
    refs = {name: run_readonly(trusted(name), role="analyst")["rows"] for name in REFERENCE_SQL}
    integrity = TrustedSQL("SELECT COUNT(*), SUM(line_total) FROM order_items")
    before = run_readonly(integrity, role="analyst")["rows"]
    client, conversations, results = TestClient(app), {}, []
    real_retrieve = context.retrieve
    for case in cases:
        role = case.get("role", "analyst")
        app.dependency_overrides[current_user] = _returning(User(username=f"dry-run-{role}", role=role))
        if case.get("setup") == "model_down":
            model = Counting(OpenRouterLLM(api_key=None, model="none", timeout=3,
                                           url="http://127.0.0.1:9/v1/chat/completions"))
        else:
            model = Counting(get_llm())
        app.dependency_overrides[get_llm] = _returning(model)
        if case.get("setup") == "knowledge_down":
            def down(*a, **kw):
                raise EmbeddingError("The embedding model is unreachable (dry run).")
            context.retrieve = down
        payload = {"message": case["message"]}
        if case.get("follows"):
            payload["conversation_id"] = conversations.get(case["follows"])
        started = time.monotonic()
        try:
            r = client.post("/ask", json=payload)
            status, body = r.status_code, r.json()
        finally:
            context.retrieve = real_retrieve
        if status == 200:
            conversations[case["id"]] = body.get("conversation_id")
        found = check(case["expect"], status, body, refs, model.calls)
        results.append({"id": case["id"], "ok": not found, "problems": found, "seconds": time.monotonic() - started,
                        "answer": str(body.get("answer") or body.get("detail", ""))[:90]})
    app.dependency_overrides.clear()
    after = run_readonly(integrity, role="analyst")["rows"]
    return results, before == after


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m evals.demo", description=__doc__.splitlines()[0])
    p.add_argument("--case", action="append", default=[], help="run only this scenario (repeatable)")
    args = p.parse_args(argv)
    import json
    from pathlib import Path
    cases = json.loads((Path(__file__).with_name("demo_cases.json")).read_text())["cases"]
    if args.case:
        cases = [c for c in cases if c["id"] in args.case or any(c["id"] == f for f in args.case)]
    results, unchanged = run(cases)
    print(f"{'scenario':18} {'result':6} {'secs':>6}  answer or problem")
    for r in results:
        detail = "; ".join(r["problems"]) if r["problems"] else r["answer"]
        print(f"{r['id']:18} {'PASS' if r['ok'] else 'FAIL':6} {r['seconds']:6.1f}  {detail}")
    passed = sum(r["ok"] for r in results)
    print(f"\npassed {passed}/{len(results)} scenarios; data {'unchanged' if unchanged else 'CHANGED'}")
    return 0 if passed == len(results) and unchanged else 1


if __name__ == "__main__":
    sys.exit(main())
