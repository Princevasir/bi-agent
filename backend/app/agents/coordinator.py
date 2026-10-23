"""Coordinator agent: understands each message and decides which agents handle it.

Chart changes go to the chart agent and questions about the data catalog to the knowledge agent,
neither calling the model; business questions ("How is revenue defined?", "Why did tent sales dip?")
are answered from the knowledge documents when there are any; everything else is a data question. Follow-ups are first rewritten into a
standalone question using the conversation so far.
"""
import re

from app.bi.catalog_answers import catalog_question
from app.bi.chart import is_chart_only
from app.bi.rewrite import rewrite_prompt

JOB = "Understands each message, rewrites follow-ups, and routes it to the right agents."
MAX_QUESTION_CHARS = 500


# Questions about the business rather than the data (demo gap D7)
KNOWLEDGE_PATTERNS = [
    r"\bhow (is|are|do we|do you|should we|does the company)\b.*\b(defined|define|calculated|calculate|measured|"
    r"measure|counted|count)\b",
    r"\bwhat (does|do) .+ mean\b", r"\bwhat counts as\b", r"\b(definition|meaning) of\b", r"^\s*define\b",
    r"\bwhen does the fiscal\b", r"\bfiscal (year|calendar|quarter)s? (start|begin|run|work)",
    r"\bwhat is (our|the)\b.*\b(policy|policies|rule|process|programme|program|threshold)\b",
    r"^\s*why (did|does|do|is|was|were)\b", r"\bwhat happened\b", r"\bwho owns\b",
    r"^\s*explain the\b.*\b(metric|rule|policy|definition)\b",
]


def is_about_knowledge(text):
    text = str(text).lower()
    return any(re.search(p, text) for p in KNOWLEDGE_PATTERNS)


def route(state, ctx):
    if is_chart_only(state["question"]):
        return {"route": "chart_change"}
    intent = catalog_question(state["question"], None)      # by wording only; no database call yet
    # Business knowledge outranks the catalog's metric list, never a table or column description.
    if ctx.knowledge is not None and is_about_knowledge(state["question"]) and intent in (None, ("metrics", None)):
        return {"route": "knowledge", "intent": intent}
    if intent:
        return {"route": "catalog", "intent": intent}
    return {"route": "data"}


def after_route(state):
    if state["route"] == "chart_change":
        return "redraw"
    if state["route"] == "catalog":
        return "catalog_answer"
    if state["route"] == "knowledge":
        return "find_knowledge"
    return "rewrite" if state.get("history") else "find_knowledge"


def rewrite(state, ctx):
    lines = ctx.generate(rewrite_prompt(state["question"], state["history"], state["today"])).strip().splitlines()
    text = lines[0].strip()[:MAX_QUESTION_CHARS] if lines else ""
    return {"standalone": text or state["question"]}

