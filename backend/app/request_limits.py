"""Per-user request limits: questions per minute and per day (GR-COST-01) and one running question
at a time (GR-COST-03). In memory by default, or in appdb with STATE_STORE=postgres so the limits
hold across backend instances (tables in db/init/10_request_limits.sql).
"""
import math
import os
import time
from contextlib import contextmanager
from threading import Lock

from app.llm.budget import MemoryLedger

MINUTE, DAY = 60, 24 * 3600


class RateLimited(Exception):
    def __init__(self, reason, retry_after):
        super().__init__(f"Too many questions in the last {reason}.")
        self.reason, self.retry_after = reason, retry_after


class Busy(Exception):
    """The user already has a question running."""


class RateLimiter:
    def __init__(self, per_minute=10, per_day=200, clock=time.monotonic, ledger=None):
        self.per_minute, self.per_day, self._clock = per_minute, per_day, clock
        self.ledger = ledger or MemoryLedger()

    def hit(self, user):
        """Count one question for the user, or raise RateLimited without counting it."""
        now = self._clock()
        self.ledger.prune(now - DAY)
        for reason, window, cap in (("minute", MINUTE, self.per_minute), ("day", DAY, self.per_day)):
            asked = self.ledger.entries(now - window, now, user)
            if sum(n for _, n in asked) >= cap:
                retry_after = max(1, math.ceil(asked[0][0] + window - now))
                raise RateLimited(reason, retry_after)
        self.ledger.add(now, user, 1)


class MemoryRunning:
    def __init__(self):
        self._running, self._lock = set(), Lock()

    @contextmanager
    def hold(self, user):
        with self._lock:
            if user in self._running:
                raise Busy(user)
            self._running.add(user)
        try:
            yield
        finally:
            with self._lock:
                self._running.discard(user)


def from_env():
    per_minute, per_day = int(os.getenv("RATE_PER_MINUTE", "10")), int(os.getenv("RATE_PER_DAY", "200"))
    from app.appdb import PgRunning, PgTokenLedger, state_store
    if state_store() == "postgres":
        return (RateLimiter(per_minute, per_day, clock=time.time, ledger=PgTokenLedger("request_usage")),
                PgRunning())
    return RateLimiter(per_minute, per_day), MemoryRunning()
