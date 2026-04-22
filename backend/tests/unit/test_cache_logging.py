"""Unit tests for cache-layer error logging (v2.3.1).

Before v2.3.1 the Redis cache silently swallowed every exception with
``except: pass``.  Outages went invisible, making failed invalidations
and stale-read incidents impossible to root-cause from logs.

These tests cover the new behaviour:

* Errors on get/set/delete are logged at WARNING with key + exception.
* Repeated errors within 60 s collapse into a single line (no log
  spam during a prolonged outage).
* The fallback in-memory cache still serves the request regardless.
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.cache import RedisCache, _RateLimitedLogger

# ---------------------------------------------------------------------------
# Rate-limited logger
# ---------------------------------------------------------------------------


class TestRateLimitedLogger:
    def test_first_call_emits_warning(self, caplog):
        limiter = _RateLimitedLogger(window_seconds=60.0)
        with caplog.at_level(logging.WARNING, logger="app.core.cache"):
            limiter.warn("get", "costs:123", ConnectionError("refused"))
        assert len(caplog.records) == 1
        assert "costs:123" in caplog.records[0].getMessage()
        assert "ConnectionError" in caplog.records[0].getMessage()
        assert "refused" in caplog.records[0].getMessage()

    def test_second_call_within_window_is_suppressed(self, caplog):
        limiter = _RateLimitedLogger(window_seconds=60.0)
        with caplog.at_level(logging.WARNING, logger="app.core.cache"):
            limiter.warn("get", "k1", ConnectionError("boom"))
            limiter.warn("get", "k2", ConnectionError("boom"))
            limiter.warn("get", "k3", ConnectionError("boom"))
        # Only first line was emitted.
        assert len(caplog.records) == 1

    def test_different_error_types_log_separately(self, caplog):
        limiter = _RateLimitedLogger(window_seconds=60.0)
        with caplog.at_level(logging.WARNING, logger="app.core.cache"):
            limiter.warn("get", "k1", ConnectionError("refused"))
            limiter.warn("get", "k2", TimeoutError("slow"))
        assert len(caplog.records) == 2

    def test_second_call_after_window_emits_with_skipped_count(self, caplog):
        limiter = _RateLimitedLogger(window_seconds=0.01)
        with caplog.at_level(logging.WARNING, logger="app.core.cache"):
            limiter.warn("get", "k1", ConnectionError("a"))
            limiter.warn("get", "k2", ConnectionError("b"))
            limiter.warn("get", "k3", ConnectionError("c"))
            import time

            time.sleep(0.05)  # Window expires
            limiter.warn("get", "k4", ConnectionError("d"))
        messages = [rec.getMessage() for rec in caplog.records]
        assert len(messages) == 2
        assert "+2 similar" in messages[1]


# ---------------------------------------------------------------------------
# RedisCache error handling
# ---------------------------------------------------------------------------


@pytest.fixture
def fresh_cache(monkeypatch):
    """Isolated cache instance that does NOT touch real Redis."""
    c = RedisCache()
    # Reset the module-level rate limiter so it does not absorb warnings
    # emitted by previous tests (pytest-xdist runs tests in order inside
    # a worker, but the limiter keeps state across tests otherwise).
    from app.core import cache as cache_mod

    cache_mod._rate_limited_warn = _RateLimitedLogger(window_seconds=60.0)
    return c


class TestRedisCacheErrorPaths:
    @pytest.mark.asyncio
    async def test_get_error_is_logged_and_falls_back(self, fresh_cache, caplog):
        # Pretend Redis is connected but every call raises.
        mock_redis = MagicMock()
        mock_redis.get = AsyncMock(side_effect=ConnectionError("refused"))
        fresh_cache._redis = mock_redis
        # Seed the fallback so we can verify it served the value.
        await fresh_cache._fallback.set("demo", {"val": 1}, ttl=10)

        with caplog.at_level(logging.WARNING, logger="app.core.cache"):
            result = await fresh_cache.get("demo")

        assert result == {"val": 1}
        assert any("cache get failed" in rec.getMessage() for rec in caplog.records)
        assert any("demo" in rec.getMessage() for rec in caplog.records)

    @pytest.mark.asyncio
    async def test_set_error_is_logged_and_falls_back(self, fresh_cache, caplog):
        mock_redis = MagicMock()
        mock_redis.setex = AsyncMock(side_effect=ConnectionError("refused"))
        fresh_cache._redis = mock_redis

        with caplog.at_level(logging.WARNING, logger="app.core.cache"):
            await fresh_cache.set("k", {"v": 1})

        # Fallback kept the value regardless of Redis failure.
        assert await fresh_cache._fallback.get("k") == {"v": 1}
        assert any("cache set failed" in rec.getMessage() for rec in caplog.records)

    @pytest.mark.asyncio
    async def test_delete_error_is_logged_and_falls_back(self, fresh_cache, caplog):
        mock_redis = MagicMock()
        mock_redis.delete = AsyncMock(side_effect=ConnectionError("refused"))
        fresh_cache._redis = mock_redis
        await fresh_cache._fallback.set("x", 1, ttl=10)

        with caplog.at_level(logging.WARNING, logger="app.core.cache"):
            await fresh_cache.delete("x")

        # Fallback delete still runs.
        assert await fresh_cache._fallback.get("x") is None
        assert any("cache delete failed" in rec.getMessage() for rec in caplog.records)

    @pytest.mark.asyncio
    async def test_unavailable_redis_is_logged_once_at_info(self, caplog):
        """Connect-time failure should log at INFO (not spammy WARNING).

        We force ``_get_redis`` to raise by handing it a settings object
        whose ``redis_url`` points at ``ModuleNotFoundError`` territory —
        the catch-all branch in the cache module turns any import / ping
        failure into a single INFO line, not a WARNING flood.
        """
        c = RedisCache()

        class _StubSettings:
            redis_url = "redis://stub.invalid:9999/0"

        with (
            caplog.at_level(logging.INFO, logger="app.core.cache"),
            patch("app.core.cache.logger") as mock_logger,
            patch(
                "app.config.get_settings",
                return_value=_StubSettings(),
            ),
        ):
            # Force the ``import redis.asyncio`` line to raise as if the
            # dep were missing entirely — covers both "redis not
            # installed" and "Redis daemon down" from the log caller's
            # POV: a single INFO line, not a WARNING flood.
            mock_logger.info = MagicMock()
            mock_logger.warning = MagicMock()
            with patch.dict("sys.modules", {"redis.asyncio": None}):
                result = await c._get_redis()
        assert result is None
        # The cache logger's .info() was called once with the "not
        # available" message — we assert on the mock rather than caplog
        # because we patched the logger object to isolate this test
        # from the module-level logging config.
        assert mock_logger.info.called
        info_msg = mock_logger.info.call_args[0][0]
        assert "not available" in info_msg

    @pytest.mark.asyncio
    async def test_outage_flood_collapses_to_one_line(self, fresh_cache, caplog):
        mock_redis = MagicMock()
        mock_redis.get = AsyncMock(side_effect=ConnectionError("refused"))
        fresh_cache._redis = mock_redis

        with caplog.at_level(logging.WARNING, logger="app.core.cache"):
            for i in range(50):
                await fresh_cache.get(f"key-{i}")

        # Window is 60 s — all 50 should collapse into the first one.
        warnings = [r for r in caplog.records if "cache get failed" in r.getMessage()]
        assert len(warnings) == 1
