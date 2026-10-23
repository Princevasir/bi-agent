from app.bi.metrics import METRICS
from app.db import TrustedSQL, run_readonly

from app.access import ROLE_TABLES, tables_for

ALLOWED_TABLES = ROLE_TABLES["analyst"]


def get_schema(role="analyst"):
    result = run_readonly(TrustedSQL(
        "SELECT table_name, column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = ANY(%s) "
        "ORDER BY table_name, ordinal_position"),
        (list(tables_for(role)),),
        role=role,
    )
    schema = {}
    for table, column, dtype in result["rows"]:
        schema.setdefault(table, []).append({"column": column, "type": dtype})
    return schema


def schema_text(role="analyst"):
    return "\n".join(
        f"{t}({', '.join(c['column'] + ' ' + c['type'] for c in cols)})"
        for t, cols in get_schema(role).items()
    )


def metrics_text(role="analyst"):
    if "orders" not in tables_for(role):
        return ""
    return "\n".join(
        f"- {m.name}: {m.description}; {m.expression} over orders o WHERE {m.base_where}"
        for m in METRICS.values()
    )