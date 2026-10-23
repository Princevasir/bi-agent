from functools import lru_cache

from app import catalog
from app.access import ROLE_TABLES, data_source, denied_columns, tables_for, uses_catalog
from app.bi.metrics import METRICS
from app.db import TrustedSQL, run_readonly

ALLOWED_TABLES = ROLE_TABLES["analyst"]
INTROSPECTION_ROWS = 2000


def get_schema(role="analyst"):
    """Columns and types of the role's tables, as the role's own login sees them."""
    result = run_readonly(TrustedSQL(
        "SELECT table_name, column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = ANY(%s) "
        "ORDER BY table_name, ordinal_position"),
        (list(tables_for(role)),),
        role=role, max_rows=INTROSPECTION_ROWS,
    )
    denied = denied_columns(role)
    schema = {}
    for table, column, dtype in result["rows"]:
        if (table, column) not in denied:
            schema.setdefault(table, []).append({"column": column, "type": dtype})
    return schema


def _introspect(role):
    def run(sql, params=None):
        return run_readonly(TrustedSQL(sql), params, role=role, max_rows=INTROSPECTION_ROWS)["rows"]
    return catalog.introspect(run)


def _short(dtype):
    return {"timestamp without time zone": "timestamp", "character varying": "text", "character": "text",
            "double precision": "float"}.get(dtype, dtype)


@lru_cache(maxsize=16)
def _catalog_text(source, role):
    """The prompt's description of the role's tables (M29b): meaning, grain, readable columns with
    types and allowed values, joins from the database's foreign keys, and the catalog's caveats."""
    cat, db, denied = catalog.get(), _introspect(role), denied_columns(role)
    allowed = set(tables_for(role))
    blocks = []
    for name in tables_for(role):
        table, live = cat.tables.get(name), db.get(name)
        if table is None or live is None:
            continue
        cols = []
        for column, dtype in live["columns"].items():
            if (name, column) in denied or column not in table.columns:
                continue
            c = table.columns[column]
            extra = f" [{', '.join(c.values)}]" if c.values else ""
            unit = f" ({c.unit})" if c.unit else ""
            cols.append(f"{column} {_short(dtype)}{extra}: {c.description}{unit}")
        joins = [f"{col} -> {ref}.{ref_col}" for col, ref, ref_col in live["foreign_keys"] if ref in allowed]
        lines = [f"{name}: {table.description} {table.grain}"]
        if live["primary_key"]:
            lines.append(f"  key: {', '.join(live['primary_key'])}")
        lines += [f"  - {c}" for c in cols]
        if joins:
            lines.append(f"  joins: {'; '.join(joins)}")
        lines += [f"  note: {c}" for c in table.caveats]
        blocks.append("\n".join(lines))
    return "\n".join(blocks)


def schema_text(role="analyst"):
    if uses_catalog():
        return _catalog_text(data_source(), role)
    return "\n".join(
        f"{t}({', '.join(c['column'] + ' ' + c['type'] for c in cols)})"
        for t, cols in get_schema(role).items()
    )


def metrics_text(role="analyst"):
    if uses_catalog():
        allowed = set(tables_for(role))
        return "\n".join(
            f"- {m.name}: {m.description} = {m.expression}"
            + (f" WHERE {' AND '.join(m.filters)}" if m.filters else "") + f" (tables: {', '.join(m.tables)})"
            for m in catalog.get().metrics.values() if set(m.tables) <= allowed)
    if "orders" not in tables_for(role):
        return ""
    return "\n".join(
        f"- {m.name}: {m.description}; {m.expression} over orders o WHERE {m.base_where}"
        for m in METRICS.values()
    )


def hints_text():
    """SQL tips from the catalog (retail only): how to group by quarter or month, prefix shared names."""
    if not uses_catalog():
        return ""
    return "\n".join(f"- {h}" for h in catalog.get().hints)


def clear_cache():
    _catalog_text.cache_clear()
