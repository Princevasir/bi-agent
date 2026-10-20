import re

DATE_LIKE = re.compile(r"^\d{4}-\d{2}(-\d{2})?$")
MAX_CHART_ROWS = 50


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def build_chart_spec(columns, rows):
    if len(columns) != 2 or not 2 <= len(rows) <= MAX_CHART_ROWS:
        return None
    if not all(_is_number(r[1]) for r in rows):
        return None
    labels = [r[0] for r in rows]
    if any(_is_number(label) for label in labels):
        return None
    is_time = all(isinstance(label, str) and DATE_LIKE.match(label) for label in labels)
    return {"type": "line" if is_time else "bar", "x": columns[0], "y": columns[1]}