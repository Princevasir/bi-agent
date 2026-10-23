from app import policy


class AccessError(Exception):
    """The role is unknown or not allowed."""


# From the policy file (GR-POL-01); a malformed policy stops the import, and so the backend.
ROLE_TABLES = {name: role.tables for name, role in policy.get().roles.items()}
ROLE_DB_ENV = {name: role.database_url_env for name, role in policy.get().roles.items()}


def tables_for(role):
    if role not in ROLE_TABLES:
        raise AccessError("Unknown role.")
    return ROLE_TABLES[role]


def db_env_for(role):
    if role not in ROLE_DB_ENV:
        raise AccessError("Unknown role.")
    return ROLE_DB_ENV[role]