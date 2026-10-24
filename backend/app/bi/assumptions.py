"""The assumptions behind an answer, read from its SQL (GR-ACC-03).

A wrong period or an unexpected filter is the most common silent mistake, so every data answer
lists the date ranges and filters its query used, deterministically, from the parsed SQL:
"Dates: 1 Sep 2026 to 30 Sep 2026 (order_date)", "status is completed". Half-open ranges
(>= start, < next day) are shown with their last included day.
"""
import re
from datetime import date, timedelta

import sqlglot
from sqlglot import exp

DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?)?")


def _unwrap(node):
    while isinstance(node, (exp.Cast, exp.TryCast, exp.Paren)):
        node = node.this
    return node


def _as_date(node):
    """(date, at_midnight) for a string literal like '2026-09-01', or None."""
    node = _unwrap(node)
    if not (isinstance(node, exp.Literal) and node.is_string):
        return None
    m = DATE.match(node.this.strip())
    if not m:
        return None
    midnight = m[4] is None or (m[4], m[5], m[6] or "00") == ("00", "00", "00")
    return date(int(m[1]), int(m[2]), int(m[3])), midnight


def _fmt(d):
    return f"{d.day} {d.strftime('%b')} {d.year}"


def _conjuncts(node):
    node = _unwrap(node)
    if isinstance(node, exp.And):
        yield from _conjuncts(node.this)
        yield from _conjuncts(node.expression)
    else:
        yield node


def _literal_text(node):
    node = _unwrap(node)
    return node.this if isinstance(node, exp.Literal) else None


FLIP = {exp.GTE: exp.LTE, exp.GT: exp.LT, exp.LTE: exp.GTE, exp.LT: exp.GT}


def assumptions(sql):
    try:
        tree = sqlglot.parse_one(sql, read="postgres") if sql and sql.strip() else None
    except sqlglot.errors.ParseError:
        return []
    if tree is None:
        return []
    ranges, years, filters = {}, [], []
    for where in tree.find_all(exp.Where):
        for cond in _conjuncts(where.this):
            kind, left, right = type(cond), getattr(cond, "this", None), getattr(cond, "expression", None)
            if kind in FLIP and isinstance(_unwrap(right), exp.Column) and _as_date(left):
                kind, left, right = FLIP[kind], right, left           # '2026-01-01' <= col
            if isinstance(cond, exp.Between) and isinstance(_unwrap(left), exp.Column):
                low, high = _as_date(cond.args.get("low")), _as_date(cond.args.get("high"))
                if low and high:
                    r = ranges.setdefault(_unwrap(left).sql(), {})
                    r["start"], r["end"] = low[0], high[0]
                continue
            column = _unwrap(left) if left is not None else None
            if kind in FLIP and isinstance(column, exp.Column) and _as_date(right):
                d, midnight = _as_date(right)
                r = ranges.setdefault(column.sql(), {})
                if kind is exp.GTE:
                    r["start"] = d
                elif kind is exp.GT:
                    r["start"] = d if not midnight else d + timedelta(days=1)
                elif kind is exp.LT:
                    r["end"], r["before"] = (d - timedelta(days=1) if midnight else d), d
                elif kind is exp.LTE:
                    r["end"] = d
                continue
            if kind is exp.EQ and isinstance(_unwrap(left), exp.Extract):
                part = _unwrap(left).this.name.upper()
                value = _literal_text(right)
                if part == "YEAR" and value is not None:
                    years.append(f"Year {value} ({_unwrap(left).expression.sql()})")
                continue
            if kind in (exp.EQ, exp.NEQ) and isinstance(column, exp.Column) and _literal_text(right) is not None:
                filters.append(f"{column.sql()} is {'not ' if kind is exp.NEQ else ''}{_literal_text(right)}")
            elif isinstance(cond, exp.In) and isinstance(column, exp.Column):
                values = [_literal_text(v) for v in cond.expressions]
                if values and None not in values:
                    filters.append(f"{column.sql()} is {' or '.join(values)}")
    out = []
    for column, r in ranges.items():
        if "start" in r and "end" in r:
            out.append(f"Dates: {_fmt(r['start'])} to {_fmt(r['end'])} ({column})")
        elif "start" in r:
            out.append(f"Dates: from {_fmt(r['start'])} ({column})")
        elif "before" in r:
            out.append(f"Dates: before {_fmt(r['before'])} ({column})")
        elif "end" in r:
            out.append(f"Dates: up to {_fmt(r['end'])} ({column})")
    return out + years + filters
