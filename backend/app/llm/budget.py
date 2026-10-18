from threading import Lock

from app.llm.base import LLMRateLimitError


class TokenBudget:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.used = 0
        self._lock = Lock()

    def check(self) -> None:
        with self._lock:
            if self.used >= self.limit:
                raise LLMRateLimitError("Token budget exhausted.")

    def record(self, tokens: int) -> None:
        with self._lock:
            self.used += tokens