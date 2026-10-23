"""Analyst agent: turns the query result into a short answer that is grounded in the rows.

The model drafts a sentence; every number in it must appear in the result or the question,
otherwise a plain answer is built from the rows instead.
"""
from app.bi.grounding import answer_prompt, fallback_answer, is_grounded

JOB = "Explains the result in a sentence and replaces it with a plain answer if any number is not grounded."


def has_data(rows):
    if not rows:
        return False
    return not (len(rows) == 1 and any(v is None for v in rows[0]))


def explain(state, ctx):
    question = state.get("standalone") or state["question"]
    result = {"columns": state["columns"], "rows": state["rows"], "truncated": state["truncated"]}
    return {"draft": ctx.generate(answer_prompt(question, state["sql"], result)).strip()}


def ground(state, ctx):
    context = f"{state['question']} {state.get('standalone', '')}"
    draft = state["draft"]
    if draft and is_grounded(draft, context, state["rows"]):
        answer, source = draft, "llm"
    else:
        answer, source = fallback_answer(state["columns"], state["rows"]), "fallback"
    if state["truncated"]:
        answer += f" Note: the result was truncated to the first {len(state['rows'])} rows."
    return {"answer": answer, "answer_source": source}


def no_rows(state, ctx):
    text = "The query returned no rows." if not state["rows"] else "No matching data was found."
    return {"answer": text, "answer_source": "fallback"}
