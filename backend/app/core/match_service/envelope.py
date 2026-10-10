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

SourceType = Literal["bim", "pdf", "dwg", "photo", "text", "boq", "image"]
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

    v3 ProjectItem fields (added 2026-05-09 per MAPPING_PROCESS.md §3.2):
    upstream extractors that know the structured value should populate
    these fields directly. The query builder routes them to either
    Qdrant ``hard_filters`` or ``soft_boosts`` based on the
    "if classifier errs, would the right answer be discarded?" rule
    from §4.2.1 - BIM Pset values are hard, DWG / heuristic guesses
    are soft. Each is optional so existing callers don't break.

    Attributes (v3):
        ifc_class: Verbatim ``IfcWall`` / ``IfcSlab`` / ``IfcBeam`` from
            the BIM extractor. Hard filter when present - IFC class is
            authoritative for source-of-truth IFC files.
        ifc_predefined_type: ``"PARTITIONING"``, ``"FLOOR"``, etc.
            Hard filter when present.
        ost_category: Revit ``OST_Walls`` / ``OST_Floors`` from the
            Revit RVT export. Soft boost - Revit families occasionally
            mislabel category vs ifc_class.
        material_class: Normalised material bucket - ``"concrete"``,
            ``"steel"``, ``"wood"``, ``"ceramic"``. Soft boost.
        nominal_size_mm: Integer mm thickness / diameter / nominal size.
            Soft boost - sized rates within ±10% range still rank well.
        is_external: Pset ``IsExternal`` - hard filter when present
            (BIM Pset is trustworthy).
        is_loadbearing: Pset ``LoadBearing`` - hard filter when present.
        is_structural: ``StructuralUsage == "Bearing"`` from Revit -
            hard filter when present.
        construction_stage_hint: User-picked stage (``"02_Demolition"``
            … ``"13_Sitework"``). Hard filter when present - the user
            explicitly narrowed the search.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    source: SourceType
    # Empty string is a valid value: the upstream extractor didn't
    # detect a language tag. The translation cascade short-circuits on
    # empty source_lang and runs the search verbatim - preferable to
    # the historical ``"en"`` default, which forced an English-source
    # assumption on every untagged element.
    source_lang: str = Field(default="", max_length=8)
    category: str = Field(default="", max_length=64)
    description: str = Field(default="", max_length=2000)
    properties: dict[str, Any] = Field(default_factory=dict)
    quantities: dict[str, float] = Field(default_factory=dict)
    unit_hint: str | None = Field(default=None, max_length=20)
    classifier_hint: dict[str, str] | None = None

    # ── v3 ProjectItem-equivalent structured fields ──────────────────
    ifc_class: str | None = Field(default=None, max_length=64)
    ifc_predefined_type: str | None = Field(default=None, max_length=64)
    ost_category: str | None = Field(default=None, max_length=64)
    material_class: str | None = Field(default=None, max_length=32)
    nominal_size_mm: int | None = Field(default=None, ge=0, le=100_000)
    is_external: bool | None = None
    is_loadbearing: bool | None = None
    is_structural: bool | None = None
    construction_stage_hint: str | None = Field(default=None, max_length=32)

    # Verbatim CWICR rate_code carried over from the source - set when
    # the upstream extractor knows the exact match (e.g., a BoQ row with
    # a populated ``Code`` column, or a manual override). When present,
    # the ranker short-circuits the Qdrant fan-out and pulls the rate
    # directly from parquet (MAPPING_PROCESS.md §4.1.5). Falls through
    # to the normal vector path when the code isn't in the bound
    # catalogue (stale code, wrong catalogue, typo).
    exact_code: str | None = Field(default=None, max_length=128)

    # Project-context fields - populated by the caller (service.run_match)
    # so matchers can scope candidate search by the project's expected
    # currency / region without a per-group project lookup. Empty string
    # means "no preference" (matchers degrade to global search).
    #
    # The lexical matcher uses ``project_currency`` as a hard SQL filter:
    # for a USD project we don't want EUR candidates pretending to be
    # USD rates - return no candidates instead and let the UI render
    # "no rates loaded for USD" so the operator loads the right
    # catalogue. This is what makes /match-elements universal across
    # currency zones - it never lies about the rate's currency.
    project_currency: str = Field(default="", max_length=8)
    project_region: str = Field(default="", max_length=32)


class MatchCandidate(BaseModel):
    """One ranked CWICR position returned to the caller.

    The candidate exposes both the raw vector score and the post-boost
    final score. Field names match the eval-harness contract - every
    candidate dict the harness reads has at minimum ``code`` and
    ``unit_rate`` accessible.

    The ``boosts_applied`` dict is intentionally open-ended: each boost
    contributes one key (e.g. ``"classifier_match"``) so we can
    re-tune weights from production audit data without changing this
    schema.
    """

    model_config = ConfigDict(extra="ignore")

    # Database id of the underlying record (CostItem.id for CWICR hits,
    # CatalogResource.id for resource hits). The UI posts this back when
    # confirming so the BOQ Position links to the real row, not a code
    # string. Optional because some legacy candidates serialised before
    # this field landed don't carry an id.
    id: str | None = None
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


# Lower thresholds applied when the candidate is supported by hard
# filter matches or a high-quality classification signal - see v3-P9
# MAPPING_PROCESS.md §6.4. Three or more hard filters that survive into
# the SearchPlan (e.g., ifc_class + is_loadbearing + construction_stage)
# tighten the search so much that a moderate vector score still earns
# HIGH band; a single hard filter is not enough on its own.
_HARD_FILTER_HIGH_BONUS_FLOOR: float = 0.75
_HARD_FILTER_MEDIUM_BONUS_FLOOR: float = 0.60
_HARD_FILTER_BONUS_MIN_COUNT: int = 3
_HARD_FILTER_MEDIUM_MIN_COUNT: int = 1


def confidence_band_for(
    score: float,
    hard_filters_matched: int = 0,
    classification_confidence: str | None = None,
) -> ConfidenceBand:
    """Map a final score onto the high/medium/low confidence band.

    Backwards-compatible: ``confidence_band_for(score)`` keeps the v2
    semantics (pure threshold check). The two extra arguments power the
    v3 §6.4 derivation:

    * ``hard_filters_matched`` - count of *hard* SearchPlan predicates
      whose value is also present (and matches) on the candidate's
      Qdrant payload. Ignored when ``0``. ``≥3`` lets a vector score
      ≥0.75 promote to HIGH; ``≥1`` lets ≥0.60 promote to MEDIUM.
    * ``classification_confidence`` - value from the candidate's CWICR
      payload; ``"high"`` shifts the floors slightly downward,
      ``"low"`` shifts them upward. ``None`` is a no-op.

    The bonuses are additive, not multiplicative - they relax the
    *floor* required to clear a band, never above the original
    ``CONFIDENCE_HIGH_THRESHOLD`` (so a high score with no hard filter
    support still lands in HIGH).
    """

    cls = (classification_confidence or "").strip().lower()
    cls_offset = -0.02 if cls == "high" else 0.03 if cls == "low" else 0.0

    high_floor = CONFIDENCE_HIGH_THRESHOLD + cls_offset
    medium_floor = CONFIDENCE_MEDIUM_THRESHOLD + cls_offset

    if hard_filters_matched >= _HARD_FILTER_BONUS_MIN_COUNT:
        # 3+ hard filters: the search was narrow enough that 0.75 is
        # convincing - drop the HIGH floor for this candidate only.
        high_floor = min(high_floor, _HARD_FILTER_HIGH_BONUS_FLOOR + cls_offset)
    if hard_filters_matched >= _HARD_FILTER_MEDIUM_MIN_COUNT:
        medium_floor = min(medium_floor, _HARD_FILTER_MEDIUM_BONUS_FLOOR + cls_offset)

    if score >= high_floor:
        return "high"
    if score >= medium_floor:
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
    never writes the link into BOQ - that's a separate confirmed-action
    step (Phase 4).

    ``status`` is the structured signal the UI uses to render explicit
    empty states instead of letting the user wonder why ``candidates``
    is ``[]``:

    * ``ok``                     - search ran, candidates returned (may be 0).
    * ``no_catalog_selected``    - project hasn't picked a CWICR catalogue yet.
    * ``catalog_not_vectorized`` - picked catalogue has zero vectors indexed.
    * ``no_catalogs_loaded``     - no CWICR catalogue has been loaded at all.

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
    # Process ids of matching models switched off in the processes center
    # (``cwicr_ranker``, ``bge_reranker``). Non-empty means candidates came
    # from the reduced path, and the UI says so with a link to the center.
    models_disabled: list[str] = Field(default_factory=list)
