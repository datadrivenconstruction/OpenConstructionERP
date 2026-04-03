"""Simple in-memory rate limiter (no Redis required).

Limits requests per user per time window. Thread-safe via dict with timestamps.
For production, replace with Redis-based implementation.
"""

import time
from collections import defaultdict
from threading import Lock


class RateLimiter:
    """Token bucket rate limiter using sliding window."""

    def __init__(self, max_requests: int = 10, window_seconds: int = 60) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    def is_allowed(self, key: str) -> tuple[bool, int]:
        """Check if request is allowed. Returns (allowed, remaining)."""
        now = time.time()
        with self._lock:
            # Clean old entries
            self._requests[key] = [
                t for t in self._requests[key] if t > now - self.window_seconds
            ]

            if len(self._requests[key]) >= self.max_requests:
                return False, 0

            self._requests[key].append(now)
            remaining = self.max_requests - len(self._requests[key])
            return True, remaining


# Global instances
ai_limiter = RateLimiter(max_requests=10, window_seconds=60)  # 10 AI requests/min
api_limiter = RateLimiter(max_requests=100, window_seconds=60)  # 100 API requests/min
