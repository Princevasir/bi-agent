"""The guardrail policy file (GR-POL-01): loaded once, checked strictly, enforced by code.

`get()` returns the policy from GUARDRAIL_POLICY, or backend/policy/guardrails.toml. Any problem
raises PolicyError, and because access.py, limits.py and sql_guard.py read the policy when they
are imported, a malformed file stops the backend from starting (fail closed).
"""
import hashlib
import os
import re
import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from sqlglot import exp

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "policy" / "guardrails.toml"
SQL_LIMITS = ("max_rows", "max_result_bytes", "timeout_ms", "max_tables", "max_depth", "repair_attempts")
MAY_BE_ZERO = {"repair_attempts"}
TABLE_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")
ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")


class PolicyError(Exception):
    """The policy file is missing or malformed."""


@dataclass(frozen=True)
class Role:
    tables: tuple
    database_url_env: str
    personal_data: bool = False


@dataclass(frozen=True)
class Source:
    catalog: bool
    roles: dict


@dataclass(frozen=True)
class Policy:
    path: Path
    sha256: str
    sql: dict
    allowed_function_types: frozenset
    allowed_function_names: frozenset
    blocked_prefixes: tuple
    prompt_functions: tuple
    sources: dict

    @property
    def roles(self):
        """Roles of the active data source (DATA_SOURCE, default sample)."""
        return self.sources[active_source(self)].roles


def active_source(p):
    name = os.getenv("DATA_SOURCE", "sample")
    if name not in p.sources:
        raise PolicyError(f"DATA_SOURCE must be one of {', '.join(sorted(p.sources))}, got {name!r}.")
    return name


def _keys(section, where, required, optional=()):
    if not isinstance(section, dict):
        raise PolicyError(f"{where} must be a table.")
    unknown = sorted(set(section) - set(required) - set(optional))
    if unknown:
        raise PolicyError(f"Unknown key in {where}: {', '.join(unknown)}")
    missing = [k for k in required if k not in section]
    if missing:
        raise PolicyError(f"Missing key in {where}: {', '.join(missing)}")


def _strings(value, where):
    if not isinstance(value, list) or not value or not all(isinstance(v, str) and v for v in value):
        raise PolicyError(f"{where} must be a non-empty list of strings.")
    if len(set(value)) != len(value):
        raise PolicyError(f"{where} has duplicates.")
    return value


def load(path=None):
    path = Path(path or os.getenv("GUARDRAIL_POLICY") or DEFAULT_PATH)
    try:
        raw = path.read_bytes()
        doc = tomllib.loads(raw.decode())
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
        raise PolicyError(f"The policy file {path} could not be read: {e}") from e

    _keys(doc, "the policy", ("version", "sql", "sources"))
    if doc["version"] != 1:
        raise PolicyError("Unsupported policy version.")

    sql = doc["sql"]
    _keys(sql, "[sql]", SQL_LIMITS + ("functions",))
    for name in SQL_LIMITS:
        v = sql[name]
        if isinstance(v, bool) or not isinstance(v, int) or v < (0 if name in MAY_BE_ZERO else 1):
            raise PolicyError(f"[sql] {name} must be a whole number greater than {-1 if name in MAY_BE_ZERO else 0}.")

    fn = sql["functions"]
    _keys(fn, "[sql.functions]", ("allowed_types", "allowed_names", "blocked_prefixes", "prompt_functions"))
    types = _strings(fn["allowed_types"], "[sql.functions] allowed_types")
    for t in types:
        cls = getattr(exp, t, None)
        if not (isinstance(cls, type) and issubclass(cls, exp.Func)):
            raise PolicyError(f"[sql.functions] allowed_types: {t} is not a sqlglot function type.")
    prefixes = tuple(p.lower() for p in _strings(fn["blocked_prefixes"], "[sql.functions] blocked_prefixes"))
    names = _strings(fn["allowed_names"], "[sql.functions] allowed_names")
    for n in names:
        if n != n.lower() or n.startswith(prefixes):
            raise PolicyError(f"[sql.functions] allowed_names: {n} must be lower case and not blocked.")
    shown = _strings(fn["prompt_functions"], "[sql.functions] prompt_functions")
    for n in shown:
        if not TABLE_NAME.match(n) or n.startswith(prefixes):
            raise PolicyError(f"[sql.functions] prompt_functions: {n} must be a lower-case SQL name, not blocked.")

    sources = doc["sources"]
    if not isinstance(sources, dict) or "sample" not in sources:
        raise PolicyError("[sources] must define at least the sample source.")
    parsed = {}
    for source_name, source in sources.items():
        _keys(source, f"[sources.{source_name}]", ("catalog", "roles"))
        if not isinstance(source["catalog"], bool):
            raise PolicyError(f"[sources.{source_name}] catalog must be true or false.")
        roles = source["roles"]
        if not isinstance(roles, dict) or not roles:
            raise PolicyError(f"[sources.{source_name}.roles] must define at least one role.")
        parsed_roles = {}
        for name, role in roles.items():
            where = f"[sources.{source_name}.roles.{name}]"
            _keys(role, where, ("tables", "database_url_env"), ("personal_data",))
            tables = _strings(role["tables"], f"{where} tables") if role["tables"] else None
            if not tables:
                raise PolicyError(f"{where} tables must list at least one table.")
            for t in tables:
                if not TABLE_NAME.match(t):
                    raise PolicyError(f"{where} tables: {t} is not a valid table name.")
            env = role["database_url_env"]
            if not isinstance(env, str) or not ENV_NAME.match(env):
                raise PolicyError(f"{where} database_url_env must be an environment variable name.")
            personal = role.get("personal_data", False)
            if not isinstance(personal, bool):
                raise PolicyError(f"{where} personal_data must be true or false.")
            parsed_roles[name] = Role(tables=tuple(tables), database_url_env=env, personal_data=personal)
        parsed[source_name] = Source(catalog=source["catalog"], roles=parsed_roles)

    return Policy(
        path=path, sha256=hashlib.sha256(raw).hexdigest(),
        sql={k: sql[k] for k in SQL_LIMITS},
        allowed_function_types=frozenset(types), allowed_function_names=frozenset(names),
        blocked_prefixes=prefixes, prompt_functions=tuple(shown), sources=parsed,
    )


@lru_cache(maxsize=1)
def get():
    return load()
