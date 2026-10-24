import os
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass

import psycopg
from psycopg.types.json import Jsonb

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

def ping():
    try:
        with psycopg.connect(_url(), connect_timeout=3) as conn:
            conn.execute("SELECT 1")
    except psycopg.Error as e:
        raise DBError("Database error.") from e


# ---- shared state for more than one backend instance (demo gap D11; STATE_STORE=postgres) ------------------
# Tables in db/init/09_shared_state.sql. Times are Unix seconds from the given clock.

def state_store():
    kind = os.getenv("STATE_STORE", "memory")
    if kind not in ("memory", "postgres"):
        raise ValueError(f"Unknown STATE_STORE: {kind} (use memory or postgres)")
    return kind


def _run(sql, params=(), fetch=False):
    try:
        with psycopg.connect(_url(), connect_timeout=5) as conn:
            cur = conn.execute(sql, params)
            return cur.fetchall() if fetch else None
    except psycopg.Error as e:
        raise DBError("Database error.") from e


class PgConversationStore:
    """Conversations in appdb, so every backend instance can answer a follow-up."""

    def __init__(self, max_conversations=10_000, max_turns=20, clock=time.time, key_prefix=""):
        self.max_conversations, self.max_turns, self.clock, self.key_prefix = (
            max_conversations, max_turns, clock, key_prefix)

    def new_id(self):
        return str(uuid.uuid4())

    def get(self, key):
        from app.bi.conversation import Turn
        rows = _run("SELECT turns FROM conversations WHERE key = %s", (key,), fetch=True)
        return [Turn(**t) for t in rows[0][0]] if rows else None

    def add(self, key, turn):
        # Append and trim in single statements, so two instances adding at once both keep their turn.
        _run("""INSERT INTO conversations (key, turns, updated_at) VALUES (%(key)s, jsonb_build_array(%(turn)s::jsonb), %(now)s)
                ON CONFLICT (key) DO UPDATE SET turns = conversations.turns || EXCLUDED.turns, updated_at = %(now)s""",
             {"key": key, "turn": Jsonb(asdict(turn)), "now": self.clock()})
        _run("""UPDATE conversations SET turns = (
                    SELECT jsonb_agg(e ORDER BY n) FROM jsonb_array_elements(turns) WITH ORDINALITY AS a(e, n)
                    WHERE n > jsonb_array_length(turns) - %(max)s)
                WHERE key = %(key)s AND jsonb_array_length(turns) > %(max)s""", {"key": key, "max": self.max_turns})
        _run("""DELETE FROM conversations WHERE key LIKE %(p)s AND key NOT IN (
                    SELECT key FROM conversations WHERE key LIKE %(p)s ORDER BY updated_at DESC LIMIT %(max)s)""",
             {"p": self.key_prefix + "%", "max": self.max_conversations})


class PgLoginThrottle:
    """The sign-in throttle in appdb: a lockout holds on every backend instance."""

    def __init__(self, max_failures=5, window=15 * 60, lockout=15 * 60, clock=time.time):
        self.max_failures, self.window, self.lockout, self.clock = max_failures, window, lockout, clock

    def is_locked(self, username):
        rows = _run("SELECT locked_until FROM login_locks WHERE username = %s", (username,), fetch=True)
        if not rows:
            return False
        if self.clock() >= rows[0][0]:
            _run("DELETE FROM login_locks WHERE username = %s", (username,))
            return False
        return True

    def record_failure(self, username):
        now = self.clock()
        _run("INSERT INTO login_failures (username, failed_at) VALUES (%s, %s)", (username, now))
        _run("DELETE FROM login_failures WHERE username = %s AND failed_at < %s", (username, now - self.window))
        [(count,)] = _run("SELECT count(*) FROM login_failures WHERE username = %s", (username,), fetch=True)
        if count >= self.max_failures:
            _run("""INSERT INTO login_locks (username, locked_until) VALUES (%(u)s, %(until)s)
                    ON CONFLICT (username) DO UPDATE SET locked_until = EXCLUDED.locked_until""",
                 {"u": username, "until": now + self.lockout})
            _run("DELETE FROM login_failures WHERE username = %s", (username,))

    def record_success(self, username):
        _run("DELETE FROM login_failures WHERE username = %s", (username,))


LEDGER_TABLES = ("token_usage", "request_usage")     # fixed names: a table name cannot be a query parameter


class PgTokenLedger:
    """Spending in appdb (tokens in token_usage, questions in request_usage), shared by every instance."""

    def __init__(self, table="token_usage"):
        if table not in LEDGER_TABLES:
            raise ValueError(f"Not a ledger table: {table!r}")
        self.table = table

    def add(self, at, user, tokens):
        _run(f"INSERT INTO {self.table} (spent_at, username, tokens) VALUES (%s, %s, %s)", (at, user, tokens))

    def prune(self, cutoff):
        _run(f"DELETE FROM {self.table} WHERE spent_at <= %s", (cutoff,))

    def entries(self, since, until, user=None):
        if user is None:
            return _run(f"SELECT spent_at, tokens FROM {self.table} WHERE spent_at > %s AND spent_at <= %s "
                        "ORDER BY spent_at", (since, until), fetch=True)
        return _run(f"SELECT spent_at, tokens FROM {self.table} WHERE spent_at > %s AND spent_at <= %s "
                    "AND username = %s ORDER BY spent_at", (since, until, user), fetch=True)


class PgRunning:
    """At most one running question per user across instances (GR-COST-03). A hold left by a crashed
    instance expires after stale_after seconds."""

    def __init__(self, clock=time.time, stale_after=300):
        self.clock, self.stale_after = clock, stale_after

    @contextmanager
    def hold(self, user):
        from app.request_limits import Busy
        now = self.clock()
        _run("DELETE FROM running_questions WHERE username = %s AND started_at < %s", (user, now - self.stale_after))
        got = _run("""INSERT INTO running_questions (username, started_at) VALUES (%s, %s)
                      ON CONFLICT (username) DO NOTHING RETURNING username""", (user, now), fetch=True)
        if not got:
            raise Busy(user)
        try:
            yield
        finally:
            _run("DELETE FROM running_questions WHERE username = %s", (user,))
