"""Simple caching layer with in-memory fallback.

Uses Redis if available, falls back to in-memory LRU cache.
Thread-safe. TTL-based expiration.

Usage:
    from app.core.cache import cache

    # Set/get
    await cache.set("key", {"data": 123}, ttl=300)
    value = await cache.get("key")

    # Decorator
    @cached(ttl=60, prefix="costs")
    async def search_costs(query: str) -> list:
        ...
"""

import json
import logging
import time
from collections import OrderedDict
from functools import wraps
from threading import Lock
from typing import Any, Callable

logger = logging.getLogger(__name__)


class _RateLimitedLogger:
    """Collapse repeated warnings so an outage does not spam the log.

    Keyed by ``(operation, error_type)`` — if the same pair is emitted
    within ``window_seconds`` we skip the log line and bump an in-memory
    counter that gets flushed the next time the pair is logged.  That
    way a Redis that's been down for 30 minutes produces one line per
    minute per operation instead of thousands.
    """

    def __init__(self, window_seconds: float = 60.0) -> None:
        self._window = window_seconds
        self._last_emit: dict[tuple[str, str], float] = {}
        self._skipped: dict[tuple[str, str], int] = {}
        self._lock = Lock()

    def warn(self, operation: str, key: str, exc: BaseException) -> None:
        err_type = type(exc).__name__
        bucket_key = (operation, err_type)
        now = time.time()
        with self._lock:
            last = self._last_emit.get(bucket_key, 0.0)
            if now - last < self._window:
                self._skipped[bucket_key] = self._skipped.get(bucket_key, 0) + 1
                return
            skipped = self._skipped.pop(bucket_key, 0)
            self._last_emit[bucket_key] = now
        suffix = f" (+{skipped} similar in the last {int(self._window)}s)" if skipped else ""
        logger.warning(
            "cache %s failed on key=%r: %s: %s%s",
            operation,
            key,
            err_type,
            exc,
            suffix,
        )


_rate_limited_warn = _RateLimitedLogger()


class InMemoryCache:
    """LRU cache with TTL expiration. No external dependencies."""

    def __init__(self, max_size: int = 1000) -> None:
        self.max_size = max_size
        self._store: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._lock = Lock()

    async def get(self, key: str) -> Any | None:
        with self._lock:
            if key not in self._store:
                return None
            value, expires_at = self._store[key]
            if expires_at and time.time() > expires_at:
                del self._store[key]
                return None
            self._store.move_to_end(key)
            return value

    async def set(self, key: str, value: Any, ttl: int = 300) -> None:
        expires_at = time.time() + ttl if ttl > 0 else 0
        with self._lock:
            self._store[key] = (value, expires_at)
            self._store.move_to_end(key)
            # Evict oldest if over max size
            while len(self._store) > self.max_size:
                self._store.popitem(last=False)

    async def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    async def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def stats(self) -> dict[str, Any]:
        with self._lock:
            now = time.time()
            active = sum(1 for _, (_, exp) in self._store.items() if not exp or exp > now)
            return {
                "engine": "in-memory",
                "total_keys": len(self._store),
                "active_keys": active,
                "max_size": self.max_size,
            }


class RedisCache:
    """Redis-backed cache. Falls back to in-memory if Redis unavailable."""

    def __init__(self) -> None:
        self._redis: Any | None = None
        self._fallback = InMemoryCache()

    async def _get_redis(self) -> Any | None:
        if self._redis is not None:
            return self._redis or None
        try:
            from app.config import get_settings

            settings = get_settings()
            if not settings.redis_url:
                return None
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(settings.redis_url, decode_responses=True)
            await self._redis.ping()
            logger.info("Redis cache connected: %s", settings.redis_url)
            return self._redis
        except Exception as exc:  # noqa: BLE001 — we want the reason visible once
            # Connect-time failure is logged once at INFO (it's normal in dev
            # where Redis is not running); further per-op failures go through
            # the rate-limited warner so the log stays readable.
            logger.info(
                "Redis not available (%s: %s) — using in-memory cache",
                type(exc).__name__,
                exc,
            )
            self._redis = False  # Mark as unavailable
            return None

    async def get(self, key: str) -> Any | None:
        r = await self._get_redis()
        if r:
            try:
                val = await r.get(f"oe:{key}")
                return json.loads(val) if val else None
            except Exception as exc:  # noqa: BLE001 — funnel all errors through the rate limiter
                _rate_limited_warn.warn("get", key, exc)
        return await self._fallback.get(key)

    async def set(self, key: str, value: Any, ttl: int = 300) -> None:
        r = await self._get_redis()
        if r:
            try:
                await r.setex(f"oe:{key}", ttl, json.dumps(value, default=str))
                return
            except Exception as exc:  # noqa: BLE001
                _rate_limited_warn.warn("set", key, exc)
        await self._fallback.set(key, value, ttl)

    async def delete(self, key: str) -> None:
        r = await self._get_redis()
        if r:
            try:
                await r.delete(f"oe:{key}")
                return
            except Exception as exc:  # noqa: BLE001
                _rate_limited_warn.warn("delete", key, exc)
        await self._fallback.delete(key)

    async def clear(self) -> None:
        await self._fallback.clear()

    def stats(self) -> dict[str, Any]:
        if self._redis and self._redis is not False:
            return {"engine": "redis", "status": "connected"}
        return self._fallback.stats()


# Global cache instance
cache = RedisCache()


def cached(ttl: int = 300, prefix: str = "") -> Callable:
    """Decorator for caching async function results.

    Args:
        ttl: Time-to-live in seconds (default 5 minutes).
        prefix: Key prefix for namespacing.
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Build cache key from function name + args
            key_parts = [prefix or func.__name__]
            key_parts.extend(str(a) for a in args)
            key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
            key = ":".join(key_parts)

            # Check cache
            result = await cache.get(key)
            if result is not None:
                return result

            # Call function and cache result
            result = await func(*args, **kwargs)
            if result is not None:
                await cache.set(key, result, ttl)
            return result

        return wrapper

    return decorator
