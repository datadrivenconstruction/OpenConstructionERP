"""Translation service — element → catalog cross-lingual normalisation.

Public entrypoint:

    from app.core.translation import translate, TranslationResult

    result = await translate(
        "Concrete C30/37 Wall",
        source_lang="en",
        target_lang="bg",
        domain="construction",
    )

The cascade runs four tiers in order and short-circuits on the first hit
that meets the per-tier confidence threshold (see ``cascade.DEFAULT_THRESHOLDS``):

    1. Lookup tables (MUSE bilingual + IATE EU termbase) on disk
    2. Async SQLite cache of past translations
    3. LLM translation via the configured AI provider
    4. Fallback — return the original text unchanged

Used by the element-to-catalog match feature (see ``app.core.match_service``)
to translate element descriptions from a source language (e.g. Revit material
names in English) into the language of the regional CWICR catalogue
(e.g. Bulgarian for ``BG_SOFIA``, German for ``DE_BERLIN``).

Direction is one-way: the catalogue stays in its source language, only the
element side is translated.
"""

from __future__ import annotations

from app.core.translation.cascade import (
    DEFAULT_THRESHOLDS,
    TierUsed,
    TranslationResult,
    translate,
)

__all__ = [
    "DEFAULT_THRESHOLDS",
    "TierUsed",
    "TranslationResult",
    "translate",
]
