"""Chart agent: picks a chart for a result by fixed rules, and redraws the last result on request.

The model never picks a chart. A chart type named in the question becomes the suggestion if it
fits the data; "make it a pie chart" redraws the previous result with no model call or query.
"""
from app.bi.chart import NAMES, apply_request, build_chart_spec, requested_chart

JOB = "Chooses a chart for the result by fixed rules and redraws the last result when asked."
NOTHING_TO_REDRAW = "There is no earlier result to redraw yet. Ask a question about your data first."


def draw(state, ctx):
    requested = requested_chart(state["question"]) if state["rows"] else None   # nothing to draw, nothing to explain
    chart, note = apply_request(build_chart_spec(state["columns"], state["rows"]), requested)
    return {"chart": chart, "chart_note": note}


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
