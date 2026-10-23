"""SQL agent: turns a question into one safe, read-only query and runs it.

The model writes the query; the validator, not the model, decides whether it may run; it runs on
the role's read-only login. A fixable failure gets one repair and a decline about the data gets one
second opinion, both bounded by the policy file.
"""
from app import limits
from app.access import denied_columns, metric_rules, tables_for
from app.bi.catalog_answers import asks_for_personal_data, worth_a_second_opinion
from app.bi.sql_guard import PERSONAL_DATA_MESSAGE, SQLRejected, validate_sql
from app.bi.text_to_sql import NO_QUERY, generate_sql, is_no_query
from app.db import DBQueryError, run_readonly

JOB = "Writes one read-only query for the question, has it validated, and runs it on the role's login."
NO_QUERY_ANSWER = ("I can only answer questions about the data you have access to, "
                   "and I can't change data. "
                   'Try something like "What was revenue by region in September 2026?"')


def write_sql(state, ctx):
    question = state.get("standalone") or state["question"]
    sql = generate_sql(question, ctx.generate, state["today"], role=state["role"], repair=state.get("repair"),
                       knowledge=state.get("knowledge"))
    return {"sql": sql, "repair": None}


def retry_or_raise(state, failed_sql, reason, error):
    """GR-WF-01: one more try with the reason, if allowed; otherwise the failure stands."""
    if state.get("repairs", 0) >= limits.sql_repair_attempts():
        raise error
    return {"repair": (failed_sql, reason), "repairs": state.get("repairs", 0) + 1}


def second_opinion(state, ctx):
    return {"repair": (NO_QUERY, ""), "decline_retries": state.get("decline_retries", 0) + 1}


def declined(state, ctx):
    return {"sql": "", "columns": [], "rows": [], "truncated": False,
            "answer": NO_QUERY_ANSWER, "answer_source": "fallback"}


def check_sql(state, ctx):
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


def execute(state, ctx):
    try:
        return run_readonly(state["sql"], role=state["role"])
    except DBQueryError as e:
        return retry_or_raise(state, state["sql"], e.detail or str(e), e)


def after_write(state):
    if not is_no_query(state["sql"]):
        return "check_sql"
    question = state.get("standalone") or state["question"]
    if worth_a_second_opinion(question) and state.get("decline_retries", 0) < limits.decline_retries():
        return "second_opinion"
    return "declined"


def after_check(state):
    return "write_sql" if state.get("repair") else "execute"


def after_execute(state, has_data):
    if state.get("repair"):
        return "write_sql"
    return "explain" if has_data(state["rows"]) else "no_rows"
