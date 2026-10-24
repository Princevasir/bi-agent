from functools import lru_cache

from app import catalog, policy


class AccessError(Exception):
    """The role is unknown or not allowed."""


# From the policy file (GR-POL-01); a malformed policy stops the import, and so the backend.
# These two reflect the data source active when the backend started; the functions below read it
# on every call.
ROLE_TABLES = {name: role.tables for name, role in policy.get().roles.items()}
ROLE_DB_ENV = {name: role.database_url_env for name, role in policy.get().roles.items()}


def data_source():
    """The active data source (DATA_SOURCE, default sample); an unknown name raises PolicyError."""
    return policy.active_source(policy.get())


def uses_catalog():
    return policy.get().sources[data_source()].catalog


def _role(role):
    roles = policy.get().sources[data_source()].roles
    if role not in roles:
        raise AccessError("Unknown role.")
    return roles[role]


def tables_for(role):
    return _role(role).tables


def db_env_for(role):
    return _role(role).database_url_env


@lru_cache(maxsize=1)
def _personal_columns():
    return frozenset((t.name, c.name) for t in catalog.get().tables.values()
                     for c in t.columns.values() if c.pii)


def may_export(role):
    """Whether the role may download result tables (GR-PRIV-05)."""
    return _role(role).export


def denied_columns(role):
    """(table, column) pairs the role may not read: personal data, unless the role is allowed it."""
    r = _role(role)
    if not uses_catalog() or r.personal_data:
        return frozenset()
    return _personal_columns()


def metric_rules():
    """The catalog's metric rules for the active source; none for sources without a catalog."""
    return catalog.get().rules if uses_catalog() else ()
