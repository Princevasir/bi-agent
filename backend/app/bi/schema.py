from app.bi.metrics import METRICS
from app.db import run_readonly

ALLOWED_TABLES = ("orders", "regions")


def get_schema():
    result = run_readonly(
        "SELECT table_name, column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = ANY(%s) "
        "ORDER BY table_name, ordinal_position",
        (list(ALLOWED_TABLES),),
    )
    schema = {}
    for table, column, dtype in result["rows"]:
        schema.setdefault(table, []).append({"column": column, "type": dtype})
    return schema


def schema_text():
    return "\n".join(
        f"{t}({', '.join(c['column'] + ' ' + c['type'] for c in cols)})"
        for t, cols in get_schema().items()
    )


def metrics_text():
    return "\n".join(
        f"- {m.name}: {m.description}; {m.expression} over orders o WHERE {m.base_where}"
        for m in METRICS.values()
    )