"""Chart rules (F1b): the result's shape decides which charts fit. The model never picks a chart.

build_chart_spec returns the suggested type first in "options", the other types that fit after
it, and the columns each chart needs (x, y, series, values, size, location, start, end).
"""
import re
from itertools import pairwise

DATE_LIKE = re.compile(r"^\d{4}-\d{2}(-\d{2})?([T ]\d{2}:\d{2}:\d{2}(\.\d+)?([+-]\d{2}:?\d{2}|Z)?)?$")
MAX_CHART_ROWS = 50        # category and time charts
MAX_POINT_ROWS = 200       # scatter, bubble and distributions can show more points
MIN_DISTRIBUTION_ROWS = 10
MAX_PIE_PARTS = 8
MAX_RADAR_ROWS = 12
STAGE_NAME = re.compile(r"stage|step|funnel", re.IGNORECASE)


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _kind(name, values):
    present = [v for v in values if v is not None]
    if not present:
        return None
    if all(_is_number(v) for v in present):
        if "year" in name.lower() and all(float(v).is_integer() and 1900 <= v <= 2100 for v in present):
            return "time"
        return "number"
    if all(isinstance(v, str) for v in present):
        if all(DATE_LIKE.match(v) for v in present):
            return "time"
        return "country" if "country" in name.lower() else "text"
    return None


def _category_options(values, time=False, label=""):
    options = ["line", "area", "bar"] if time else ["bar"]
    nonneg = all(v is None or v >= 0 for v in values)
    if not time and nonneg and 2 <= len(values) <= MAX_PIE_PARTS:
        options += ["pie", "donut"]
    if not time and all(v is not None and v > 0 for v in values):
        options.append("treemap")
    falling = all(a >= b for a, b in pairwise(values) if a is not None and b is not None)
    if not time and nonneg and falling and STAGE_NAME.search(label) and len(values) <= MAX_PIE_PARTS:
        options.append("funnel")
    if any(v is not None and v < 0 for v in values):
        options.append("waterfall")
    return options


def _spec(options, **columns):
    return {"type": options[0], "options": options, **columns}


def build_chart_spec(columns, rows):
    n = len(rows)
    if n < 2 or not columns:
        return None
    kinds = [_kind(c, [r[i] for r in rows]) for i, c in enumerate(columns)]
    if None in kinds:
        return None
    numbers = [c for c, k in zip(columns, kinds) if k == "number"]
    small = n <= MAX_CHART_ROWS

    if len(columns) == 1:
        if kinds == ["number"] and MIN_DISTRIBUTION_ROWS <= n <= MAX_POINT_ROWS:
            return _spec(["histogram", "box"], y=columns[0])
        return None

    if len(columns) == 2:
        (a, b), (ka, kb) = columns, kinds
        values = [r[1] for r in rows]
        if kb != "number":
            return None
        if ka == "country" and small:
            return _spec(["map", "bar"], x=a, y=b, location=a)
        if ka == "time" and small:
            return _spec(_category_options(values, time=True), x=a, y=b)
        if ka == "text" and small:
            return _spec(_category_options(values, label=a), x=a, y=b)
        if ka == "number" and n <= MAX_POINT_ROWS:
            return _spec(["scatter"], x=a, y=b)
        return None

    if len(columns) == 3:
        (a, b, c), (ka, kb, kc) = columns, kinds
        if ka == "text" and kb == kc == "time" and small:
            return _spec(["gantt"], x=a, start=b, end=c)
        if sorted((ka, kb)) in (["text", "time"], ["country", "time"]) and kc == "number" and small:
            time_col, cat_col = (a, b) if ka == "time" else (b, a)
            return _spec(["line", "area", "stacked_bar"], x=time_col, series=cat_col, y=c)
        if ka in ("text", "country") and kb in ("text", "country") and kc == "number" and small:
            return _spec(["stacked_bar", "grouped_bar", "heatmap", "treemap", "sankey"], x=a, series=b, y=c)
        if kinds == ["number"] * 3 and n <= MAX_POINT_ROWS:
            return _spec(["bubble", "scatter"], x=a, y=b, size=c)
        if ka in ("text", "country") and kb == kc == "number" and small:
            return _spec(["grouped_bar", "scatter"], x=a, values=[b, c])   # scatter: b against c, labelled by a

    first, rest = kinds[0], kinds[1:]
    if first in ("text", "country") and len(rest) >= 3 and all(k == "number" for k in rest) and n <= MAX_RADAR_ROWS:
        return _spec(["grouped_bar", "radar"], x=columns[0], values=numbers)
    return None
