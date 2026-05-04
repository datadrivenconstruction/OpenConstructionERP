# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Universal request/response types for the element-to-CWICR matcher.

Every source pipeline (BIM, PDF, DWG, photo) feeds the same
:class:`ElementEnvelope` into the matcher. The envelope is intentionally
loose-typed (``properties`` and ``quantities`` are free-form dicts) so a
new source extractor can ship without touching this schema.

Response candidates carry both the raw cosine score and the boosted
final score so the UI can show "why" each candidate ranks where it
does (the ``boosts_applied`` dict).
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.match_service.config import (
    CONFIDENCE_HIGH_THRESHOLD,
    CONFIDENCE_MEDIUM_THRESHOLD,
)
from app.core.translation import TranslationResult

SourceType = Literal["bim", "pdf", "dwg", "photo"]
ConfidenceBand = Literal["high", "medium", "low"]


class ElementEnvelope(BaseModel):
    """Source-agnostic representation of one estimable element.

    The envelope captures everything the matcher needs to rank CWICR
    candidates: a free-form description, source language, optional
    quantitative properties and pre-classification hints from the
    upstream extractor.

    Attributes:
        source: Which pipeline produced this element.
        source_lang: ISO-639 two-letter code (e.g. ``"en"``, ``"de"``).
            The matcher translates the description into the project's
            ``target_language`` before searching.
        category: Free-form element type (e.g. ``"wall"``, ``"door"``,
            ``"hvac_duct"``). Used in query construction and boost
            heuristics.
        description: Human-readable summary the matcher embeds.
        properties: Material, fire-rating, finish, etc. Stringified into
            the query text but kept in raw form so boosts can see them.
        quantities: ``length_m`` / ``area_m2`` / ``volume_m3`` / etc.
            Used to infer the expected unit when ``unit_hint`` is absent.
        unit_hint: Preferred CWICR unit (``"m"``, ``"m2"``, ``"m3"``,
            ``"pcs"``). When present, drives the unit boost.
        classifier_hint: ``{"din276": "330.10", "masterformat": "..."}``.
            BIM elements typically arrive pre-classified; PDF/photo
            usually don't.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    source: SourceType
    source_lang: str = Field(default="en", min_length=2, max_length=8)
    category: str = Field(default="", max_length=64)
    description: str = Field(default="", max_length=2000)
    properties: dict[str, Any] = Field(default_factory=dict)
    quantities: dict[str, float] = Field(default_factory=dict)
    unit_hint: str | None = Field(default=None, max_length=20)
    classifier_hint: dict[str, str] | None = None


class MatchCandidate(BaseModel):
    """One ranked CWICR position returned to the caller.

    The candidate exposes both the raw vector score and the post-boost
    final score. Field names match the eval-harness contract — every
    candidate dict the harness reads has at minimum ``code`` and
    ``unit_rate`` accessible.

    The ``boosts_applied`` dict is intentionally open-ended: each boost
    contributes one key (e.g. ``"classifier_match"``) so we can
    re-tune weights from production audit data without changing this
    schema.
    """

    model_config = ConfigDict(extra="ignore")

    code: str
    description: str = ""
    unit: str = ""
    unit_rate: float = 0.0
    currency: str = ""
    score: float = 0.0
    vector_score: float = 0.0
    boosts_applied: dict[str, float] = Field(default_factory=dict)
    confidence_band: ConfidenceBand = "low"
    reasoning: str | None = None
    # Pass-through fields that aren't load-bearing for ranking but useful
    # to the UI (so we don't have to JOIN against costs again).
    region_code: str = ""
    source: str = ""
    language: str = ""
    classification: dict[str, str] = Field(default_factory=dict)


def confidence_band_for(score: float) -> ConfidenceBand:
    """Map a final score onto the high/medium/low confidence band."""
    if score >= CONFIDENCE_HIGH_THRESHOLD:
        return "high"
    if score >= CONFIDENCE_MEDIUM_THRESHOLD:
        return "medium"
    return "low"


class MatchRequest(BaseModel):
    """Inbound match request."""

    model_config = ConfigDict(extra="ignore")

    envelope: ElementEnvelope
    project_id: UUID
    top_k: int = Field(default=10, ge=1, le=100)
    use_reranker: bool = False


MatchStatus = Literal[
    "ok",
    "no_catalog_selected",
    "catalog_not_vectorized",
    "no_catalogs_loaded",
]


class MatchResponse(BaseModel):
    """Outbound match response.

    ``auto_linked`` is set when (and only when) the project's settings
    have ``auto_link_enabled=True`` AND the highest candidate's score
    crossed the configured ``auto_link_threshold``. The matcher itself
    never writes the link into BOQ — that's a separate confirmed-action
    step (Phase 4).

    ``status`` is the structured signal the UI uses to render explicit
    empty states instead of letting the user wonder why ``candidates``
    is ``[]``:

    * ``ok``                     — search ran, candidates returned (may be 0).
    * ``no_catalog_selected``    — project hasn't picked a CWICR catalogue yet.
    * ``catalog_not_vectorized`` — picked catalogue has zero vectors indexed.
    * ``no_catalogs_loaded``     — no CWICR catalogue has been loaded at all.

    ``catalog_id`` and ``catalog_count`` mirror the picked catalogue so the
    UI can render the badge ("📚 RU_STPETERSBURG · 55,719 / 1,000 vectorised")
    without an extra round-trip.
    """

    model_config = ConfigDict(extra="ignore", arbitrary_types_allowed=True)

    request: MatchRequest
    candidates: list[MatchCandidate] = Field(default_factory=list)
    translation_used: TranslationResult | None = None
    auto_linked: MatchCandidate | None = None
    took_ms: int = 0
    cost_usd: float = 0.0
    status: MatchStatus = "ok"
    catalog_id: str | None = None
    catalog_count: int = 0
    catalog_vectorized_count: int = 0
