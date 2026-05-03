"""Cascade orchestrator — runs the four translation tiers in order.

Each tier returns either a ``TranslationResult`` (with a confidence score)
or ``None`` (meaning "I can't help, try the next tier"). The cascade
short-circuits on the first hit whose confidence is at or above the
configured threshold for that tier.

Thresholds are *per tier* because the tiers report confidence on different
scales:

* lookup_muse  — 0.8+ (exact phrase) or rapidfuzz score / 100
* lookup_iate  — 0.85+ (curated termbase, treat near-matches conservatively)
* cache        — 1.0 always (the cache only stores past hits)
* llm          — 0.7 default (LLMs sometimes confabulate)
* fallback     — 0.0 (definitionally no translation happened)

The fallback tier is special: it always succeeds, so it never short-circuits
and is always reached on cascade exhaustion.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

# Module-level imports so the cascade orchestrator is patchable from tests
# (``unittest.mock.patch`` looks up the attribute on the cascade module,
# not on the source module — re-binding here makes the wiring explicit).
from app.core.translation.cache import TranslationCache
from app.core.translation.llm_translator import llm_translate
from app.core.translation.lookup import lookup_phrase

logger = logging.getLogger(__name__)


class TierUsed(str, Enum):
    """Identifies which tier produced the translation."""

    LOOKUP_MUSE = "lookup_muse"
    LOOKUP_IATE = "lookup_iate"
    CACHE = "cache"
    LLM = "llm"
    FALLBACK = "fallback"


@dataclass(frozen=True)
class TranslationResult:
    """Outcome of a single ``translate()`` call.

    Attributes:
        translated:   Translated text, or original text on fallback.
        source_lang:  ISO-639 two-letter source code.
        target_lang:  ISO-639 two-letter target code.
        tier_used:    Which tier produced this result.
        confidence:   0.0 - 1.0. 1.0 = certain (cache hit / exact MUSE
                      match), 0.0 = no translation happened (fallback).
        cost_usd:     LLM call cost in USD, ``None`` if no LLM was hit.
    """

    translated: str
    source_lang: str
    target_lang: str
    tier_used: TierUsed
    confidence: float
    cost_usd: float | None = None


# Per-tier confidence thresholds. A tier "wins" only if its result meets
# its threshold; otherwise we fall through to the next tier. Fallback has
# threshold 0.0 so it always succeeds.
#
# Cache threshold is intentionally low (0.5): the cache stores hits from
# every higher tier, including LLM hits at 0.7 confidence. A 1.0 cache
# threshold would reject every LLM-sourced cache row and force the LLM
# to be re-called every request — defeating the cache.
DEFAULT_THRESHOLDS: dict[TierUsed, float] = {
    TierUsed.LOOKUP_MUSE: 0.80,
    TierUsed.LOOKUP_IATE: 0.85,
    TierUsed.CACHE: 0.5,
    TierUsed.LLM: 0.70,
    TierUsed.FALLBACK: 0.0,
}


async def translate(
    text: str,
    source_lang: str,
    target_lang: str,
    *,
    domain: str = "construction",
    user_settings: Any = None,
    thresholds: dict[TierUsed, float] | None = None,
    cache_db_path: str | None = None,
    lookup_root: str | None = None,
) -> TranslationResult:
    """Translate ``text`` from ``source_lang`` to ``target_lang``.

    Args:
        text:           Text to translate. Empty/whitespace returns fallback.
        source_lang:    ISO-639 two-letter code (e.g. "en"). Lower-cased.
        target_lang:    ISO-639 two-letter code (e.g. "bg"). Lower-cased.
        domain:         Domain hint for the LLM prompt and cache key.
                        "construction" by default.
        user_settings:  Optional ``AISettings`` ORM row for the LLM tier.
                        ``None`` is fine — the LLM tier just degrades to a
                        miss and the cascade falls through to fallback.
        thresholds:     Optional per-tier override map; missing keys keep
                        their default values.
        cache_db_path:  Override path for the SQLite cache. Defaults to
                        ``~/.openestimate/translations/cache.db``.
        lookup_root:    Override root for MUSE/IATE TSV files. Defaults to
                        ``~/.openestimate/translations/``.

    Returns:
        ``TranslationResult`` — never raises for normal input. Network /
        filesystem errors are logged at debug level and treated as misses.

    Same-language short-circuit: if ``source_lang == target_lang`` the
    cascade returns immediately with ``tier_used=fallback`` and the
    original text — no I/O, no LLM call.
    """
    src = (source_lang or "").lower().strip()
    tgt = (target_lang or "").lower().strip()
    text_in = (text or "").strip()

    if not text_in:
        return TranslationResult(
            translated=text_in,
            source_lang=src,
            target_lang=tgt,
            tier_used=TierUsed.FALLBACK,
            confidence=0.0,
        )

    # No-op when the requested language equals the source language. Saves
    # a cache write and an LLM call on the very common "already in
    # catalogue language" case.
    if src and tgt and src == tgt:
        return TranslationResult(
            translated=text_in,
            source_lang=src,
            target_lang=tgt,
            tier_used=TierUsed.FALLBACK,
            confidence=1.0,
        )

    th = {**DEFAULT_THRESHOLDS, **(thresholds or {})}

    # ── Tier 1 + 2: lookup tables (MUSE then IATE) ────────────────────
    for tier, dictionary in (
        (TierUsed.LOOKUP_MUSE, "muse"),
        (TierUsed.LOOKUP_IATE, "iate"),
    ):
        try:
            hit = await lookup_phrase(
                text_in, src, tgt, dictionary=dictionary, root=lookup_root
            )
        except Exception as exc:  # pragma: no cover — defensive
            logger.debug("Lookup tier %s failed: %s", tier, exc)
            hit = None
        if hit is not None and hit[1] >= th[tier]:
            translated_text, conf = hit
            await _maybe_cache(
                text_in,
                translated_text,
                src,
                tgt,
                domain,
                tier,
                conf,
                cache_db_path,
            )
            return TranslationResult(
                translated=translated_text,
                source_lang=src,
                target_lang=tgt,
                tier_used=tier,
                confidence=conf,
            )

    # ── Tier 3: SQLite cache ──────────────────────────────────────────
    cache = TranslationCache(cache_db_path)
    try:
        cached = await cache.get(text_in, src, tgt, domain)
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("Cache get failed: %s", exc)
        cached = None
    if cached is not None and cached["confidence"] >= th[TierUsed.CACHE]:
        # Best-effort usage stats. Never fatal.
        try:
            await cache.mark_used(cached["id"])
        except Exception as exc:  # pragma: no cover — defensive
            logger.debug("Cache mark_used failed: %s", exc)
        # Tier reported back to caller is the original tier that
        # produced the row, but with a CACHE marker so observability
        # can see this was a cache hit.
        return TranslationResult(
            translated=cached["translated_text"],
            source_lang=src,
            target_lang=tgt,
            tier_used=TierUsed.CACHE,
            confidence=cached["confidence"],
        )

    # ── Tier 4: LLM ───────────────────────────────────────────────────
    try:
        llm_hit = await llm_translate(
            text_in, src, tgt, domain=domain, user_settings=user_settings
        )
    except Exception as exc:
        # Network / API errors must never bubble up — the fallback tier
        # is the safety net.
        logger.debug("LLM translate failed: %s", exc)
        llm_hit = None
    if llm_hit is not None:
        translated_text, cost_usd, conf = llm_hit
        if conf >= th[TierUsed.LLM]:
            await _maybe_cache(
                text_in,
                translated_text,
                src,
                tgt,
                domain,
                TierUsed.LLM,
                conf,
                cache_db_path,
            )
            return TranslationResult(
                translated=translated_text,
                source_lang=src,
                target_lang=tgt,
                tier_used=TierUsed.LLM,
                confidence=conf,
                cost_usd=cost_usd,
            )

    # ── Tier 5: fallback (always succeeds) ────────────────────────────
    return TranslationResult(
        translated=text_in,
        source_lang=src,
        target_lang=tgt,
        tier_used=TierUsed.FALLBACK,
        confidence=0.0,
    )


async def _maybe_cache(
    text: str,
    translated: str,
    src: str,
    tgt: str,
    domain: str,
    tier: TierUsed,
    confidence: float,
    cache_db_path: str | None,
) -> None:
    """Persist a successful translation. Errors are logged & swallowed."""
    try:
        cache = TranslationCache(cache_db_path)
        await cache.upsert(
            text=text,
            translated_text=translated,
            source_lang=src,
            target_lang=tgt,
            domain=domain,
            tier_used=tier.value,
            confidence=confidence,
        )
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("Cache upsert failed: %s", exc)
