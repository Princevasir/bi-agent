import re

NUM = re.compile(r"\d[\d,]*\.?\d*")


def _numbers(text):
    out = set()
    for m in NUM.findall(text):
        try:
            out.add(round(float(m.replace(",", "").rstrip(".")), 2))
        except ValueError:
            pass
    return out


def is_grounded(answer, question, rows):
    allowed = _numbers(question)
    for row in rows:
        for v in row:
            if isinstance(v, (int, float)):
                allowed.add(round(float(v), 2))
    return _numbers(answer) <= allowed


def fallback_answer(columns, rows):
    if not rows:
        return "The query returned no rows."
    return "; ".join(
        ", ".join(f"{c}: {v}" for c, v in zip(columns, r)) for r in rows[:10]
    )


def answer_prompt(question, sql, result):
    return (
        "Answer the question in one or two sentences using ONLY the data below. "
        "Do not use any number that is not in the data.\n\n"
        f"Question: {question}\nSQL: {sql}\nColumns: {result['columns']}\n"
        f"Rows: {result['rows'][:50]}\nTruncated: {result['truncated']}"
    )