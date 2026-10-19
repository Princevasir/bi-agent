import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from app.bi.schema import ALLOWED_TABLES

BLOCKED_PREFIXES = ("pg_", "lo_", "dblink", "set_config", "current_setting")


class SQLRejected(Exception):
    pass


def validate_sql(sql: str) -> str:
    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except SqlglotError as e:
        raise SQLRejected("The SQL could not be parsed.") from e
    if len(statements) != 1:
        raise SQLRejected("Exactly one statement is allowed.")
    tree = statements[0]
    if not isinstance(tree, exp.Select):
        raise SQLRejected("Only SELECT statements are allowed.")
    if tree.find(exp.Into) or tree.args.get("locks"):
        raise SQLRejected("SELECT INTO and locking clauses are not allowed.")
    ctes = {c.alias for c in tree.find_all(exp.CTE)}
    for t in tree.find_all(exp.Table):
        if t.name in ctes and not t.db:
            continue
        if t.db or t.catalog:
            raise SQLRejected("Schema-qualified tables are not allowed.")
        if t.name.lower() not in ALLOWED_TABLES:
            raise SQLRejected(f"Table not permitted: {t.name}")
    for f in tree.find_all(exp.Anonymous):
        if f.name.lower().startswith(BLOCKED_PREFIXES):
            raise SQLRejected(f"Function not permitted: {f.name}")
    return tree.sql(dialect="postgres")