"""Score the BI workflow against a fixed set of questions with known answers."""
import json
import re
from collections import Counter
from pathlib import Path

from app.access import AccessError
from app.bi.conversation import MAX_STORED_ROWS, Turn
from app.bi.service import answer_question, has_data
from app.bi.sql_guard import SQLRejected
from app.db import DBError, run_readonly
from app.llm.base import LLMError

CASES_PATH = Path(__file__).with_name("cases.json")
KINDS = {"answer", "first_row", "follow_up", "no_data", "safety", "known_gap"}
BLOCKED = (SQLRejected, AccessError, DBError)

_DATE = re.compile(r"^\d{4}-\d{2}(-\d{2}([T ].*)?)?$")
_NUMBER = re.compile(r"^-?\d+(\.\d+)?$")


def load_cases(path=CASES_PATH):
    return json.loads(Path(path).read_text())


def as_generate(llm):
    """Turn an LLMService into the prompt -> text function the workflow expects."""
    return lambda prompt: llm.generate(prompt).text


# ---- comparing rows ----

def _norm(value, month=False):
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    if isinstance(value, str):
        text = value.strip()
        if month and _DATE.match(text):
            return text[:7]
        if _NUMBER.match(text):
            return round(float(text), 2)
        return text.lower()
    return value


def _contains(expected_row, actual_row, month):
    want = Counter(_norm(v, month) for v in expected_row)
    have = Counter(_norm(v, month) for v in actual_row)
    return all(have[k] >= n for k, n in want.items())


def rows_match(expected, actual, month=False):
    """Same number of rows, and each expected row's values appear in a distinct actual row.

    Column order, column names and extra columns are ignored; row order is ignored.
    """
    if len(expected) != len(actual):
        return False
    unused = list(actual)
    for want in expected:
        for i, have in enumerate(unused):
            if _contains(want, have, month):
                del unused[i]
                break
        else:
            return False
    return True


def first_row_matches(expected, actual, month=False):
    return bool(actual) and _contains(expected[0], actual[0], month)


def score_rows(case, rows):
    month = case.get("month", False)
    if case["kind"] == "first_row":
        return first_row_matches(case["expected"], rows, month)
    return rows_match(case["expected"], rows, month)


# ---- running a case ----

def run_case(case, generate, today):
    """Ask every turn of a case through the real workflow and score the last answer."""
    result = {"id": case["id"], "kind": case["kind"], "role": case["role"], "passed": False,
              "reason": "", "sql": None, "rows": None, "answer": None,
              "answer_source": None, "interpreted_as": None}
    history = []
    try:
        for question in case["turns"]:
            out = answer_question(question, generate, today, history, role=case["role"])
            history.append(Turn(question=question, sql=out["sql"], columns=out["columns"],
                                rows=out["rows"][:MAX_STORED_ROWS], answer=out["answer"]))
    except BLOCKED as exc:
        blocked = case["kind"] == "safety"
        result.update(passed=blocked,
                      reason=f"blocked: {type(exc).__name__}" if blocked
                      else f"error: {type(exc).__name__}: {exc}")
        return result
    except LLMError as exc:
        result["reason"] = f"model error: {type(exc).__name__}"
        return result

    rows = out["rows"]
    result.update(sql=out["sql"], rows=rows[:10], answer=out["answer"],
                  answer_source=out["answer_source"], interpreted_as=out["interpreted_as"])
    kind = case["kind"]

    if kind == "safety":
        cells = [str(v).lower() for row in rows for v in row]
        hits = [f for f in case["forbidden"] if any(f.lower() in cell for cell in cells)]
        result.update(passed=not hits,
                      reason=f"forbidden value returned: {hits[0]}" if hits else "ran harmlessly")
    elif kind == "no_data":
        ok = not has_data(rows) and out["answer_source"] == "fallback"
        result.update(passed=ok, reason="ok" if ok else "data or a model-written answer returned")
    elif kind == "known_gap":
        ok = not out["sql"]
        result.update(passed=ok, reason="ok" if ok else "a query ran (expected no query)")
    else:
        ok = score_rows(case, rows)
        result.update(passed=ok, reason="ok" if ok else
                      f"rows differ: expected {case['expected']}, got {rows[:10]}")
    return result


# ---- data integrity ----

def integrity_snapshot():
    """Counts that must not change during an evaluation run (read through the analyst login)."""
    orders = run_readonly("SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM orders")["rows"][0]
    regions = run_readonly("SELECT COUNT(*) FROM regions")["rows"][0][0]
    return {"orders": orders[0], "orders_amount": float(orders[1]), "regions": regions}


def check_integrity(before, after):
    return [f"{key}: {before[key]} -> {after.get(key)}" for key in before
            if before[key] != after.get(key)]
