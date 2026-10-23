import re
from datetime import date

from app import policy
from app.access import denied_columns
from app.bi.schema import metrics_text, schema_text

FENCE = re.compile(r"```(?:sql)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
NO_QUERY = "NO_QUERY"


def rules_text(role: str = "analyst") -> str:
    """The SQL rules the validator enforces, worded for the model (GR-POL-02)."""
    p = policy.get()
    return (
        "Rules (the query is checked against these and rejected if it breaks one):\n"
        "- Read only: one SELECT, or a UNION, INTERSECT or EXCEPT of SELECTs. Never INSERT, UPDATE, DELETE "
        "or change the schema, not even inside WITH.\n"
        "- Join every table with a condition that links it to another table (JOIN ... ON a.col = b.col). "
        "No CROSS JOIN and no comma joins without a linking condition, except to a one-row total such as "
        "(SELECT sum(x) AS total FROM t).\n"
        f"- Use at most {p.sql['max_tables']} table references and at most {p.sql['max_depth']} levels "
        "of nested subqueries.\n"
        "- Do not use schema-qualified names or functions in FROM (such as generate_series or unnest).\n"
        f"- Use only these functions (CASE expressions and CAST or :: casts are also fine): "
        f"{', '.join(p.prompt_functions)}."
        + ("\n- Personal data (names, email addresses, phone numbers, street addresses, postal codes, "
           "salaries) is not available: never select it, and never use SELECT * on customers, "
           "customer_addresses or employees." if denied_columns(role) else "")
    )


def build_prompt(question: str, today: date, role: str = "analyst") -> str:
    return (
        "You write PostgreSQL for a BI tool. Return exactly one SELECT statement "
        "and nothing else. Use only the tables and columns listed below. "
        "Prefer the metric definitions. Use explicit date ranges. "
        "Any question about this data, including rankings, comparisons, totals and "
        "top or bottom values, must get a SELECT. "
        "Requests to draw, chart or plot data are questions about this data and must get a SELECT; "
        "the chart is drawn automatically from the result. "
        f"Only if the message is not a question about this data (for example a greeting or "
        f"small talk) or asks to change or delete data, return exactly {NO_QUERY} instead.\n\n"
        f"Today's date: {today.isoformat()}\n\n"
        f"Schema:\n{schema_text(role)}\n\nMetrics:\n{metrics_text(role)}\n\n"
        f"{rules_text(role)}\n\n"
        f"Question: {question}\nSQL:"
    )


def extract_sql(text: str) -> str:
    m = FENCE.search(text)
    return (m.group(1) if m else text).strip()


def is_no_query(text: str) -> bool:
    """True when the model declined to write a query."""
    return text.strip().rstrip(";.").strip().upper() == NO_QUERY


def generate_sql(question: str, generate, today: date, role: str = "analyst") -> str:
    return extract_sql(generate(build_prompt(question, today, role)))