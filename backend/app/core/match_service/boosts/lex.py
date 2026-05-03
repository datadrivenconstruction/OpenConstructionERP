# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Lexical boost — rewards near-verbatim description overlap.

Vector search excels at semantic similarity but can promote candidates
whose surface text shares little with the element. ``rapidfuzz``
``token_set_ratio`` measures exactly that surface overlap (independent
of token order, which is what we want for free-form CWICR descriptions
like ``"Stahlbetonwand C30/37, 24cm"``).

Cutoffs:
    * score ≥ 80 → +0.05 (high — almost a verbatim phrase match)
    * score ≥ 60 → +0.02 (medium — meaningful term overlap)
    * score < 60 → no contribution
"""

from __future__ import annotations

from typing import Any

from app.core.match_service.config import (
    BOOST_WEIGHTS,
    LEX_HIGH_THRESHOLD,
    LEX_MEDIUM_THRESHOLD,
)
from app.core.match_service.envelope import ElementEnvelope, MatchCandidate


def _token_set_ratio(left: str, right: str) -> int:
    """Wrap rapidfuzz so we degrade to 0 if the optional dep is missing.

    rapidfuzz is already in base deps (``backend/pyproject.toml``), so
    this should always succeed in production. The fallback is a
    safety net for stripped-down test environments.
    """
    if not left.strip() or not right.strip():
        return 0
    try:
        from rapidfuzz import fuzz  # noqa: PLC0415
    except ImportError:
        # Defensive — keep the matcher functional without rapidfuzz.
        return 0
    return int(fuzz.token_set_ratio(left, right))


def boost(
    envelope: ElementEnvelope,
    candidate: MatchCandidate,
    settings: Any,  # noqa: ARG001
) -> dict[str, float]:
    """Add lex-overlap boost based on rapidfuzz token_set_ratio."""
    description = candidate.description or ""
    # Use the *translated* envelope text where available — the matcher
    # writes the translated description back into ``envelope.description``
    # before ranking so this boost compares apples-to-apples with the
    # candidate (which is in the catalogue language).
    query = envelope.description or envelope.category or ""
    if not description or not query:
        return {}

    score = _token_set_ratio(query, description)
    if score >= LEX_HIGH_THRESHOLD:
        return {"lex_high": BOOST_WEIGHTS.lex_high}
    if score >= LEX_MEDIUM_THRESHOLD:
        return {"lex_medium": BOOST_WEIGHTS.lex_medium}
    return {}
