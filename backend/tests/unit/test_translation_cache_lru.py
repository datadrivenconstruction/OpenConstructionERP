# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Tests for the in-process LRU layered on the PostgreSQL translation cache.

The LRU exists to amortise DB SELECTs across N concurrent match requests
with identical envelopes. These tests verify hit / miss behaviour and
that ``upsert()`` invalidates the LRU so a freshly written translation is
visible on the next ``get()``. They run against the test PostgreSQL DB
provided by ``conftest``; the cache's lazy table-ensure means a bare
``TranslationCache()`` works without a full app startup.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio

from app.core.translation import cache as cache_mod


@pytest_asyncio.fixture(autouse=True)
async def _reset_lru() -> AsyncGenerator[None, None]:
    """Reset the in-process LRU and the shared engine pool around each test.

    The cache reads/writes through the module-global ``app.database.engine``.
    pytest-asyncio runs each test on its own event loop, so the pooled
    asyncpg connections from a previous test belong to a closed loop;
    disposing the engine forces the next test to open fresh connections on
    its own loop.
    """
    from app.database import engine

    cache_mod._lru_invalidate()
    yield
    cache_mod._lru_invalidate()
    await engine.dispose()


@pytest.mark.asyncio
async def test_get_miss_caches_none_sentinel() -> None:
    """A miss writes a None sentinel so the next get() doesn't re-query the DB."""
    cache = cache_mod.TranslationCache()
    out1 = await cache.get("hello lru miss", "en", "de", "construction")
    assert out1 is None
    stats = cache_mod.lru_stats()
    assert stats["entries"] == 1


@pytest.mark.asyncio
async def test_get_hit_returns_cached_row() -> None:
    """After upsert() the row is returned from cache on subsequent get()."""
    cache = cache_mod.TranslationCache()
    await cache.upsert(
        text="hello lru hit",
        translated_text="hallo",
        source_lang="en",
        target_lang="de",
        domain="construction",
        tier_used="cache",
        confidence=1.0,
    )
    out = await cache.get("hello lru hit", "en", "de", "construction")
    assert out is not None
    assert out["translated_text"] == "hallo"


@pytest.mark.asyncio
async def test_upsert_invalidates_lru() -> None:
    """A get() miss caches None; subsequent upsert() drops the sentinel."""
    cache = cache_mod.TranslationCache()

    # First get — miss → None sentinel cached.
    assert await cache.get("door lru", "en", "ru", "construction") is None

    # Now upsert — must invalidate the sentinel so the next get sees the row.
    await cache.upsert(
        text="door lru",
        translated_text="дверь",
        source_lang="en",
        target_lang="ru",
        domain="construction",
        tier_used="cache",
        confidence=0.95,
    )

    out = await cache.get("door lru", "en", "ru", "construction")
    assert out is not None
    assert out["translated_text"] == "дверь"


@pytest.mark.asyncio
async def test_lru_absorbs_repeated_gets() -> None:
    """After one populated get(), the LRU caches the key and serves repeats.

    50 further get()s on the same envelope return the row without growing
    the LRU beyond the single cached key — proof the LRU absorbs repeats
    rather than re-reading the DB each time.
    """
    cache = cache_mod.TranslationCache()
    await cache.upsert(
        text="window lru",
        translated_text="fenster",
        source_lang="en",
        target_lang="de",
        domain="construction",
        tier_used="cache",
        confidence=1.0,
    )

    # Drop the LRU so the very first get() actually populates it from the DB.
    cache_mod._lru_invalidate()

    h = cache_mod._hash("window lru")
    key = (cache_mod._LRU_NAMESPACE, h, "en", "de", "construction")

    first = await cache.get("window lru", "en", "de", "construction")
    assert first is not None

    # The populated key is now resident in the LRU.
    hit, cached = cache_mod._lru_get(key)
    assert hit is True
    assert cached is not None
    assert cached["translated_text"] == "fenster"
    assert cache_mod.lru_stats()["entries"] == 1

    # 50 more get()s all return the row and never grow the LRU past one key.
    for _ in range(50):
        row = await cache.get("window lru", "en", "de", "construction")
        assert row is not None
        assert row["translated_text"] == "fenster"
    assert cache_mod.lru_stats()["entries"] == 1


@pytest.mark.asyncio
async def test_lru_max_size_bound() -> None:
    """LRU stays bounded at the configured maxsize."""
    cache = cache_mod.TranslationCache()
    # Force a tiny maxsize for the test.
    original = cache_mod._LRU_MAXSIZE
    cache_mod._LRU_MAXSIZE = 4  # type: ignore[assignment]
    try:
        for i in range(20):
            await cache.get(f"text-bound-{i}", "en", "de", "construction")
        stats = cache_mod.lru_stats()
        assert stats["entries"] <= 4
    finally:
        cache_mod._LRU_MAXSIZE = original  # type: ignore[assignment]


def test_lru_invalidate_global() -> None:
    """invalidate(None) drops every entry."""
    cache_mod._lru_put(("pg", "a", "en", "de", "x"), None)
    cache_mod._lru_put(("pg", "b", "en", "de", "x"), None)
    assert cache_mod.lru_stats()["entries"] == 2
    cache_mod._lru_invalidate()
    assert cache_mod.lru_stats()["entries"] == 0


def test_lru_invalidate_specific_key() -> None:
    """invalidate(key) drops only one entry."""
    k1 = ("pg", "a", "en", "de", "x")
    k2 = ("pg", "b", "en", "de", "x")
    cache_mod._lru_put(k1, None)
    cache_mod._lru_put(k2, None)
    cache_mod._lru_invalidate(k1)
    stats = cache_mod.lru_stats()
    assert stats["entries"] == 1
