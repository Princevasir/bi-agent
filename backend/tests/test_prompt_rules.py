"""GR-POL-02: the SQL prompt's rules are generated from the guardrail policy."""
import dataclasses
from datetime import date

import pytest

from app import policy
from app.bi import text_to_sql
from app.bi.sql_guard import validate_sql
from app.bi.text_to_sql import build_prompt

TODAY = date(2026, 10, 15)

# One accepted example call for every function the prompt advertises. A function added to
# prompt_functions without an example here fails the test, so each one gets checked.
EXAMPLES = {
    "count": "count(*)", "sum": "sum(amount)", "avg": "avg(amount)", "min": "min(amount)", "max": "max(amount)",
    "stddev": "stddev(amount)", "percentile_cont": "percentile_cont(0.5) WITHIN GROUP (ORDER BY amount)",
    "string_agg": "string_agg(status, ',')", "array_agg": "array_agg(id)",
    "bool_and": "bool_and(amount > 0)", "bool_or": "bool_or(amount > 0)",
    "row_number": "row_number() OVER (ORDER BY id)", "rank": "rank() OVER (ORDER BY amount)",
    "dense_rank": "dense_rank() OVER (ORDER BY amount)", "percent_rank": "percent_rank() OVER (ORDER BY amount)",
    "cume_dist": "cume_dist() OVER (ORDER BY amount)", "ntile": "ntile(4) OVER (ORDER BY amount)",
    "lag": "lag(amount) OVER (ORDER BY id)", "lead": "lead(amount) OVER (ORDER BY id)",
    "first_value": "first_value(amount) OVER (ORDER BY id)", "last_value": "last_value(amount) OVER (ORDER BY id)",
    "nth_value": "nth_value(amount, 2) OVER (ORDER BY id)",
    "coalesce": "coalesce(amount, 0)", "nullif": "nullif(amount, 0)", "greatest": "greatest(amount, 1)",
    "least": "least(amount, 1)", "abs": "abs(amount)", "round": "round(amount, 2)", "ceil": "ceil(amount)",
    "floor": "floor(amount)", "sqrt": "sqrt(amount)", "power": "power(amount, 2)", "ln": "ln(amount)",
    "log": "log(amount)", "exp": "exp(1)", "sign": "sign(amount)",
    "date_trunc": "date_trunc('month', order_date)", "extract": "extract(month FROM order_date)",
    "date_part": "date_part('year', order_date)", "to_char": "to_char(order_date, 'YYYY-MM')",
    "to_date": "to_date('2026-01-01', 'YYYY-MM-DD')", "to_timestamp": "to_timestamp('2026-01-01', 'YYYY-MM-DD')",
    "make_date": "make_date(2026, 1, 1)", "age": "age(order_date)", "now": "now()", "current_date": "current_date",
    "lower": "lower(status)", "upper": "upper(status)", "trim": "trim(status)", "length": "length(status)",
    "concat": "concat(status, 'x')", "concat_ws": "concat_ws('-', status, status)",
    "substring": "substring(status, 1, 2)", "replace": "replace(status, 'a', 'b')", "initcap": "initcap(status)",
    "left": "left(status, 2)", "right": "right(status, 2)", "strpos": "strpos(status, 'a')",
    "split_part": "split_part(status, '-', 1)",
}


@pytest.fixture
def custom_policy(monkeypatch):
    def use(**sql_changes):
        base = policy.get()
        changed = dataclasses.replace(base, sql={**base.sql, **sql_changes.pop("sql", {})}, **sql_changes)
        monkeypatch.setattr(text_to_sql.policy, "get", lambda: changed)
        return changed
    return use


def test_prompt_keeps_its_opening():
    assert build_prompt("x", TODAY).startswith("You write PostgreSQL")   # RoutedLLM routes on this


def test_prompt_states_every_rule_from_the_policy():
    p = policy.get()
    prompt = build_prompt("Revenue by region?", TODAY)
    assert "Rules" in prompt
    assert f"at most {p.sql['max_tables']} table references" in prompt
    assert f"at most {p.sql['max_depth']} levels of nested subqueries" in prompt
    assert "condition" in prompt and "CROSS JOIN" in prompt
    assert "INSERT, UPDATE, DELETE" in prompt
    for name in p.prompt_functions:
        assert name in prompt


def test_changing_the_policy_changes_the_prompt(custom_policy):
    custom_policy(sql={"max_tables": 4}, prompt_functions=("count", "sum"))
    prompt = build_prompt("x", TODAY)
    assert "at most 4 table references" in prompt
    assert "count, sum" in prompt and "date_trunc" not in prompt


def test_every_function_the_prompt_offers_has_an_example():
    assert set(policy.get().prompt_functions) == set(EXAMPLES)


@pytest.mark.parametrize("name", sorted(EXAMPLES))
def test_every_function_the_prompt_offers_is_accepted_by_the_validator(name):
    assert validate_sql(f"SELECT {EXAMPLES[name]} FROM orders")


def test_question_comes_after_the_rules():
    prompt = build_prompt("What was revenue?", TODAY)
    assert prompt.index("Rules") < prompt.index("Question: What was revenue?")
