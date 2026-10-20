import os
from dataclasses import dataclass

import psycopg

from app.db import DBError


@dataclass(frozen=True)
class User:
    username: str
    role: str
    is_active: bool = True
    password_hash: str = ""


def _url():
    url = os.getenv("APP_DATABASE_URL")
    if not url:
        raise DBError("APP_DATABASE_URL is not set.")
    return url


def get_user(username):
    try:
        with psycopg.connect(_url(), connect_timeout=5) as conn:
            row = conn.execute(
                "SELECT username, role, is_active, password_hash FROM users WHERE username = %s",
                (username.strip().lower(),),
            ).fetchone()
    except psycopg.Error as e:
        raise DBError("Database error.") from e
    if row is None:
        return None
    return User(username=row[0], role=row[1], is_active=row[2], password_hash=row[3])


def create_user(username, password_hash, role):
    try:
        with psycopg.connect(_url(), connect_timeout=5) as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s)",
                (username.strip().lower(), password_hash, role),
            )
    except psycopg.Error as e:
        raise DBError("Database error.") from e