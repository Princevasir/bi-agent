"""Small-group protection (GR-PRIV-03): an aggregate result never describes fewer than k customers.

A total over a tiny group can reveal one person ("average spend of Platinum customers in Boulder"
with one such customer is that customer's spend). When a generated query aggregates data from a
table that holds customer_id, the code adds COUNT(DISTINCT <table>.customer_id) to it; the query
is validated again and run, rows under the minimum are removed, and the helper column is dropped.
Queries with CTEs, set operations or window functions are left as they are (a residual risk).
"""
from functools import lru_cache

import sqlglot
from sqlglot import exp

HELPER = "bi_group_customers"


@lru_cache(maxsize=1)
def _customer_tables():
    from app import catalog
    return frozenset(t.name for t in catalog.get().tables.values() if "customer_id" in t.columns)


def with_customer_count(sql):
    """The query with a per-group customer count added, or None when the check does not apply."""
    try:
        tree = sqlglot.parse_one(sql, read="postgres")
    except sqlglot.errors.ParseError:
        return None
    if not isinstance(tree, exp.Select) or tree.args.get("with") or tree.find(exp.Window):
        return None
    aggregated = tree.args.get("group") or any(e.find(exp.AggFunc) for e in tree.expressions)
    if not aggregated:
        return None
    tables = [t for t in tree.find_all(exp.Table) if t.parent_select is tree and t.name in _customer_tables()]
    if not tables:
        return None
    table = next((t for t in tables if t.name == "customers"), tables[0])
    qualifier = table.alias or table.name
    counted = tree.copy()
    counted.select(f"COUNT(DISTINCT {qualifier}.customer_id) AS {HELPER}", copy=False)
    return counted.sql(dialect="postgres")


def suppress_small_groups(columns, rows, minimum):
    """(columns without the helper, rows covering at least `minimum` customers, how many were removed)."""
    if HELPER not in columns:
        return columns, rows, 0
    i = columns.index(HELPER)
    # 0 customers (guest orders only) cannot single anyone out; 1 to minimum-1 can
    kept = [r[:i] + r[i + 1:] for r in rows if not 0 < (r[i] or 0) < minimum]
    return columns[:i] + columns[i + 1:], kept, len(rows) - len(kept)
