from datetime import date
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.bi.grounding import answer_prompt, fallback_answer, is_grounded
from app.bi.rewrite import rewrite_prompt
from app.bi.sql_guard import validate_sql
from app.bi.text_to_sql import generate_sql
from app.db import run_readonly

MAX_QUESTION_CHARS = 500


class State(TypedDict, total=False):
    question: str
    today: date
    history: list
    standalone: str
    sql: str
    columns: list
    rows: list
    truncated: bool
    draft: str
    answer: str
    answer_source: str

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
        return {"sql": generate_sql(question, generate, state["today"])}

    def check_sql(state):
        return {"sql": validate_sql(state["sql"])}

    def execute(state):
        return run_readonly(state["sql"])

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

    def after_execute(state):
        return "explain" if has_data(state["rows"]) else "no_rows"

    g = StateGraph(State)
    g.add_node("rewrite", rewrite)
    g.add_node("write_sql", write_sql)
    g.add_node("check_sql", check_sql)
    g.add_node("execute", execute)
    g.add_node("explain", explain)
    g.add_node("ground", ground)
    g.add_node("no_rows", no_rows)
    g.add_conditional_edges(START, at_start, {"rewrite": "rewrite", "write_sql": "write_sql"})
    g.add_edge("rewrite", "write_sql")
    g.add_edge("write_sql", "check_sql")
    g.add_edge("check_sql", "execute")
    g.add_conditional_edges("execute", after_execute, {"explain": "explain", "no_rows": "no_rows"})
    g.add_edge("explain", "ground")
    g.add_edge("ground", END)
    g.add_edge("no_rows", END)
    return g.compile()


def answer_question(question, generate, today, history=None):
    state = {"question": question, "today": today, "history": history or []}
    out = build_graph(generate).invoke(state)
    return {
        "question": question,
        "interpreted_as": out.get("standalone", question),
        "sql": out["sql"],
        "columns": out["columns"],
        "rows": out["rows"],
        "truncated": out["truncated"],
        "answer": out["answer"],
        "answer_source": out["answer_source"],
    }