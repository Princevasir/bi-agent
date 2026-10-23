"""Questions about the data itself (M29c), answered from the role's catalog without the model or SQL.

"What tables do I have?", "Describe the orders table", "What does line_total mean?" and "Which metrics
are defined?" are recognised by fixed patterns. A table or column the role cannot see is answered
exactly like one that does not exist, so hidden tables are never revealed.
"""
import re

from app import catalog

LIST_TABLES = [r"\b(list|show|what|which|all|available)\b.*\btables\b", r"\btables?\b.*\b(have|access|available)\b",
               r"\bwhat (data|information) (do|can) i\b", r"\bwhat can i (ask|query|see)\b"]
DESCRIBE = r"\b(describe|tell me about|what('s| is) in|columns?|fields?|structure|schema|details)\b"
METRICS = [r"\b(which|what|list|show)\b.*\bmetrics?\b",
           r"\bhow (is|are) (\w+ ){1,3}(defined|calculated|computed|measured)\b", r"\bdefinition of\b"]
EXPLAIN = [r"\bwhat (does|do) (the )?(?P<x>[a-z_ ]+?)( column| field)? mean\b",
           r"^\s*what is (the )?(?P<x>[a-z_ ]+?)( column| field)?\s*\??\s*$"]
SAMPLE_TABLES = {"orders": ["id", "order_date", "region_id", "status", "amount"], "regions": ["id", "name"]}


def _known():
    """Every table and column name we could be asked about (from the files, no database)."""
    names = {t.name: list(t.columns) for t in catalog.get().tables.values()}
    for table, columns in SAMPLE_TABLES.items():
        names.setdefault(table, columns)
    return names


def _names(cat):
    return {name: [c["name"] for c in t["columns"]] for name, t in (cat or {}).items()}


def _forms(name):
    spaced = name.replace("_", " ")
    singular = spaced[:-1] if spaced.endswith("s") else spaced
    return {spaced, singular}


def _mentioned_table(text, tables):
    for name in sorted(tables, key=len, reverse=True):          # order_items before orders
        if any(re.search(rf"\b{re.escape(f)}\b", text) for f in _forms(name)):
            return name
    return None


def catalog_question(text, cat):
    """(intent, subject) for a question about the data, or None for a question for the model."""
    text = str(text).lower().strip()
    names = {**_known(), **_names(cat)}
    if any(re.search(p, text) for p in METRICS):
        return "metrics", None
    table = _mentioned_table(text, names)
    if table and (re.search(DESCRIBE, text) or re.search(rf"\b({'|'.join(map(re.escape, _forms(table)))}) table\b", text)):
        return "describe_table", table
    for pattern in EXPLAIN:
        m = re.search(pattern, text)
        if m:
            column = m.group("x").strip().replace(" ", "_")
            if any(column in cols for cols in names.values()):
                return "explain_column", column
    if any(re.search(p, text) for p in LIST_TABLES):
        return "list_tables", None
    return None


def _result(columns, rows, text):
    return {"sql": "", "columns": columns, "rows": rows, "truncated": False, "answer": text,
            "answer_source": "catalog", "chart": None, "chart_note": None, "sql_repairs": 0}


def _describe_column(c):
    text = c["description"]
    if c.get("values"):
        text += f" Values: {', '.join(c['values'])}."
    if c.get("unit"):
        text += f" ({c['unit']})"
    return text.strip()


def answer(intent, cat, metrics):
    kind, subject = intent
    if kind == "list_tables":
        order = list(catalog.DOMAINS) + ["Sample data"]
        tables = sorted(cat.values(), key=lambda t: (order.index(t["domain"]) if t["domain"] in order else 99,
                                                     t["name"]))
        rows = [[t["name"], t["domain"], t["description"], t["rows"]] for t in tables]
        areas = len({t["domain"] for t in tables})
        return _result(["table", "business_area", "description", "rows"], rows,
                       f"You can query {len(rows)} tables in {areas} business area{'s' if areas != 1 else ''}. "
                       'Ask "Describe the <table> table" to see its columns.')
    if kind == "describe_table":
        t = cat.get(subject)
        if t is None:
            return _result([], [], f"There is no table called {subject} that you can access. "
                                   'Ask "What tables do I have access to?" to see them.')
        rows = []
        for c in t["columns"]:
            key = "PK" if c["primary_key"] else (f"FK → {c['references']}" if c.get("references") else "")
            rows.append([c["name"], c["type"], key, _describe_column(c)])
        text = f"{t['name']}: {t['description']} {t['grain']}".strip()
        if t["primary_key"]:
            text += f" Primary key: {', '.join(t['primary_key'])}."
        if t["caveats"]:
            text += " Watch out: " + " ".join(t["caveats"])
        return _result(["column", "type", "key", "description"], rows, text)
    if kind == "explain_column":
        rows = [[t["name"], c["name"], c["type"], _describe_column(c)]
                for t in cat.values() for c in t["columns"] if c["name"] == subject]
        if not rows:
            return _result([], [], f"There is no column called {subject} that you can access.")
        return _result(["table", "column", "type", "description"], rows, f"{subject}: {rows[0][3]}")
    rows = [[m["name"], m["definition"], m["description"]] for m in metrics]
    return _result(["metric", "definition", "description"], rows,
                   f"{len(rows)} governed metric{'s are' if len(rows) != 1 else ' is'} defined for your data.")
