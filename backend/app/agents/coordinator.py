"""Coordinator agent: understands each message and decides which agents handle it.

Chart changes go to the chart agent and questions about the data to the knowledge agent, neither
calling the model; everything else is a data question. Follow-ups are first rewritten into a
standalone question using the conversation so far.
"""
from app.bi.catalog_answers import catalog_question
from app.bi.chart import is_chart_only
from app.bi.rewrite import rewrite_prompt

JOB = "Understands each message, rewrites follow-ups, and routes it to the right agents."
MAX_QUESTION_CHARS = 500


def route(state, ctx):
    if is_chart_only(state["question"]):
        return {"route": "chart_change"}
    intent = catalog_question(state["question"], None)      # by wording only; no database call yet
    if intent:
        return {"route": "catalog", "intent": intent}
    return {"route": "data"}


def after_route(state):
    if state["route"] == "chart_change":
        return "redraw"
    if state["route"] == "catalog":
        return "catalog_answer"
    return "rewrite" if state.get("history") else "find_knowledge"


def rewrite(state, ctx):
    lines = ctx.generate(rewrite_prompt(state["question"], state["history"], state["today"])).strip().splitlines()
    text = lines[0].strip()[:MAX_QUESTION_CHARS] if lines else ""
    return {"standalone": text or state["question"]}
