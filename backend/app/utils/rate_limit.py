"""Bounded, process-local request throttling. Deploy one API worker."""
import threading
import time
from collections import OrderedDict, deque
from app.utils.errors import AppException


class RateLimiter:
    def __init__(self):
        self.entries = OrderedDict()
        self.lock = threading.Lock()

    def check(self, key, limit, window):
        now = time.monotonic()
        with self.lock:
            attempts = self.entries.setdefault(key, deque())
            self.entries.move_to_end(key)
            while attempts and attempts[0] <= now - window:
                attempts.popleft()
            if len(attempts) >= limit:
                raise AppException(429, "RATE_LIMIT_EXCEEDED", "Too many requests. Please wait before trying again.")
            attempts.append(now)
            while len(self.entries) > 10000:
                self.entries.popitem(last=False)


auth_limiter = RateLimiter()
