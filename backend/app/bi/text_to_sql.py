import re
from datetime import date

from app.bi.schema import metrics_text, schema_text

FENCE = re.compile(r"```(?:sql)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def build_prompt(question: str, today: date) -> str:
    return (
        "You write PostgreSQL for a BI tool. Return exactly one SELECT statement "
        "and nothing else. Use only the tables and columns listed below. "
        "Prefer the metric definitions. Use explicit date ranges.\n\n"
        f"Today's date: {today.isoformat()}\n\n"
        f"Schema:\n{schema_text()}\n\nMetrics:\n{metrics_text()}\n\n"
        f"Question: {question}\nSQL:"
    )


def extract_sql(text: str) -> str:
    m = FENCE.search(text)
    return (m.group(1) if m else text).strip()


def generate_sql(question: str, generate, today: date) -> str:
    return extract_sql(generate(build_prompt(question, today)))