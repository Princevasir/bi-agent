from datetime import date
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.access import denied_columns, metric_rules, tables_for
from app.bi.chart import apply_request, build_chart_spec, requested_chart
from app.bi.grounding import answer_prompt, fallback_answer, is_grounded
from app.bi.rewrite import rewrite_prompt
from app.bi.catalog_answers import asks_for_personal_data, worth_a_second_opinion
from app.bi.sql_guard import PERSONAL_DATA_MESSAGE, SQLRejected, validate_sql
from app.bi.text_to_sql import NO_QUERY
from app.bi.text_to_sql import generate_sql, is_no_query
from app import limits
from app.db import DBQueryError, run_readonly

MAX_QUESTION_CHARS = 500
NO_QUERY_ANSWER = ("I can only answer questions about the data you have access to, "
                   "and I can't change data. "
                   'Try something like "What was revenue by region in September 2026?"')


class State(TypedDict, total=False):
    question: str
    today: date
    role: str
    history: list
    standalone: str
    sql: str
    columns: list
    rows: list
    truncated: bool
    draft: str
    answer: str
    answer_source: str
    repairs: int
    repair: tuple
    decline_retries: int


def has_data(rows):
    if not rows:
        return False
    return not (len(rows) == 1 and any(v is None for v in rows[0]))


def build_graph(generate):
    def rewrite(state):
        lines = generate(
            rewrite_prompt(state["question"], state["history"], state["today"])
        ).strip().splitlines()
        text = lines[0].strip()[:MAX_QUESTION_CHARS] if lines else ""
        return {"standalone": text or state["question"]}

    def write_sql(state):
        question = state.get("standalone") or state["question"]
        sql = generate_sql(question, generate, state["today"], role=state["role"], repair=state.get("repair"))
        return {"sql": sql, "repair": None}

    def retry_or_raise(state, failed_sql, reason, error):
        """GR-WF-01: one more try with the reason, if allowed; otherwise the failure stands."""
        if state.get("repairs", 0) >= limits.sql_repair_attempts():
            raise error
        return {"repair": (failed_sql, reason), "repairs": state.get("repairs", 0) + 1}

    def second_opinion(state):
        return {"repair": (NO_QUERY, ""), "decline_retries": state.get("decline_retries", 0) + 1}

    def declined(state):
        return {"sql": "", "columns": [], "rows": [], "truncated": False,
                "answer": NO_QUERY_ANSWER, "answer_source": "fallback"}

    def check_sql(state):
        try:
            return {"sql": validate_sql(state["sql"], tables_for(state["role"]), denied_columns(state["role"]),
                                        metric_rules())}
        except SQLRejected as e:
            question = state.get("standalone") or state["question"]
            unasked_personal = e.user_message == PERSONAL_DATA_MESSAGE and not asks_for_personal_data(question)
            if not (e.repairable or unasked_personal):
                raise
            reason = ("Personal data columns are not available: leave out names, email addresses, phone numbers, "
                      "street addresses, postal codes and salaries, and do not use SELECT *."
                      if unasked_personal else str(e))
            return retry_or_raise(state, state["sql"], reason, e)

    def execute(state):
        try:
            return run_readonly(state["sql"], role=state["role"])
        except DBQueryError as e:
            return retry_or_raise(state, state["sql"], e.detail or str(e), e)

    def no_rows(state):
        text = "The query returned no rows." if not state["rows"] else "No matching data was found."
        return {"answer": text, "answer_source": "fallback"}

    def explain(state):
        question = state.get("standalone") or state["question"]
        result = {
            "columns": state["columns"],
            "rows": state["rows"],
            "truncated": state["truncated"],
        }
        return {"draft": generate(answer_prompt(question, state["sql"], result)).strip()}

    def ground(state):
        context = f"{state['question']} {state.get('standalone', '')}"
        draft = state["draft"]
        if draft and is_grounded(draft, context, state["rows"]):
            answer, source = draft, "llm"
        else:
            answer, source = fallback_answer(state["columns"], state["rows"]), "fallback"
        if state["truncated"]:
            answer += f" Note: the result was truncated to the first {len(state['rows'])} rows."
        return {"answer": answer, "answer_source": source}

    def at_start(state):
        return "rewrite" if state.get("history") else "write_sql"

    def after_write(state):
        if not is_no_query(state["sql"]):
            return "check_sql"
        question = state.get("standalone") or state["question"]
        if worth_a_second_opinion(question) and state.get("decline_retries", 0) < limits.decline_retries():
            return "second_opinion"
        return "declined"

    def after_check(state):
        return "write_sql" if state.get("repair") else "execute"

    def after_execute(state):
        if state.get("repair"):
            return "write_sql"
        return "explain" if has_data(state["rows"]) else "no_rows"

    g = StateGraph(State)
    g.add_node("rewrite", rewrite)
    g.add_node("write_sql", write_sql)
    g.add_node("check_sql", check_sql)
    g.add_node("execute", execute)
    g.add_node("explain", explain)
    g.add_node("ground", ground)
    g.add_node("no_rows", no_rows)
    g.add_node("declined", declined)
    g.add_node("second_opinion", second_opinion)
    g.add_edge("second_opinion", "write_sql")
    g.add_conditional_edges(START, at_start, {"rewrite": "rewrite", "write_sql": "write_sql"})
    g.add_edge("rewrite", "write_sql")
    g.add_conditional_edges("write_sql", after_write,
                            {"declined": "declined", "check_sql": "check_sql", "second_opinion": "second_opinion"})
    g.add_edge("declined", END)
    g.add_conditional_edges("check_sql", after_check, {"write_sql": "write_sql", "execute": "execute"})
    g.add_conditional_edges(
        "execute", after_execute, {"write_sql": "write_sql", "explain": "explain", "no_rows": "no_rows"}
    )
    g.add_edge("explain", "ground")
    g.add_edge("ground", END)
    g.add_edge("no_rows", END)
    return g.compile()


def answer_question(question, generate, today, history=None, role="analyst"):
    state = {"question": question, "today": today, "history": history or [], "role": role}
    out = build_graph(generate).invoke(state)
    requested = requested_chart(question) if out["rows"] else None     # nothing to draw, nothing to explain
    chart, chart_note = apply_request(build_chart_spec(out["columns"], out["rows"]), requested)
    return {
        "question": question,
        "interpreted_as": out.get("standalone", question),
        "sql": out["sql"],
        "columns": out["columns"],
        "rows": out["rows"],
        "truncated": out["truncated"],
        "answer": out["answer"],
        "answer_source": out["answer_source"],
        "chart": chart,
        "chart_note": chart_note,
        "sql_repairs": out.get("repairs", 0),
        "decline_retries": out.get("decline_retries", 0),
    }