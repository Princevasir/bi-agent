import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from app.bi.schema import ALLOWED_TABLES
from app.sqltypes import ValidatedSQL

# GR-SQL-01: functions are allowed only if listed here; widening the list is a security decision.
# Typed functions are matched by sqlglot's node class name, unknown ones (Anonymous) by their SQL name.
ALLOWED_FUNCTION_TYPES = frozenset({
    # aggregates
    "Count", "Sum", "Avg", "Min", "Max", "Stddev", "StddevPop", "StddevSamp", "Variance", "VariancePop",
    "PercentileCont", "PercentileDisc", "ArrayAgg", "GroupConcat", "LogicalAnd", "LogicalOr",
    # window
    "RowNumber", "Rank", "DenseRank", "PercentRank", "CumeDist", "Ntile", "Lag", "Lead",
    "FirstValue", "LastValue", "NthValue",
    # conditional and casts
    "Case", "If", "Coalesce", "Nullif", "Greatest", "Least", "Cast", "TryCast",
    # maths
    "Abs", "Round", "Ceil", "Floor", "Sqrt", "Pow", "Ln", "Log", "Exp", "Sign",
    # dates and times
    "TimestampTrunc", "DateTrunc", "Extract", "TimeToStr", "ToChar", "StrToDate", "StrToTime",
    "CurrentDate", "CurrentTimestamp", "CurrentTime",
    # strings (no padding or repeat: they build arbitrarily large values)
    "Lower", "Upper", "Trim", "Length", "Concat", "ConcatWs", "Substring", "Replace", "Initcap",
    "Left", "Right", "StrPosition", "SplitPart",
})
ALLOWED_FUNCTION_NAMES = frozenset({"date_part", "make_date", "age", "to_date", "to_timestamp"})
# Old blocklist, kept as a second check behind the allowlist.
BLOCKED_PREFIXES = ("pg_", "lo_", "dblink", "set_config", "current_setting")

WRITE_NODES = tuple(getattr(exp, n) for n in (
    "Insert", "Update", "Delete", "Merge", "Create", "Drop", "Alter", "Command", "Copy", "Into",
) if hasattr(exp, n))
SET_OPERATIONS = (exp.Union, exp.Intersect, exp.Except)


class SQLRejected(Exception):
    pass


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


def validate_sql(sql: str, allowed_tables = ALLOWED_TABLES) -> ValidatedSQL:
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
    return ValidatedSQL(tree.sql(dialect="postgres"))
