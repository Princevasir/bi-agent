"""The workflow: five specialist agents (app/agents) wired into one LangGraph graph.

The coordinator routes each message; the graph runs the steps of the agents it chose, records each
step in the trace, and stops within max_steps whatever happens.
"""
import operator
import time
from dataclasses import dataclass
from datetime import date
from typing import Annotated, Callable, Optional, TypedDict

from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph

from app import limits
from app.bi.assumptions import assumptions
from app.agents import OWNER, analyst, chart, coordinator, sql
from app.agents import knowledge as knowledge_agent
from app.agents.analyst import has_data  # noqa: F401  (used by the evaluation harness)
from app.agents.sql import NO_QUERY_ANSWER  # noqa: F401


class DeadlineExceeded(Exception):
    """The question passed its deadline; no further step was started (GR-WF-02)."""


class StepLimitError(Exception):
    """The workflow reached max_steps without finishing; it is stopped rather than left to loop."""


class State(TypedDict, total=False):
    question: str
    today: date
    role: str
    history: list
    route: str
    intent: tuple
    standalone: str
    knowledge: list
    sql: str
    columns: list
    rows: list
    truncated: bool
    draft: str
    answer: str
    answer_source: str
    chart: Optional[dict]
    chart_note: Optional[str]
    repairs: int
    suppressed: int
    repair: tuple
    decline_retries: int
    trace: Annotated[list, operator.add]


@dataclass(frozen=True)
class Context:
    generate: Callable
    knowledge: Optional[Callable] = None
    deadline: Optional[float] = None          # time.monotonic() value after which no step starts (GR-WF-02)


STEPS = {
    "route": coordinator.route, "rewrite": coordinator.rewrite,
    "find_knowledge": knowledge_agent.find_knowledge, "catalog_answer": knowledge_agent.catalog_answer,
    "write_sql": sql.write_sql, "second_opinion": sql.second_opinion, "check_sql": sql.check_sql,
    "execute": sql.execute, "declined": sql.declined,
    "explain": analyst.explain, "ground": analyst.ground, "no_rows": analyst.no_rows,
    "explain_knowledge": analyst.explain_knowledge, "check_citations": analyst.check_citations,
    "draw": chart.draw, "redraw": chart.redraw,
}


def _traced(name, step, ctx):
    def run(state):
        if ctx.deadline is not None and time.monotonic() > ctx.deadline:
            raise DeadlineExceeded(f"The question passed its deadline before step {name}.")
        started = time.perf_counter()
        out = step(state, ctx)
        ms = round((time.perf_counter() - started) * 1000, 1)
        return {**out, "trace": [{"agent": OWNER[name], "step": name, "ms": ms}]}
    return run


def build_graph(generate, knowledge=None, deadline=None):
    ctx = Context(generate, knowledge, deadline)
    g = StateGraph(State)
    for name, step in STEPS.items():
        g.add_node(name, _traced(name, step, ctx))
    g.add_edge(START, "route")
    g.add_conditional_edges("route", coordinator.after_route,
                            {"redraw": "redraw", "catalog_answer": "catalog_answer", "declined": "declined",
                             "rewrite": "rewrite", "find_knowledge": "find_knowledge"})
    g.add_edge("rewrite", "find_knowledge")
    g.add_conditional_edges("find_knowledge", knowledge_agent.after_find,
                            {"explain_knowledge": "explain_knowledge", "catalog_answer": "catalog_answer",
                             "write_sql": "write_sql"})
    g.add_edge("explain_knowledge", "check_citations")
    g.add_conditional_edges("write_sql", sql.after_write,
                            {"declined": "declined", "check_sql": "check_sql", "second_opinion": "second_opinion"})
    g.add_edge("second_opinion", "write_sql")
    g.add_conditional_edges("check_sql", sql.after_check, {"write_sql": "write_sql", "execute": "execute"})
    g.add_conditional_edges("execute", lambda s: sql.after_execute(s, analyst.has_data),
                            {"write_sql": "write_sql", "explain": "explain", "no_rows": "no_rows"})
    g.add_edge("explain", "ground")
    g.add_edge("ground", "draw")
    g.add_edge("no_rows", "draw")
    for last in ("draw", "redraw", "catalog_answer", "declined", "check_citations"):
        g.add_edge(last, END)
    return g.compile()


def answer_question(question, generate, today, history=None, role="analyst", knowledge=None):
    """knowledge(question, role) returns retrieved documents for the SQL prompt (RAG R6), or None for none."""
    state = {"question": question, "today": today, "history": history or [], "role": role, "trace": []}
    max_steps = limits.workflow_max_steps()
    try:
        deadline = time.monotonic() + limits.request_deadline_seconds()
        out = build_graph(generate, knowledge, deadline).invoke(state, config={"recursion_limit": max_steps})
    except GraphRecursionError as e:
        raise StepLimitError(f"The workflow did not finish within {max_steps} steps.") from e
    return {
        "question": question,
        "interpreted_as": out.get("standalone", question),
        "route": out["route"],
        "intent": out.get("intent"),
        "sql": out["sql"],
        "assumptions": assumptions(out["sql"]) if out["sql"] else [],      # GR-ACC-03
        "columns": out["columns"],
        "rows": out["rows"],
        "truncated": out["truncated"],
        "answer": out["answer"],
        "answer_source": out["answer_source"],
        "chart": out.get("chart"),
        "chart_note": out.get("chart_note"),
        "sql_repairs": out.get("repairs", 0),
        "suppressed_groups": out.get("suppressed", 0),
        "decline_retries": out.get("decline_retries", 0),
        "sources": [{"document_id": h.document_id, "title": h.title, "doc_type": h.doc_type, "owner": h.owner,
                     "version": h.version, "score": h.score} for h in out.get("knowledge") or []],
        "trace": out["trace"],
    }
