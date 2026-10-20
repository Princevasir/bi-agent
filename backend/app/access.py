class AccessError(Exception):
    """The role is unknown or not allowed."""


ROLE_TABLES = {"analyst": ("orders", "regions"), "limited": ("regions",)}
ROLE_DB_ENV = {"analyst": "DATABASE_URL", "limited": "DATABASE_URL_LIMITED"}


def tables_for(role):
    if role not in ROLE_TABLES:
        raise AccessError("Unknown role.")
    return ROLE_TABLES[role]


def db_env_for(role):
    if role not in ROLE_DB_ENV:
        raise AccessError("Unknown role.")
    return ROLE_DB_ENV[role]