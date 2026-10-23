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
# Whole numbers that name a period, like EXTRACT(QUARTER ...), are categories, not measurements.
PERIODS = [(re.compile(r"quarter|\bqtr\b"), 1, 4), (re.compile(r"month"), 1, 12), (re.compile(r"week(?!day)"), 1, 53),
           (re.compile(r"weekday|day_of_week|dow"), 0, 7), (re.compile(r"hour"), 0, 23), (re.compile(r"day"), 1, 31)]


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _kind(name, values):
    present = [v for v in values if v is not None]
    if not present:
        return None
    if all(_is_number(v) for v in present):
        whole = all(float(v).is_integer() for v in present)
        if whole and "year" in name.lower() and all(1900 <= v <= 2100 for v in present):
            return "time"
        for pattern, low, high in PERIODS:
            if whole and pattern.search(name.lower()) and all(low <= v <= high for v in present):
                return "period"
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
    # A period only labels things; a period-like value column (lead_time_days) is a measurement.
    kinds = [k if k != "period" or i == 0 else "number" for i, k in enumerate(kinds)]
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
        if ka == "period" and small:
            options = _category_options(values, label=a)
            return _spec(options[:1] + ["line", "area"] + options[1:], x=a, y=b)
        if ka == "number" and n <= MAX_POINT_ROWS:
            return _spec(["scatter"], x=a, y=b)
        return None

    if len(columns) == 3:
        (a, b, c), (ka, kb, kc) = columns, kinds
        if ka == "text" and kb == kc == "time" and small:
            return _spec(["gantt"], x=a, start=b, end=c)
        if ka == "period" and kb in ("text", "country") and kc == "number" and small:
            return _spec(["line", "area", "stacked_bar"], x=a, series=b, y=c)
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



# ---- F1c: chart types named by the user ---------------------------------------------------------
# A fixed word list, never the model. Order matters: "stacked area" is an area chart, "stacked bar" a
# stacked bar, "bubble" before "scatter". Whole words only, so "online" is not "line".
REQUESTS = [
    ("donut", r"\b(donut|doughnut)\b"), ("pie", r"\bpie\b"), ("treemap", r"\btree ?map\b"),
    ("funnel", r"\bfunnel\b"), ("waterfall", r"\bwaterfall\b"), ("heatmap", r"\bheat ?map\b"),
    ("sankey", r"\bsankey\b"), ("radar", r"\b(radar|spider)\b"), ("bubble", r"\bbubble\b"),
    ("scatter", r"\bscatter\b"), ("histogram", r"\bhistogram\b"),
    ("box", r"\bbox ?plot\b|\bbox and whisker\b"), ("gantt", r"\bgantt\b|\btimeline chart\b"),
    ("map", r"\bchoropleth\b|\bon a map\b|\bas a map\b|\bmap chart\b|\bworld map\b"),
    ("area", r"\barea (chart|graph|plot)\b|\bas an area\b"), ("stacked_bar", r"\bstacked\b"),
    ("grouped_bar", r"\b(grouped|clustered|side[- ]by[- ]side)\b"),
    ("line", r"\bline (chart|graph|plot)\b|\bas a line\b|\bas lines\b"),
    ("bar", r"\b(bar|column) (chart|graph|plot)s?\b|\bas (a )?bars?\b|\bas columns\b"),
]
NAMES = {
    "bar": "bar chart", "pie": "pie chart", "donut": "donut chart", "treemap": "treemap", "funnel": "funnel chart",
    "waterfall": "waterfall chart", "line": "line chart", "area": "area chart", "stacked_bar": "stacked bar chart",
    "grouped_bar": "grouped bar chart", "heatmap": "heatmap", "sankey": "Sankey diagram", "radar": "radar chart",
    "scatter": "scatter plot", "bubble": "bubble chart", "histogram": "histogram", "box": "box plot",
    "map": "map", "gantt": "Gantt chart",
}
NEEDS = {
    "bar": "one category and one number", "pie": "one category and one number, 2 to 8 parts, no negative values",
    "donut": "one category and one number, 2 to 8 parts, no negative values",
    "treemap": "categories with positive numbers", "funnel": "stages whose values only fall, such as visits, carts and orders",
    "waterfall": "step-by-step changes, including negative ones", "line": "dates, months or years along the bottom",
    "area": "dates, months or years along the bottom", "stacked_bar": "two categories and one number",
    "grouped_bar": "a category and two or more numbers, or two categories and one number",
    "heatmap": "two categories and one number", "sankey": "two categories and one number (from, to and amount)",
    "radar": "one category and at least three numbers", "scatter": "two numbers per row",
    "bubble": "three numbers per row", "histogram": "one number with at least 10 rows",
    "box": "one number with at least 10 rows", "map": "a country column and one number",
    "gantt": "a label with a start and an end date",
}
CHART_WORDS = {
    "pie", "donut", "doughnut", "treemap", "tree", "map", "funnel", "waterfall", "heatmap", "heat", "sankey",
    "radar", "spider", "bubble", "scatter", "histogram", "box", "boxplot", "whisker", "gantt", "timeline",
    "choropleth", "world", "area", "stacked", "grouped", "clustered", "side", "line", "lines", "bar", "bars",
    "column", "columns", "chart", "charts", "graph", "plot", "diagram",
}
FILLER = {
    "make", "it", "that", "this", "the", "show", "draw", "display", "turn", "change", "switch", "convert",
    "into", "to", "as", "in", "a", "an", "please", "instead", "can", "could", "you", "me", "use", "now",
    "same", "result", "results", "view", "visualise", "visualize", "with", "of", "type", "by", "and", "on",
    "try", "lets", "let's", "how", "about", "would", "like", "want", "i", "give",
}


def requested_chart(text):
    """The chart type the user named, or None."""
    lowered = str(text).lower()
    return next((kind for kind, pattern in REQUESTS if re.search(pattern, lowered)), None)


def is_chart_only(text):
    """True when the message asks only for a different chart, not for different data."""
    if requested_chart(text) is None:
        return False
    words = re.findall(r"[a-z']+", str(text).lower())
    return all(w in CHART_WORDS or w in FILLER for w in words)


def apply_request(spec, requested):
    """Use the requested chart if it fits the result; otherwise keep the suggestion and say why."""
    if requested is None:
        return spec, None
    if spec and requested in spec["options"]:
        options = [requested] + [o for o in spec["options"] if o != requested]
        return {**spec, "type": requested, "options": options}, None
    note = f"A {NAMES[requested]} doesn't fit this result: it needs {NEEDS[requested]}."
    if spec:
        note += f" Showing a {NAMES[spec['type']]} instead; other options are under Chart type."
    return spec, note
