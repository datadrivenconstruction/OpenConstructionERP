# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Tests for the in-process LRU layered on top of the SQLite translation cache.

The LRU exists to amortise SQLite SELECTs across N concurrent match
requests with identical envelopes. These tests verify hit / miss
behaviour and that ``upsert()`` invalidates the LRU so a freshly
written translation is visible on the next ``get()``.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.core.translation import cache as cache_mod


@pytest.fixture(autouse=True)
def _reset_lru() -> None:
    cache_mod._lru_invalidate()
    yield
    cache_mod._lru_invalidate()


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "trcache.db")


@pytest.mark.asyncio
async def test_get_miss_caches_none_sentinel(db_path: str) -> None:
    """A miss writes a None sentinel so the next get() doesn't re-query SQLite."""
    cache = cache_mod.TranslationCache(db_path)
    out1 = await cache.get("hello", "en", "de", "construction")
    assert out1 is None
    stats = cache_mod.lru_stats()
    assert stats["entries"] == 1


@pytest.mark.asyncio
async def test_get_hit_returns_cached_row(db_path: str) -> None:
    """After upsert() the row is returned from cache on subsequent get()."""
    cache = cache_mod.TranslationCache(db_path)
    await cache.upsert(
        text="hello",
        translated_text="hallo",
        source_lang="en",
        target_lang="de",
        domain="construction",
        tier_used="cache",
        confidence=1.0,
    )
    out = await cache.get("hello", "en", "de", "construction")
    assert out is not None
    assert out["translated_text"] == "hallo"


@pytest.mark.asyncio
async def test_upsert_invalidates_lru(db_path: str, monkeypatch) -> None:
    """A get() miss caches None; subsequent upsert() drops the sentinel."""
    cache = cache_mod.TranslationCache(db_path)

    # First get — miss → None sentinel cached.
    assert await cache.get("door", "en", "ru", "construction") is None

    # Now upsert — must invalidate the sentinel so the next get sees the row.
    await cache.upsert(
        text="door",
        translated_text="дверь",
        source_lang="en",
        target_lang="ru",
        domain="construction",
        tier_used="cache",
        confidence=0.95,
    )

    out = await cache.get("door", "en", "ru", "construction")
    assert out is not None
    assert out["translated_text"] == "дверь"


@pytest.mark.asyncio
async def test_lru_amortises_repeated_gets(db_path: str) -> None:
    """50 identical get()s on a populated key should issue 1 SQLite read."""
    cache = cache_mod.TranslationCache(db_path)
    await cache.upsert(
        text="window",
        translated_text="fenster",
        source_lang="en",
        target_lang="de",
        domain="construction",
        tier_used="cache",
        confidence=1.0,
    )

    sqlite_calls = 0
    real_connect = sqlite3.connect

    def _counting_connect(*args, **kwargs):
        nonlocal sqlite_calls
        sqlite_calls += 1
        return real_connect(*args, **kwargs)

    # Drop the LRU so the very first get() actually hits SQLite.
    cache_mod._lru_invalidate()

    import sqlite3 as _sqlite_mod  # noqa: PLC0415

    _orig = _sqlite_mod.connect
    _sqlite_mod.connect = _counting_connect
    try:
        for _ in range(50):
            row = await cache.get("window", "en", "de", "construction")
            assert row is not None
    finally:
        _sqlite_mod.connect = _orig

    # First call hits SQLite once; subsequent 49 are LRU hits → 0 SQLite.
    assert sqlite_calls <= 2, f"too many SQLite reads: {sqlite_calls}"


@pytest.mark.asyncio
async def test_lru_max_size_bound(db_path: str) -> None:
    """LRU stays bounded at the configured maxsize."""
    cache = cache_mod.TranslationCache(db_path)
    # Force a tiny maxsize for the test.
    original = cache_mod._LRU_MAXSIZE
    cache_mod._LRU_MAXSIZE = 4  # type: ignore[assignment]
    try:
        for i in range(20):
            await cache.get(f"text-{i}", "en", "de", "construction")
        stats = cache_mod.lru_stats()
        assert stats["entries"] <= 4
    finally:
        cache_mod._LRU_MAXSIZE = original  # type: ignore[assignment]


def test_lru_invalidate_global() -> None:
    """invalidate(None) drops every entry."""
    cache_mod._lru_put(("a", "en", "de", "x"), None)
    cache_mod._lru_put(("b", "en", "de", "x"), None)
    assert cache_mod.lru_stats()["entries"] == 2
    cache_mod._lru_invalidate()
    assert cache_mod.lru_stats()["entries"] == 0


def test_lru_invalidate_specific_key() -> None:
    """invalidate(key) drops only one entry."""
    k1 = ("a", "en", "de", "x")
    k2 = ("b", "en", "de", "x")
    cache_mod._lru_put(k1, None)
    cache_mod._lru_put(k2, None)
    cache_mod._lru_invalidate(k1)
    stats = cache_mod.lru_stats()
    assert stats["entries"] == 1
