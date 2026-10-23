"""Metric rules on generated SQL (GR-ACC-01, GR-ACC-02), defined in backend/catalog/rules.toml.

Columns are resolved to tables through the query's aliases; an unqualified column is resolved
through the catalog when exactly one table in the query has it. Columns of a CTE are traced back
only by name, so a rule about order_items.line_total also catches SUM(line_total) over a CTE.
"""
from sqlglot import exp

from app import catalog

AGGREGATES = (exp.Sum, exp.Avg)


def _aliases(tree, ctes):
    """alias or table name -> table name, for real tables in the whole query."""
    return {t.alias_or_name.lower(): t.name.lower() for t in tree.find_all(exp.Table)
            if t.name and not (t.name in ctes and not t.db)}


def _resolve(col, aliases, scope):
    """The (table, column) a column reference means, or (None, name) if it cannot be told."""
    name = col.name.lower()
    if col.table:
        return aliases.get(col.table.lower()), name
    described = catalog.get().tables
    owners = [t for t in scope if t in described and name in described[t].columns]
    return (owners[0], name) if len(owners) == 1 else (None, name)


def _select_tables(select, aliases):
    """Real tables in one SELECT's own FROM and JOINs (not in its subqueries)."""
    sources = [select.args.get("from")] + list(select.args.get("joins") or [])
    found = set()
    for src in sources:
        if src is not None and isinstance(src.this, exp.Table) and src.this.name:
            found.add(aliases.get(src.this.alias_or_name.lower(), src.this.name.lower()))
    return found


def check(tree, rules, ctes, rejected):
    """Raise `rejected(message)` for the first rule the query breaks."""
    if not rules:
        return
    aliases = _aliases(tree, ctes)
    scope = set(aliases.values())
    resolved = [(_resolve(c, aliases, scope), c) for c in tree.find_all(exp.Column)]
    has_aggregate = any(True for _ in tree.find_all(*AGGREGATES))
    cte_names = {c.lower() for c in ctes}

    for rule in rules:
        targets = set(rule.columns)
        names = {c for _, c in targets}
        if rule.kind == "requires_filter" and has_aggregate:
            uses = any(ref in targets or (ref[0] is None and ref[1] in names
                                          and (col.table or "").lower() in cte_names | {""})
                       for ref, col in resolved)
            filtered = any(ref == rule.filter_on for ref, _ in resolved)
            if uses and not filtered:
                raise rejected(f"{rule.id}: {rule.message}")
        if rule.kind == "no_fanout":
            for select in tree.find_all(exp.Select):
                if rule.child_table not in _select_tables(select, aliases):
                    continue
                for agg in select.find_all(*AGGREGATES):
                    if agg.find_ancestor(exp.Select) is not select:
                        continue
                    for col in agg.find_all(exp.Column):
                        if _resolve(col, aliases, scope) in targets:
                            raise rejected(f"{rule.id}: {rule.message}")
