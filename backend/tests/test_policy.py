"""GR-POL-01: one policy file, validated at startup, enforced by code."""
import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app import limits, policy
from app.access import ROLE_DB_ENV, ROLE_TABLES
from app.bi import sql_guard

BACKEND = Path(__file__).resolve().parents[1]
POLICY_FILE = BACKEND / "policy" / "guardrails.toml"

# The rules as they were hard-coded before GR-POL-01. Moving them into the file must not change them.
BEFORE = {
    "roles": {"analyst": ("orders", "regions"), "limited": ("regions",)},
    "db_env": {"analyst": "DATABASE_URL", "limited": "DATABASE_URL_LIMITED"},
    "limits": {"max_rows": 200, "max_result_bytes": 1_000_000, "timeout_ms": 5000, "max_tables": 8, "max_depth": 3},
    "names": {"date_part", "make_date", "age", "to_date", "to_timestamp"},
    "prefixes": ("pg_", "lo_", "dblink", "set_config", "current_setting"),
    "types": {
        "Count", "Sum", "Avg", "Min", "Max", "Stddev", "StddevPop", "StddevSamp", "Variance", "VariancePop",
        "PercentileCont", "PercentileDisc", "ArrayAgg", "GroupConcat", "LogicalAnd", "LogicalOr",
        "RowNumber", "Rank", "DenseRank", "PercentRank", "CumeDist", "Ntile", "Lag", "Lead",
        "FirstValue", "LastValue", "NthValue",
        "Case", "If", "Coalesce", "Nullif", "Greatest", "Least", "Cast", "TryCast",
        "Abs", "Round", "Ceil", "Floor", "Sqrt", "Pow", "Ln", "Log", "Exp", "Sign",
        "TimestampTrunc", "DateTrunc", "Extract", "TimeToStr", "ToChar", "StrToDate", "StrToTime",
        "CurrentDate", "CurrentTimestamp", "CurrentTime",
        "Lower", "Upper", "Trim", "Length", "Concat", "ConcatWs", "Substring", "Replace", "Initcap",
        "Left", "Right", "StrPosition", "SplitPart",
    },
}

VALID = POLICY_FILE.read_text() if POLICY_FILE.exists() else ""


# ---- the file reproduces the old rules exactly ---------------------------------

def test_policy_file_reproduces_the_previous_rules():
    p = policy.load(POLICY_FILE)
    assert {r: role.tables for r, role in p.roles.items()} == BEFORE["roles"]
    assert {r: role.database_url_env for r, role in p.roles.items()} == BEFORE["db_env"]
    assert p.sql == BEFORE["limits"]
    assert p.allowed_function_types == BEFORE["types"]
    assert p.allowed_function_names == BEFORE["names"]
    assert p.blocked_prefixes == BEFORE["prefixes"]


def test_code_reads_its_rules_from_the_policy():
    p = policy.get()
    assert ROLE_TABLES == {r: role.tables for r, role in p.roles.items()}
    assert ROLE_DB_ENV == {r: role.database_url_env for r, role in p.roles.items()}
    assert sql_guard.ALLOWED_FUNCTION_TYPES == p.allowed_function_types
    assert sql_guard.ALLOWED_FUNCTION_NAMES == p.allowed_function_names
    assert sql_guard.BLOCKED_PREFIXES == p.blocked_prefixes


def test_the_policy_records_its_path_and_hash():
    p = policy.load(POLICY_FILE)
    assert p.path == POLICY_FILE
    assert p.sha256 == hashlib.sha256(POLICY_FILE.read_bytes()).hexdigest()


# ---- invariants: what no edit to the policy may do ------------------------------

def test_no_role_may_read_internal_notes():
    assert all("internal_notes" not in role.tables for role in policy.get().roles.values())


def test_limited_sees_a_subset_of_analyst():
    roles = policy.get().roles
    assert set(roles["limited"].tables) <= set(roles["analyst"].tables)


@pytest.mark.parametrize("name", ["QueryToXml", "CurrentVersion", "CurrentUser", "SessionUser", "CurrentDatabase",
                                  "Repeat", "Pad", "GenerateSeries", "ExplodingGenerateSeries", "Unnest"])
def test_dangerous_function_types_are_not_allowed(name):
    assert name not in policy.get().allowed_function_types


@pytest.mark.parametrize("name", ["query_to_xml", "table_to_xml", "cursor_to_xml", "version", "inet_server_addr",
                                  "current_setting", "pg_read_file", "dblink", "lo_import", "set_config"])
def test_dangerous_function_names_are_not_allowed(name):
    assert name not in policy.get().allowed_function_names


# ---- malformed files are refused --------------------------------------------------

BROKEN = {
    "not toml": ("[sql\nmax_rows = 1", "could not be read"),
    "missing section": (VALID.replace("[roles.limited]", "[roles_limited_typo]"), "roles_limited_typo"),
    "unknown key": (VALID.replace("max_rows = 200", "max_rows = 200\nmax_rowz = 5"), "max_rowz"),
    "wrong type": (VALID.replace("max_rows = 200", 'max_rows = "200"'), "max_rows"),
    "zero limit": (VALID.replace("max_depth = 3", "max_depth = 0"), "max_depth"),
    "boolean limit": (VALID.replace("max_depth = 3", "max_depth = true"), "max_depth"),
    "unknown function type": (VALID.replace('"Count",', '"Count", "NotARealFunction",'), "NotARealFunction"),
    "allowed name with blocked prefix": (VALID.replace('"date_part",', '"date_part", "pg_read_file",'),
                                         "pg_read_file"),
    "role without tables": (VALID.replace('tables = ["regions"]', "tables = []"), "limited"),
    "bad table name": (VALID.replace('tables = ["regions"]', 'tables = ["regions; drop"]'), "regions; drop"),
    "missing database variable": (VALID.replace('database_url_env = "DATABASE_URL_LIMITED"', ""),
                                  "database_url_env"),
    "prompt function in upper case": (VALID.replace('"count",', '"COUNT",', 1), "COUNT"),
}


@pytest.mark.parametrize("text,mentions", BROKEN.values(), ids=BROKEN.keys())
def test_malformed_policies_are_refused(tmp_path, text, mentions):
    assert text != VALID
    bad = tmp_path / "guardrails.toml"
    bad.write_text(text)
    with pytest.raises(policy.PolicyError, match=None) as e:
        policy.load(bad)
    assert mentions in str(e.value)


def test_a_missing_file_is_refused(tmp_path):
    with pytest.raises(policy.PolicyError):
        policy.load(tmp_path / "nope.toml")


def _start_backend(env_policy):
    env = {**os.environ, "GUARDRAIL_POLICY": str(env_policy), "LOG_FORMAT": "json"}
    return subprocess.run([sys.executable, "-c", "import app.main"], cwd=BACKEND, env=env,
                          capture_output=True, text=True, timeout=60)


def test_the_backend_does_not_start_with_a_broken_policy(tmp_path):
    bad = tmp_path / "guardrails.toml"
    bad.write_text(VALID.replace("max_depth = 3", "max_depth = 0"))
    result = _start_backend(bad)
    assert result.returncode != 0
    assert "PolicyError" in result.stderr and "max_depth" in result.stderr


def test_the_backend_logs_which_policy_it_loaded():
    result = _start_backend(POLICY_FILE)
    assert result.returncode == 0, result.stderr
    assert "policy_loaded" in result.stderr
    assert hashlib.sha256(POLICY_FILE.read_bytes()).hexdigest() in result.stderr


# ---- the environment may tighten a limit, never loosen it ------------------------

def test_environment_can_tighten_a_limit(monkeypatch):
    monkeypatch.setenv("SQL_MAX_ROWS", "5")
    assert limits.sql_max_rows() == 5


@pytest.mark.parametrize("name,fn", [("SQL_MAX_ROWS", limits.sql_max_rows),
                                     ("SQL_MAX_TABLES", limits.sql_max_tables),
                                     ("SQL_TIMEOUT_MS", limits.sql_timeout_ms)])
def test_environment_cannot_loosen_a_limit(monkeypatch, name, fn):
    monkeypatch.setenv(name, "999999")
    assert fn() == policy.get().sql[name.removeprefix("SQL_").lower()]
