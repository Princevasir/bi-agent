import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from app import limits, policy
from app.bi.schema import ALLOWED_TABLES
from app.sqltypes import ValidatedSQL

# GR-SQL-01: functions are allowed only if the policy file lists them (GR-POL-01).
# Typed functions are matched by sqlglot's node class name, unknown ones (Anonymous) by their SQL name.
ALLOWED_FUNCTION_TYPES = policy.get().allowed_function_types
ALLOWED_FUNCTION_NAMES = policy.get().allowed_function_names
# Second check behind the allowlist.
BLOCKED_PREFIXES = policy.get().blocked_prefixes

WRITE_NODES = tuple(getattr(exp, n) for n in (
    "Insert", "Update", "Delete", "Merge", "Create", "Drop", "Alter", "Command", "Copy", "Into",
) if hasattr(exp, n))
SET_OPERATIONS = (exp.Union, exp.Intersect, exp.Except)
COMPARISONS = (exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE)
PERSONAL_DATA_MESSAGE = ("You don't have access to personal data such as names, email addresses, phone numbers, "
                         "street addresses or salaries.")
TOO_BROAD_MESSAGE = ("The generated query was too broad to run safely. "
                     "Try a more specific question, for example a shorter period or one grouping.")


class SQLRejected(Exception):
    """Raised for SQL that must not run. user_message, when set, is safe to show the user."""

    def __init__(self, reason, user_message=None):
        super().__init__(reason)
        self.user_message = user_message


def _too_broad(reason):
    return SQLRejected(reason, TOO_BROAD_MESSAGE)


def _function_name(f):
    return f.name.lower() if isinstance(f, exp.Anonymous) else type(f).__name__


def _check_functions(tree):
    for f in tree.find_all(exp.Func):
        if isinstance(f, (exp.Connector, exp.Binary)):
            continue   # AND, OR and operators are parsed as functions; they are not calls
        if _function_name(f).lower().startswith(BLOCKED_PREFIXES):
            raise SQLRejected(f"Function not permitted: {_function_name(f)}")
        if isinstance(f.parent, exp.Dot):
            raise SQLRejected("Schema-qualified functions are not allowed.")
        allowed = (f.name.lower() in ALLOWED_FUNCTION_NAMES if isinstance(f, exp.Anonymous)
                   else type(f).__name__ in ALLOWED_FUNCTION_TYPES)
        if not allowed:
            raise SQLRejected(f"Function not permitted: {_function_name(f)}")


def _is_one_row(source, ctes):
    """A source that returns exactly one row: an aggregate with no GROUP BY, directly or via a CTE."""
    if isinstance(source, exp.Table) and source.name in ctes and not source.db:
        source = ctes[source.name]
    inner = source.this if isinstance(source, (exp.Subquery, exp.CTE)) else None
    return (isinstance(inner, exp.Select) and not inner.args.get("group")
            and any(isinstance(e.unalias(), exp.AggFunc) for e in inner.expressions))


def _links(condition, alias):
    """True if the condition compares a column of `alias` (or an unqualified column) with another column."""
    if condition is None:
        return False
    for cmp in condition.find_all(*COMPARISONS):
        left, right = list(cmp.left.find_all(exp.Column)), list(cmp.right.find_all(exp.Column))
        if not left or not right:
            continue
        qualifiers = {c.table for c in left + right}
        if "" in qualifiers or (alias in qualifiers and len(qualifiers) > 1):
            return True
    return False


def _check_structure(tree):
    ctes = {c.alias: c for c in tree.find_all(exp.CTE)}
    for select in tree.find_all(exp.Select):
        for join in select.args.get("joins") or []:
            if join.args.get("using") or join.args.get("method") == "NATURAL":
                continue
            if _is_one_row(join.this, ctes):
                continue
            alias = join.this.alias_or_name
            condition = join.args.get("on")
            if condition is None and join.args.get("kind") != "CROSS":
                condition = select.args.get("where") and select.args["where"].this
            if not _links(condition, alias):
                raise _too_broad(f"Join without a join condition: {alias}")
        depth = sum(1 for _ in _select_ancestors(select))
        if depth > limits.sql_max_depth():
            raise _too_broad(f"Subqueries nested {depth} deep")
    tables = sum(1 for t in tree.find_all(exp.Table) if not (t.name in ctes and not t.db))
    if tables > limits.sql_max_tables():
        raise _too_broad(f"{tables} table references")


def _select_ancestors(node):
    parent = node.parent
    while parent is not None:
        if isinstance(parent, exp.Select):
            yield parent
        parent = parent.parent


def _check_columns(tree, ctes, denied):
    """GR-SQL-05: no column the role may not read, by name or through *, in any part of the query."""
    tables = {t.name.lower() for t in tree.find_all(exp.Table) if not (t.name in ctes and not t.db)}
    restricted = {c for t, c in denied if t in tables}
    if not restricted:
        return
    for col in tree.find_all(exp.Column):
        if col.name.lower() in restricted:
            raise SQLRejected(f"Personal data column: {col.name}", PERSONAL_DATA_MESSAGE)
    star_tables = {t for t, _ in denied if t in tables}
    for select in tree.find_all(exp.Select):
        for e in select.expressions:
            if isinstance(e, exp.Star) or (isinstance(e, exp.Column) and isinstance(e.this, exp.Star)):
                raise SQLRejected(f"SELECT * over tables with personal data: {', '.join(sorted(star_tables))}",
                                  PERSONAL_DATA_MESSAGE)


def validate_sql(sql: str, allowed_tables = ALLOWED_TABLES, denied_columns=frozenset()) -> ValidatedSQL:
    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except SqlglotError as e:
        raise SQLRejected("The SQL could not be parsed.") from e
    if len(statements) != 1:
        raise SQLRejected("Exactly one statement is allowed.")
    tree = statements[0]
    if not isinstance(tree, (exp.Select, *SET_OPERATIONS)):
        raise SQLRejected("Only SELECT statements are allowed.")
    if tree.find(*WRITE_NODES):
        raise SQLRejected("Only read-only SELECT statements are allowed.")
    if any(s.args.get("locks") for s in tree.find_all(exp.Select)):
        raise SQLRejected("SELECT INTO and locking clauses are not allowed.")
    ctes = {c.alias for c in tree.find_all(exp.CTE)}
    for t in tree.find_all(exp.Table):
        if isinstance(t.this, exp.Func) or not t.name:
            raise SQLRejected("Table functions are not allowed.")
        if t.name in ctes and not t.db:
            continue
        if t.db or t.catalog:
            raise SQLRejected("Schema-qualified tables are not allowed.")
        if t.name.lower() not in allowed_tables:
            raise SQLRejected(f"Table not permitted: {t.name}")
    _check_functions(tree)
    _check_structure(tree)
    _check_columns(tree, ctes, denied_columns)
    return ValidatedSQL(tree.sql(dialect="postgres"))
