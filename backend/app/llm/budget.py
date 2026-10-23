"""Token budgets for model calls (demo gap D5).

A rolling window (an hour by default): tokens spent more than a window ago no longer count, so
the budget refills on its own instead of ending the demo until a restart. Each user also has a
share, so one user cannot spend the budget for everyone. In memory, per process (see D11).
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


class TokenBudget:
    def __init__(self, limit: int, window_seconds: int = DEFAULT_WINDOW, per_user: int | None = None,
                 clock=time.monotonic) -> None:
        self.limit, self.window, self.per_user = limit, window_seconds, per_user
        self._clock = clock
        self._spent = deque()          # (time, user, tokens), oldest first
        self._lock = Lock()

    def _expire(self, now):
        while self._spent and self._spent[0][0] <= now - self.window:
            self._spent.popleft()

    def _over(self, entries, cap, now):
        if sum(t for _, _, t in entries) < cap:
            return
        total, wait = sum(t for _, _, t in entries), self.window
        for at, _, tokens in entries:          # wait until enough of the oldest spending expires
            total -= tokens
            if total < cap:
                wait = at + self.window - now
                break
        minutes = max(1, math.ceil(wait / 60))
        raise LLMBudgetError(f"Token budget for this hour is used up; it frees up in about {minutes} minutes.")

    def check(self, user=None) -> None:
        with self._lock:
            now = self._clock()
            self._expire(now)
            self._over(self._spent, self.limit, now)
            if user is not None and self.per_user is not None:
                self._over([e for e in self._spent if e[1] == user], self.per_user, now)

    def record(self, tokens: int, user=None) -> None:
        with self._lock:
            self._spent.append((self._clock(), user, tokens))

    def used(self, user=None) -> int:
        with self._lock:
            self._expire(self._clock())
            return sum(t for _, u, t in self._spent if user is None or u == user)


def from_env():
    return TokenBudget(int(os.getenv("LLM_TOKEN_BUDGET", DEFAULT_LIMIT)),
                       int(os.getenv("LLM_TOKEN_BUDGET_WINDOW_SECONDS", DEFAULT_WINDOW)),
                       int(os.getenv("LLM_USER_TOKEN_BUDGET", DEFAULT_PER_USER)))
