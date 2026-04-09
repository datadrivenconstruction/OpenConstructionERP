"""Simple in-memory rate limiter (no Redis required).

Limits requests per user per time window. Thread-safe via dict with timestamps.
For production, replace with Redis-based implementation.

Limits are configurable via environment variables:
  AI_RATE_LIMIT   — max AI requests per minute per user (default 10)
  API_RATE_LIMIT  — max API requests per minute per user/IP (default 100)
  LOGIN_RATE_LIMIT — max login attempts per minute per IP (default 10)
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
            self._requests[key] = [t for t in self._requests[key] if t > now - self.window_seconds]

            if len(self._requests[key]) >= self.max_requests:
                return False, 0

            self._requests[key].append(now)
            remaining = self.max_requests - len(self._requests[key])
            return True, remaining


def _create_limiters() -> tuple[RateLimiter, RateLimiter, RateLimiter]:
    """Create rate limiter instances using values from Settings.

    Reads AI_RATE_LIMIT, API_RATE_LIMIT, and LOGIN_RATE_LIMIT from the
    application configuration (environment variables / .env file).
    Falls back to sensible defaults if settings cannot be loaded.
    """
    try:
        from app.config import get_settings

        settings = get_settings()
        ai_max = settings.ai_rate_limit
        api_max = settings.api_rate_limit
        login_max = settings.login_rate_limit
    except Exception:
        # Fallback: config not available yet (e.g. during testing or import)
        ai_max = 10
        api_max = 100
        login_max = 10

    return (
        RateLimiter(max_requests=ai_max, window_seconds=60),
        RateLimiter(max_requests=api_max, window_seconds=60),
        RateLimiter(max_requests=login_max, window_seconds=60),
    )


# Global instances — configured from environment variables
ai_limiter, api_limiter, login_limiter = _create_limiters()
