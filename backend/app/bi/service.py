from datetime import date
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.bi.grounding import answer_prompt, fallback_answer, is_grounded
from app.bi.sql_guard import validate_sql
from app.bi.text_to_sql import generate_sql
from app.db import run_readonly


class State(TypedDict, total=False):
    question: str
    today: date
    sql: str
    columns: list
    rows: list
    truncated: bool
    draft: str
    answer: str
    answer_source: str


def build_graph(generate):
    def write_sql(state):
        return {"sql": generate_sql(state["question"], generate, state["today"])}

    def check_sql(state):
        return {"sql": validate_sql(state["sql"])}

    def execute(state):
        return run_readonly(state["sql"])

    def no_rows(state):
        return {"answer": "The query returned no rows.", "answer_source": "fallback"}

    def explain(state):
        result = {
            "columns": state["columns"],
            "rows": state["rows"],
            "truncated": state["truncated"],
        }
        return {"draft": generate(answer_prompt(state["question"], state["sql"], result)).strip()}

    def ground(state):
        draft = state["draft"]
        if draft and is_grounded(draft, state["question"], state["rows"]):
            answer, source = draft, "llm"
        else:
            answer, source = fallback_answer(state["columns"], state["rows"]), "fallback"
        if state["truncated"]:
            answer += f" Note: the result was truncated to the first {len(state['rows'])} rows."
        return {"answer": answer, "answer_source": source}

    def after_execute(state):
        return "explain" if state["rows"] else "no_rows"

    g = StateGraph(State)
    g.add_node("write_sql", write_sql)
    g.add_node("check_sql", check_sql)
    g.add_node("execute", execute)
    g.add_node("explain", explain)
    g.add_node("ground", ground)
    g.add_node("no_rows", no_rows)
    g.add_edge(START, "write_sql")
    g.add_edge("write_sql", "check_sql")
    g.add_edge("check_sql", "execute")
    g.add_conditional_edges("execute", after_execute, {"explain": "explain", "no_rows": "no_rows"})
    g.add_edge("explain", "ground")
    g.add_edge("ground", END)
    g.add_edge("no_rows", END)
    return g.compile()


def answer_question(question, generate, today):
    out = build_graph(generate).invoke({"question": question, "today": today})
    return {
        "question": question,
        "sql": out["sql"],
        "columns": out["columns"],
        "rows": out["rows"],
        "truncated": out["truncated"],
        "answer": out["answer"],
        "answer_source": out["answer_source"],
    }