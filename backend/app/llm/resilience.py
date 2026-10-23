"""Retry and circuit breaker around one model provider (demo gap D9).

RetryingLLM retries a transient failure (the provider throttling us, a 5xx, a dropped connection)
once after a short pause. It never retries our own budget, a configuration error, or a timeout:
after up to two minutes of waiting, a retry would only double the wait.

CircuitBreaker stops calling a provider after several failures in a row and fails fast with
LLMUnavailableError for a cooldown, so a fallback answers at once instead of after another wait.
After the cooldown one trial call decides: success closes the breaker, failure opens it again.
Both keep their state per process (see D11) and pass attribute lookups through to the client.
"""
import logging
import time
from threading import Lock

from app.llm.base import LLMBudgetError, LLMConfigError, LLMError, LLMTimeoutError, LLMUnavailableError

logger = logging.getLogger("bi_agent")
NEVER_RETRY = (LLMBudgetError, LLMConfigError, LLMTimeoutError)


class _Wrapper:
    def __getattr__(self, name):          # url, model, timeout ... of the wrapped client
        return getattr(self.llm, name)


class RetryingLLM(_Wrapper):
    def __init__(self, llm, attempts=2, delay=1.0, sleep=time.sleep):
        self.llm, self.attempts, self.delay, self._sleep = llm, attempts, delay, sleep

    def generate(self, prompt):
        for attempt in range(1, self.attempts + 1):
            try:
                return self.llm.generate(prompt)
            except NEVER_RETRY:
                raise
            except LLMError as e:
                if attempt == self.attempts:
                    raise
                logger.warning("llm_retry", extra={"error": type(e).__name__, "attempt": attempt})
                self._sleep(self.delay * attempt)


class CircuitBreaker(_Wrapper):
    def __init__(self, llm, name, failures=3, cooldown=60, clock=time.monotonic):
        self.llm, self.name, self.threshold, self.cooldown, self._clock = llm, name, failures, cooldown, clock
        self.failures_in_a_row, self.opened_at, self._lock = 0, None, Lock()

    @property
    def state(self):
        if self.opened_at is None:
            return "closed"
        return "open" if self._clock() - self.opened_at < self.cooldown else "half_open"

    def generate(self, prompt):
        with self._lock:
            if self.state == "open":
                raise LLMUnavailableError(f"{self.name} is cooling down after repeated failures.")
        try:
            result = self.llm.generate(prompt)
        except LLMBudgetError:
            raise                                  # our own limit says nothing about the provider
        except LLMError as e:
            with self._lock:
                self.failures_in_a_row += 1
                if self.opened_at is not None or self.failures_in_a_row >= self.threshold:
                    self.opened_at = self._clock()
                    logger.warning("llm_circuit_open", extra={"provider": self.name, "error": type(e).__name__,
                                                              "cooldown_seconds": self.cooldown})
            raise
        with self._lock:
            if self.opened_at is not None:
                logger.info("llm_circuit_closed", extra={"provider": self.name})
            self.failures_in_a_row, self.opened_at = 0, None
        return result
