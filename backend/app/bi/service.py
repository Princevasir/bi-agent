from app.bi.grounding import answer_prompt, fallback_answer, is_grounded
from app.bi.sql_guard import validate_sql
from app.bi.text_to_sql import generate_sql
from app.db import run_readonly


def answer_question(question, generate, today):
    sql = validate_sql(generate_sql(question, generate, today))
    result = run_readonly(sql)
    if not result["rows"]:
        answer, source = "The query returned no rows.", "fallback"
    else:
        draft = generate(answer_prompt(question, sql, result)).strip()
        if draft and is_grounded(draft, question, result["rows"]):
            answer, source = draft, "llm"
        else:
            answer, source = fallback_answer(result["columns"], result["rows"]), "fallback"
        if result["truncated"]:
            answer += f" Note: the result was truncated to the first {len(result['rows'])} rows."
    return {
        "question": question,
        "sql": sql,
        **result,
        "answer": answer,
        "answer_source": source,
    }