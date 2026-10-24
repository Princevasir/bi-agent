import re

from app.prompt_safety import FENCE_NOTE, fence

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
    rows = f"columns: {result['columns']}\nrows: {result['rows'][:50]}\ntruncated: {result['truncated']}"
    return (
        "Answer the question in one or two sentences using ONLY the data below. "
        "Do not use any number that is not in the data. A chart is drawn automatically from the data; "
        "do not explain how to make one. "
        f"{FENCE_NOTE}\n\n"
        f"Question:\n{fence('question', question)}\nSQL:\n{fence('sql', sql)}\nResult:\n{fence('rows', rows)}"
    )
