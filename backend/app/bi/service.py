from app.bi.sql_guard import validate_sql
from app.bi.text_to_sql import generate_sql
from app.db import run_readonly


def answer_question(question, generate, today):
    sql = validate_sql(generate_sql(question, generate, today))
    result = run_readonly(sql)
    return {"question": question, "sql": sql, **result}