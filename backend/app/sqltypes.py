"""Marker types for SQL that may reach the database (GR-SQL-06).

run_readonly accepts only these, so model-written SQL cannot reach Postgres
without passing validate_sql. Python cannot stop someone constructing them by
hand; the rule is that only validate_sql creates ValidatedSQL, and TrustedSQL
wraps fixed text written in our own code, never text from a model or a user.
"""


class ValidatedSQL(str):
    """SQL returned by validate_sql."""


class TrustedSQL(str):
    """Fixed, code-authored SQL (pings, schema lookups), never model or user text."""
