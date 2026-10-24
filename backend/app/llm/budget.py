"""Token budgets for model calls (demo gap D5).

A rolling window (an hour by default): tokens spent more than a window ago no longer count, so
the budget refills on its own instead of ending the demo until a restart. Each user also has a
share, so one user cannot spend the budget for everyone. Spending is kept in a ledger: in memory
by default, or in appdb with STATE_STORE=postgres so every backend instance shares it (D11).
"""
import math
import os
import time
from collections import deque
from threading import Lock

from app.llm.base import LLMBudgetError, LLMDailyQuotaError

DEFAULT_LIMIT = 400_000        # about 50 retail questions an hour in total
DEFAULT_PER_USER = 150_000     # about 20 retail questions an hour per user
DEFAULT_WINDOW = 3600
DEFAULT_PER_USER_DAILY = 600_000   # about 75 retail questions a day per user (GR-COST-02)
DAY = 24 * 3600


class MemoryLedger:
    def __init__(self):
        self._spent = deque()          # (time, user, tokens), oldest first
        self._lock = Lock()

    def add(self, at, user, tokens):
        with self._lock:
            self._spent.append((at, user, tokens))

    def prune(self, cutoff):
        with self._lock:
            while self._spent and self._spent[0][0] <= cutoff:
                self._spent.popleft()

    def entries(self, since, until, user=None):
        with self._lock:
            return [(at, t) for at, u, t in self._spent
                    if since < at <= until and (user is None or u == user)]


class TokenBudget:
    def __init__(self, limit: int, window_seconds: int = DEFAULT_WINDOW, per_user: int | None = None,
                 clock=time.monotonic, ledger=None, per_user_daily: int | None = None) -> None:
        self.limit, self.window, self.per_user, self.per_user_daily = limit, window_seconds, per_user, per_user_daily
        self._clock = clock
        self.ledger = ledger or MemoryLedger()

    def _over(self, entries, cap, now, window=None, error=LLMBudgetError, period="hour"):
        window = window or self.window
        total = sum(t for _, t in entries)
        if total < cap:
            return
        wait = window
        for at, tokens in entries:             # wait until enough of the oldest spending expires
            total -= tokens
            if total < cap:
                wait = at + window - now
                break
        minutes = max(1, math.ceil(wait / 60))
        raise error(f"Token budget for this {period} is used up; it frees up in about {minutes} minutes.")

    def check(self, user=None) -> None:
        now = self._clock()
        cutoff = now - self.window
        self.ledger.prune(now - max(self.window, DAY if self.per_user_daily else 0))
        # Only spending inside [now - window, now] counts: another instance's clock may run ahead.
        self._over(self.ledger.entries(cutoff, now), self.limit, now)
        if user is not None and self.per_user is not None:
            self._over(self.ledger.entries(cutoff, now, user), self.per_user, now)
        if user is not None and self.per_user_daily is not None:       # GR-COST-02
            self._over(self.ledger.entries(now - DAY, now, user), self.per_user_daily, now,
                       window=DAY, error=LLMDailyQuotaError, period="day")

    def record(self, tokens: int, user=None) -> None:
        self.ledger.add(self._clock(), user, tokens)

    def used(self, user=None) -> int:
        now = self._clock()
        return sum(t for _, t in self.ledger.entries(now - self.window, now, user))


def from_env():
    settings = (int(os.getenv("LLM_TOKEN_BUDGET", DEFAULT_LIMIT)),
                int(os.getenv("LLM_TOKEN_BUDGET_WINDOW_SECONDS", DEFAULT_WINDOW)),
                int(os.getenv("LLM_USER_TOKEN_BUDGET", DEFAULT_PER_USER)))
    daily = int(os.getenv("LLM_USER_DAILY_TOKEN_BUDGET", DEFAULT_PER_USER_DAILY))
    from app.appdb import PgTokenLedger, state_store
    if state_store() == "postgres":                  # wall clock: shared by processes
        return TokenBudget(*settings, clock=time.time, ledger=PgTokenLedger(), per_user_daily=daily)
    return TokenBudget(*settings, per_user_daily=daily)
