"""Chart agent: picks a chart for a result by fixed rules, and redraws the last result on request.

The model never picks a chart. A chart type named in the question becomes the suggestion if it
fits the data; "make it a pie chart" redraws the previous result with no model call or query.
"""
import re

from app.bi.chart import NAMES, apply_request, build_chart_spec, requested_chart
from app.bi.grounding import fallback_answer

JOB = "Chooses a chart for the result by fixed rules and redraws the last result when asked."
NOTHING_TO_REDRAW = "There is no earlier result to redraw yet. Ask a question about your data first."


def _chart_phrases(kind):
    """How an answer could name this chart type: its label, and 'pie graph' style variants."""
    label = NAMES[kind].lower()
    first = label.split()[0]
    words = {label} | ({f"{first} graph", f"{first} plot", f"{first} chart"} if " " in label else set())
    if kind == "donut":
        words |= {"doughnut chart"}
    return words - {"map"}                      # "map" alone is too common a word to count


def names_another_chart(answer, shown):
    """True when the answer names a chart type other than the one on screen."""
    text = (answer or "").lower()
    for kind in NAMES:
        if kind != shown and any(re.search(rf"\b{re.escape(p)}\b", text) for p in _chart_phrases(kind)):
            return True
    return False


def draw(state, ctx):
    requested = requested_chart(state["question"]) if state["rows"] else None   # nothing to draw, nothing to explain
    chart, note = apply_request(build_chart_spec(state["columns"], state["rows"]), requested)
    out = {"chart": chart, "chart_note": note}
    # The answer must not name a chart that is not shown (e.g. "A pie chart ..." above a line chart).
    if state.get("answer") and names_another_chart(state["answer"], chart["type"] if chart else None):
        out.update(answer=fallback_answer(state["columns"], state["rows"]), answer_source="fallback")
    return out


def redraw(state, ctx):
    last = next((t for t in reversed(state.get("history") or []) if t.rows), None)
    if last is None:
        return {"sql": "", "columns": [], "rows": [], "truncated": False, "answer": NOTHING_TO_REDRAW,
                "answer_source": "fallback", "chart": None, "chart_note": None}
    requested = requested_chart(state["question"])
    chart, note = apply_request(build_chart_spec(last.columns, last.rows), requested)
    shown = chart["type"] if chart else None
    answer = (f"Here is the same result as a {NAMES[shown]}." if shown == requested
              else "Here is the same result again.")
    return {"sql": last.sql, "columns": last.columns, "rows": last.rows, "truncated": False, "answer": answer,
            "answer_source": "chart_change", "chart": chart, "chart_note": note}

