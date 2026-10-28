"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the translation cascade.

These tests are pure unit — no real network, no real LLM. The cascade
modules accept a ``lookup_root`` override so each test can point at its
own ``tmp_path`` for MUSE/IATE dictionaries and stay isolated. The
translation-memory cache lives in the shared PostgreSQL test database;
tests use distinct text envelopes so their cache rows do not collide,
and the in-process LRU is reset between tests.

LLM tier is exercised by monkey-patching ``llm_translate`` so we never
hit a real API. The tests verify cascade ordering, short-circuiting,
phrase-aware MUSE lookup, cache hit on second call, and graceful
fallback when nothing else fires.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_asyncio

from app.core.translation import TierUsed, translate
from app.core.translation import cache as cache_mod
from app.core.translation.cache import TranslationCache
from app.core.translation.lookup import lookup_phrase


@pytest_asyncio.fixture(autouse=True)
async def _reset_translation_lru() -> AsyncGenerator[None, None]:
    """Reset the in-process LRU and the shared engine pool around each test.

    The cache now lives in the shared main database, so the LRU is keyed
    on a constant ``"pg"`` namespace rather than a per-test file path.
    Resetting it keeps the in-process layer from leaking cached rows or
    ``None`` sentinels across tests. Disposing the global engine drops the
    pooled asyncpg connections so the next test (run on its own event loop
    by pytest-asyncio) opens fresh connections on that loop.
    """
    from app.database import engine

    cache_mod._lru_invalidate()
    yield
    cache_mod._lru_invalidate()
    await engine.dispose()


# ── Helpers ────────────────────────────────────────────────────────────


def _write_muse(root: Path, src: str, tgt: str, rows: list[tuple[str, str]]) -> None:
    """Drop a MUSE TSV at ``{root}/muse/{src}-{tgt}.tsv``."""
    d = root / "muse"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{src}-{tgt}.tsv"
    with path.open("w", encoding="utf-8") as fh:
        fh.write("# test fixture\n")
        for s, t in rows:
            fh.write(f"{s}\t{t}\t1.0\n")


@pytest.fixture
def lookup_root(tmp_path: Path) -> Path:
    """Per-test dictionary root. Tests populate ``muse/`` as needed."""
    return tmp_path / "translations"


@pytest.fixture
def cache_path(tmp_path: Path) -> str:
    """Deprecated ``cache_db_path`` value, retained for the cascade signature.

    The translation-memory cache now lives in the shared PostgreSQL test
    database, so this value is ignored by ``translate()``. It is kept only
    so the existing ``cache_db_path=`` call sites stay valid while we
    exercise the cascade's other behaviour.
    """
    return str(tmp_path / "ignored-cache-path")


# ── Lookup phrase-aware behaviour ──────────────────────────────────────


@pytest.mark.asyncio
class TestLookup:
    async def test_full_phrase_exact_match_wins(self, lookup_root: Path) -> None:
        _write_muse(
            lookup_root,
            "en",
            "de",
            [
                ("concrete c30/37 wall", "Stahlbetonwand C30/37"),
                ("concrete", "Beton"),
                ("wall", "Wand"),
            ],
        )
        hit = await lookup_phrase(
            "Concrete C30/37 Wall",
            "en",
            "de",
            dictionary="muse",
            root=str(lookup_root),
        )
        assert hit is not None
        translated, conf = hit
        # Full-phrase hit wins over per-token translation.
        assert translated == "Stahlbetonwand C30/37"
        assert conf >= 0.95

    async def test_per_token_fallback_preserves_codes(self, lookup_root: Path) -> None:
        _write_muse(
            lookup_root,
            "en",
            "de",
            [
                ("concrete", "Beton"),
                ("wall", "Wand"),
            ],
        )
        hit = await lookup_phrase(
            "Concrete C30/37 Wall",
            "en",
            "de",
            dictionary="muse",
            root=str(lookup_root),
        )
        assert hit is not None
        translated, conf = hit
        # Codes (C30/37) preserved verbatim, lexical tokens translated.
        assert "C30/37" in translated
        assert "Beton" in translated
        assert "Wand" in translated
        # 2/2 lexical tokens hit + 1 code = full coverage = high conf.
        assert conf >= 0.8

    async def test_low_coverage_returns_none(self, lookup_root: Path) -> None:
        _write_muse(
            lookup_root,
            "en",
            "de",
            [("concrete", "Beton")],
        )
        # Only 1 of 4 lexical tokens hit → coverage 0.25 < 0.5 → miss.
        hit = await lookup_phrase(
            "thick reinforced concrete partition",
            "en",
            "de",
            dictionary="muse",
            root=str(lookup_root),
        )
        assert hit is None

    async def test_missing_file_returns_none(self, lookup_root: Path) -> None:
        # No file written → lookup is a clean miss, not an exception.
        hit = await lookup_phrase(
            "anything",
            "en",
            "fr",
            dictionary="muse",
            root=str(lookup_root),
        )
        assert hit is None


# ── Cascade ordering ───────────────────────────────────────────────────


@pytest.mark.asyncio
class TestCascade:
    async def test_short_circuits_on_muse_hit(self, lookup_root: Path, cache_path: str) -> None:
        _write_muse(
            lookup_root,
            "en",
            "bg",
            [("concrete wall", "Бетонна стена")],
        )

        # Patch the LLM tier to an explosion — if cascade reaches it the
        # test fails immediately. Proves Tier 1 short-circuits.
        async def _explode(*args, **kwargs):  # noqa: ANN001, ANN002
            raise AssertionError("LLM tier must not be reached on MUSE hit")

        with patch(
            "app.core.translation.cascade.llm_translate",
            side_effect=Exception("would also fail"),
        ):
            result = await translate(
                "Concrete Wall",
                source_lang="en",
                target_lang="bg",
                cache_db_path=cache_path,
                lookup_root=str(lookup_root),
            )
        assert result.tier_used == TierUsed.LOOKUP_MUSE
        assert "Бетонна" in result.translated

    async def test_same_language_short_circuits_to_fallback(self, lookup_root: Path, cache_path: str) -> None:
        result = await translate(
            "Concrete Wall",
            source_lang="en",
            target_lang="en",
            cache_db_path=cache_path,
            lookup_root=str(lookup_root),
        )
        assert result.tier_used == TierUsed.FALLBACK
        assert result.translated == "Concrete Wall"
        # Same-language hit: confidence is 1.0 (the text is already
        # in the target language).
        assert result.confidence == 1.0

    async def test_fallback_returns_original_text(self, lookup_root: Path, cache_path: str) -> None:
        # No MUSE/IATE files, no LLM, no settings — must fall through to fallback.
        result = await translate(
            "Reinforced Slab",
            source_lang="en",
            target_lang="bg",
            cache_db_path=cache_path,
            lookup_root=str(lookup_root),
        )
        assert result.tier_used == TierUsed.FALLBACK
        assert result.translated == "Reinforced Slab"
        assert result.confidence == 0.0

    async def test_llm_tier_used_when_lookup_misses(self, lookup_root: Path, cache_path: str) -> None:
        async def _fake_llm(text, src, tgt, *, domain, user_settings):  # noqa: ANN001
            return ("Стоманобетонна плоча", 0.0001, 0.9)

        with patch(
            "app.core.translation.cascade.llm_translate",
            side_effect=_fake_llm,
        ):
            result = await translate(
                "Reinforced Slab",
                source_lang="en",
                target_lang="bg",
                user_settings=object(),
                cache_db_path=cache_path,
                lookup_root=str(lookup_root),
            )
        assert result.tier_used == TierUsed.LLM
        assert result.translated == "Стоманобетонна плоча"
        assert result.cost_usd is not None
        assert result.confidence >= 0.7

    async def test_cache_hit_on_second_call(self, lookup_root: Path, cache_path: str) -> None:
        calls: list[tuple] = []

        async def _fake_llm(text, src, tgt, *, domain, user_settings):  # noqa: ANN001
            calls.append((text, src, tgt))
            return ("Кофраж", 0.0001, 0.9)

        # First call should hit the LLM and persist in the cache.
        with patch(
            "app.core.translation.cascade.llm_translate",
            side_effect=_fake_llm,
        ):
            r1 = await translate(
                "Formwork",
                source_lang="en",
                target_lang="bg",
                user_settings=object(),
                cache_db_path=cache_path,
                lookup_root=str(lookup_root),
            )
        assert r1.tier_used == TierUsed.LLM
        assert len(calls) == 1

        # Second call must read from the cache — LLM patch raises if hit.
        async def _explode(*args, **kwargs):  # noqa: ANN001, ANN002
            raise AssertionError("LLM tier must not be reached on cache hit")

        with patch(
            "app.core.translation.cascade.llm_translate",
            side_effect=_explode,
        ):
            r2 = await translate(
                "Formwork",
                source_lang="en",
                target_lang="bg",
                user_settings=object(),
                cache_db_path=cache_path,
                lookup_root=str(lookup_root),
            )
        assert r2.tier_used == TierUsed.CACHE
        assert r2.translated == "Кофраж"
        # Same call count — second translate didn't reach the LLM.
        assert len(calls) == 1

    async def test_cache_shared_regardless_of_path(self, tmp_path: Path, lookup_root: Path) -> None:
        """The cache is one shared DB store; the ``cache_db_path`` arg is ignored.

        Populating the cache through one (ignored) ``cache_db_path`` value
        and then reading it back through a different one must still hit the
        same shared PostgreSQL store — the per-file isolation of the old
        SQLite cache no longer exists.
        """
        cache_a = str(tmp_path / "a.db")
        cache_b = str(tmp_path / "b.db")

        async def _fake_llm(text, src, tgt, *, domain, user_settings):  # noqa: ANN001
            return ("Sdelka", 0.0001, 0.9)

        # Populate the shared cache via the first (ignored) path value.
        with patch(
            "app.core.translation.cascade.llm_translate",
            side_effect=_fake_llm,
        ):
            await translate(
                "SharedCacheProbe",
                source_lang="en",
                target_lang="bg",
                user_settings=object(),
                cache_db_path=cache_a,
                lookup_root=str(lookup_root),
            )

        # A different path value must still resolve to the same shared store,
        # so the LLM tier must NOT be reached on the second call.
        async def _explode(*args, **kwargs):  # noqa: ANN001, ANN002
            raise AssertionError("LLM tier must not be reached — cache is shared")

        with patch(
            "app.core.translation.cascade.llm_translate",
            side_effect=_explode,
        ):
            r = await translate(
                "SharedCacheProbe",
                source_lang="en",
                target_lang="bg",
                user_settings=object(),
                cache_db_path=cache_b,
                lookup_root=str(lookup_root),
            )

        assert r.tier_used == TierUsed.CACHE
        assert r.translated == "Sdelka"


# ── Cache primitives ───────────────────────────────────────────────────


@pytest.mark.asyncio
class TestCacheStore:
    # The cache is one shared PostgreSQL store, so each test uses a distinct
    # text envelope to keep its row from colliding with the others.

    async def test_upsert_then_get(self) -> None:
        c = TranslationCache()
        await c.upsert(
            text="CacheStore-Wall",
            translated_text="Wand",
            source_lang="en",
            target_lang="de",
            domain="construction",
            tier_used="llm",
            confidence=0.9,
        )
        row = await c.get("CacheStore-Wall", "en", "de", "construction")
        assert row is not None
        assert row["translated_text"] == "Wand"
        assert row["tier_used"] == "llm"
        assert row["usage_count"] == 1

    async def test_upsert_keeps_higher_confidence(self) -> None:
        c = TranslationCache()
        await c.upsert(
            text="CacheStore-Conf",
            translated_text="Wand-A",
            source_lang="en",
            target_lang="de",
            domain="construction",
            tier_used="llm",
            confidence=0.6,
        )
        await c.upsert(
            text="CacheStore-Conf",
            translated_text="Wand-B",
            source_lang="en",
            target_lang="de",
            domain="construction",
            tier_used="lookup_muse",
            confidence=0.95,
        )
        row = await c.get("CacheStore-Conf", "en", "de", "construction")
        assert row is not None
        # Higher-confidence translation wins.
        assert row["translated_text"] == "Wand-B"
        assert row["tier_used"] == "lookup_muse"
        # And usage_count incremented.
        assert row["usage_count"] == 2

    async def test_mark_used_bumps_count(self) -> None:
        c = TranslationCache()
        await c.upsert(
            text="CacheStore-Floor",
            translated_text="Boden",
            source_lang="en",
            target_lang="de",
            domain="construction",
            tier_used="cache",
            confidence=1.0,
        )
        row = await c.get("CacheStore-Floor", "en", "de", "construction")
        assert row is not None
        await c.mark_used(row["id"])
        await c.mark_used(row["id"])
        row2 = await c.get("CacheStore-Floor", "en", "de", "construction")
        assert row2 is not None
        assert row2["usage_count"] == 3
