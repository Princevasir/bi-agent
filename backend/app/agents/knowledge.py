"""Knowledge agent: finds business knowledge for a question and answers questions about the data.

Retrieval (RAG) gives the SQL agent definitions, rules and example queries; questions such as
"What tables can I see?" are answered from the role's data catalog. It never calls the model.
"""
from app.bi.catalog_answers import answer as catalog_reply
from app.bi.schema import catalog_for, metrics_for

JOB = "Finds the business knowledge a question needs and answers questions about the data catalog."


def find_knowledge(state, ctx):
    question = state.get("standalone") or state["question"]
    hits = ctx.knowledge(question, state["role"]) if ctx.knowledge else []
    if state.get("route") == "knowledge" and not hits:      # nothing written down: hand the question back
        return {"knowledge": [], "route": "catalog" if state.get("intent") else "data"}
    return {"knowledge": hits}


def after_find(state):
    return {"knowledge": "explain_knowledge", "catalog": "catalog_answer"}.get(state.get("route"), "write_sql")


def catalog_answer(state, ctx):
    role = state["role"]
    return catalog_reply(state["intent"], catalog_for(role), metrics_for(role))
