"""How answers and errors are shown: labels, numbers, the big-number card and status messages."""

DECLINE_PREFIX = "I can only answer"          # start of the backend's NO_QUERY reply
NO_DATA_ANSWERS = ("No matching data was found.", "The query returned no rows.")


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def pretty_label(name):
    """region_name -> Region name"""
    text = str(name).replace("_", " ").strip()
    return text[:1].upper() + text[1:]


def format_number(v):
    """Thousands separators; whole numbers without decimals; others with two."""
    if v is None:
        return "—"
    if not _is_number(v):
        return str(v)
    if float(v).is_integer():
        return f"{int(v):,}"
    return f"{v:,.2f}"


def single_value(columns, rows):
    """(label, value) for a one-row result with one number, optionally named by one text value."""
    if len(rows) != 1:
        return None
    row = rows[0]
    numbers = [i for i, v in enumerate(row) if _is_number(v)]
    texts = [i for i, v in enumerate(row) if isinstance(v, str)]
    if len(numbers) != 1 or len(numbers) + len(texts) != len(row) or len(texts) > 1:
        return None
    label = pretty_label(columns[numbers[0]])
    if texts:
        label = f"{label} · {row[texts[0]]}"
    return label, format_number(row[numbers[0]])


def is_declined(msg):
    return not msg.get("sql") and not msg.get("rows") and str(msg.get("answer", "")).startswith(DECLINE_PREFIX)


def is_no_data(msg):
    return bool(msg.get("sql")) and not msg.get("rows") and msg.get("answer") in NO_DATA_ANSWERS


def status_for(error):
    """A friendly status for a BackendError: kind (st.info, st.warning or st.error), icon and text."""
    text, status = str(error), getattr(error, "status_code", None)
    if status == 422:
        broad = "too broad" in text or "too large" in text
        return {"kind": "warning", "icon": "🔍" if broad else "🛡️", "text": text}
    if status == 403:
        return {"kind": "error", "icon": "🔒", "text": text}
    if status == 401:
        return {"kind": "info", "icon": "🔑", "text": text}
    if status == 429:
        return {"kind": "warning", "icon": "⏳", "text": text}
    if status == 504:
        return {"kind": "warning", "icon": "⏱️", "text": text}
    return {"kind": "error", "icon": "⚠️", "text": text}



# ---- D3: sources and "How I answered" --------------------------------------------------------------

DOC_TYPES = {"sql_example": "SQL example", "data_quality": "data quality note", "metric": "metric",
             "rule": "rule", "dashboard": "dashboard", "document": "document"}
STEPS = {
    "route": "Understood the question and chose the agents",
    "rewrite": "Rewrote the follow-up as a standalone question",
    "find_knowledge": "Looked up business definitions, rules and example queries",
    "catalog_answer": "Answered from the data catalog",
    "write_sql": "Wrote the SQL query",
    "second_opinion": "Took a second look before declining",
    "check_sql": "Checked the query against the safety rules",
    "execute": "Ran the query on a read-only login",
    "declined": "Declined: not a question about the data",
    "explain": "Drafted the answer",
    "ground": "Checked every number against the result",
    "no_rows": "Reported that no data matched",
    "draw": "Chose a chart for the result",
    "redraw": "Redrew the last result",
    "explain_knowledge": "Answered from the business documents",
    "check_citations": "Checked that the answer cites the documents and adds no numbers",
}


def source_line(sources):
    """One line naming each knowledge document the answer used, or None."""
    seen, parts = set(), []
    for s in sources or []:
        if s["document_id"] in seen:
            continue
        seen.add(s["document_id"])
        parts.append(f"{s['title']} ({DOC_TYPES.get(s['doc_type'], s['doc_type'])}, v{s['version']})")
    return "Sources: " + " · ".join(parts) if parts else None


def _seconds(ms):
    return f"{ms / 1000:.1f} s"


def trace_lines(trace):
    """(agent, what it did, time) for each step the agents took, in order."""
    return [(t["agent"], STEPS.get(t["step"], pretty_label(t["step"])), _seconds(t["ms"]) if "ms" in t else "")
            for t in trace or []]


def total_seconds(trace):
    return _seconds(sum(t.get("ms", 0) for t in trace)) if trace else ""
