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

from app.llm.base import LLMBudgetError

DEFAULT_LIMIT = 400_000        # about 50 retail questions an hour in total
DEFAULT_PER_USER = 150_000     # about 20 retail questions an hour per user
DEFAULT_WINDOW = 3600


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

    def entries(self, since, user=None):
        with self._lock:
            return [(at, t) for at, u, t in self._spent if at > since and (user is None or u == user)]


class TokenBudget:
    def __init__(self, limit: int, window_seconds: int = DEFAULT_WINDOW, per_user: int | None = None,
                 clock=time.monotonic, ledger=None) -> None:
        self.limit, self.window, self.per_user = limit, window_seconds, per_user
        self._clock = clock
        self.ledger = ledger or MemoryLedger()

    def _over(self, entries, cap, now):
        total = sum(t for _, t in entries)
        if total < cap:
            return
        wait = self.window
        for at, tokens in entries:             # wait until enough of the oldest spending expires
            total -= tokens
            if total < cap:
                wait = at + self.window - now
                break
        minutes = max(1, math.ceil(wait / 60))
        raise LLMBudgetError(f"Token budget for this hour is used up; it frees up in about {minutes} minutes.")

    def check(self, user=None) -> None:
        now = self._clock()
        cutoff = now - self.window
        self.ledger.prune(cutoff)
        self._over(self.ledger.entries(cutoff), self.limit, now)
        if user is not None and self.per_user is not None:
            self._over(self.ledger.entries(cutoff, user), self.per_user, now)

    def record(self, tokens: int, user=None) -> None:
        self.ledger.add(self._clock(), user, tokens)

    def used(self, user=None) -> int:
        now = self._clock()
        return sum(t for _, t in self.ledger.entries(now - self.window, user))


def from_env():
    settings = (int(os.getenv("LLM_TOKEN_BUDGET", DEFAULT_LIMIT)),
                int(os.getenv("LLM_TOKEN_BUDGET_WINDOW_SECONDS", DEFAULT_WINDOW)),
                int(os.getenv("LLM_USER_TOKEN_BUDGET", DEFAULT_PER_USER)))
    from app.appdb import PgTokenLedger, state_store
    if state_store() == "postgres":
        return TokenBudget(*settings, clock=time.time, ledger=PgTokenLedger())   # wall clock: shared by processes
    return TokenBudget(*settings)
