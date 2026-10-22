import re
from datetime import date

from app.bi.schema import metrics_text, schema_text

FENCE = re.compile(r"```(?:sql)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
NO_QUERY = "NO_QUERY"


def build_prompt(question: str, today: date, role: str = "analyst") -> str:
    return (
        "You write PostgreSQL for a BI tool. Return exactly one SELECT statement "
        "and nothing else. Use only the tables and columns listed below. "
        "Prefer the metric definitions. Use explicit date ranges. "
        "Any question about this data, including rankings, comparisons, totals and "
        "top or bottom values, must get a SELECT. "
        f"Only if the message is not a question about this data (for example a greeting or "
        f"small talk) or asks to change or delete data, return exactly {NO_QUERY} instead.\n\n"
        f"Today's date: {today.isoformat()}\n\n"
        f"Schema:\n{schema_text(role)}\n\nMetrics:\n{metrics_text(role)}\n\n"
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