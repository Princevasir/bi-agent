import time
from collections import deque
from threading import Lock

MAX_FAILURES = 5
WINDOW_SECONDS = 15 * 60
LOCKOUT_SECONDS = 15 * 60


class LoginThrottle:
    def __init__(self, max_failures=MAX_FAILURES, window=WINDOW_SECONDS,
                 lockout=LOCKOUT_SECONDS, clock=time.monotonic):
        self.max_failures, self.window, self.lockout = max_failures, window, lockout
        self.clock = clock
        self._failures = {}
        self._locked_until = {}
        self._lock = Lock()

    def is_locked(self, username):
        with self._lock:
            until = self._locked_until.get(username)
            if until is None:
                return False
            if self.clock() >= until:
                del self._locked_until[username]
                return False
            return True

    def record_failure(self, username):
        with self._lock:
            now = self.clock()
            q = self._failures.setdefault(username, deque())
            q.append(now)
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.max_failures:
                self._locked_until[username] = now + self.lockout
                q.clear()

    def record_success(self, username):
        with self._lock:
            self._failures.pop(username, None)
