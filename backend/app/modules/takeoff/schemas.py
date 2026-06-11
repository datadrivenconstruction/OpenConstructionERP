"""‌⁠‍Takeoff Pydantic schemas (request/response)."""

import math
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator


# ── Money serialisation helper (mirrors ai_estimator / match_elements / boq) ──
# v3 §10: dollar amounts cross the wire as a Decimal-rendered string, never a
# binary float, so a "$0.0023" AI-cost estimate never drifts to "0.00229999".
# The DB columns stay numeric; only the JSON contract changes.
def _serialise_money(v: Decimal | None) -> str | None:
    if v is None:
        return None
    if not isinstance(v, Decimal):
        try:
            v = Decimal(str(v))
        except (InvalidOperation, ValueError):
            return "0"
    if not v.is_finite():
        return "0"
    return format(v, "f")


# Round-6 audit (2026-05-22) - hard bound on per-axis coordinates inside a
# polygon. PDF pages render in PostScript points (72 dpi); ISO A0 at 72 dpi
# is 3370 × 2384 px. The frontend zoom factor caps the visible canvas at
# ~50× before WebGL gives up, so a legitimate point will never exceed
# ~250 000 in either axis. We allow ±1 000 000 as a wide safety belt while
# still cutting off the absurd ``1e30`` payload that would otherwise let
# a malicious client compute polygon areas of 1e60 m² via the shoelace
# formula and inflate BOQ totals after link-to-boq.
_MAX_COORD_ABS = 1_000_000.0
# Polygons / polylines are bounded so a malicious client can't ship a
# 10-million-point payload that pegs the shoelace loop. 5000 is well
# above the densest real-world tracing (longest highway centerline in
# the seed data is ~1200 vertices).
_MAX_POINTS_PER_MEASUREMENT = 5000


class TakeoffDocumentResponse(BaseModel):
    """‌⁠‍Response after uploading a PDF document."""

    id: str
    filename: str
    pages: int
    size_bytes: int
    status: str
    content_type: str
    uploaded_at: datetime | None = Field(None, alias="created_at")

    model_config = {"from_attributes": True, "populate_by_name": True}


class ExtractedElement(BaseModel):
    """‌⁠‍A single element extracted from AI analysis."""

    id: str
    category: str
    description: str
    quantity: float
    unit: str
    # R7 deep-improve: confidence must be a probability in [0, 1]. Out-of-
    # range values from an AI model indicate a bug - fail loudly instead
    # of silently allowing 1.5 or -3 to propagate through the UI.
    confidence: float = Field(..., ge=0.0, le=1.0)


class AnalysisResultResponse(BaseModel):
    """AI analysis result for a document."""

    elements: list[ExtractedElement]
    summary: dict


class ExtractTablesResponse(BaseModel):
    """Table extraction result for a document."""

    elements: list[ExtractedElement]
    summary: dict


class RecognizeCandidate(BaseModel):
    """One detected, unconfirmed measurement proposed by vector recognition."""

    type: str  # "area" | "distance" | "count"
    points: list[dict] = Field(default_factory=list)
    value: float | None = None
    dimension: str = ""  # "area" | "length" | "count"
    count: int | None = None
    confidence: float = 0.0
    reason: str = ""


class RecognizeResponse(BaseModel):
    """Result of offline vector recognition for one page (nothing persisted)."""

    candidates: list[RecognizeCandidate] = Field(default_factory=list)
    page: int
    source: str = "vector_recognize"
    notes: str | None = None


# ── CAD quantity extraction schemas ──────────────────────────────────────


class CadQuantityItem(BaseModel):
    """Single type-level row in a quantity group."""

    type: str
    material: str = ""
    count: float = 0
    volume_m3: float = 0
    area_m2: float = 0
    length_m: float = 0


class QuantityTotals(BaseModel):
    """Summed quantities for a group or the whole file."""

    count: float = 0
    volume_m3: float = 0
    area_m2: float = 0
    length_m: float = 0


class CadQuantityGroup(BaseModel):
    """A category-level group of quantity items."""

    category: str
    items: list[CadQuantityItem]
    totals: QuantityTotals


class CadExtractResponse(BaseModel):
    """Response from the deterministic CAD quantity extraction endpoint."""

    filename: str
    format: str
    total_elements: int
    duration_ms: int
    groups: list[CadQuantityGroup]
    grand_totals: QuantityTotals


# ── Takeoff Measurement schemas ─────────────────────────────────────────


class PointSchema(BaseModel):
    """A single 2D point in page coordinates.

    Round-6 audit - both axes are clamped to ``±_MAX_COORD_ABS`` so a
    malicious payload (``x: 1e30``) cannot inflate polygon areas via
    the shoelace formula and contaminate BOQ totals. NaN and infinity
    are rejected outright (they would produce ``NaN`` areas that
    silently bypass the upper-bound check).
    """

    x: float = Field(..., ge=-_MAX_COORD_ABS, le=_MAX_COORD_ABS)
    y: float = Field(..., ge=-_MAX_COORD_ABS, le=_MAX_COORD_ABS)

    @field_validator("x", "y")
    @classmethod
    def _reject_nan_inf(cls, v: float) -> float:
        # Pydantic's ge/le accept NaN through silently on some versions -
        # belt-and-braces. Without this guard, a polygon with NaN points
        # produces NaN areas that the upstream Decimal cast turns into
        # ``Decimal('NaN')`` and the downstream rollup never errors.
        if math.isnan(v) or math.isinf(v):
            raise ValueError("coordinate must be a finite real number")
        return v


class TakeoffMeasurementCreate(BaseModel):
    """Create a new takeoff measurement."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    document_id: str | None = None
    page: int = Field(default=1, ge=1)
    type: str = Field(
        ...,
        min_length=1,
        max_length=50,
        pattern=r"^(distance|area|count|polyline|volume|cloud|arrow|text|rectangle|highlight)$",
        description=(
            "Measurement or annotation type. Measurement: distance, area, count, polyline, volume. "
            "Annotation: cloud, arrow, text, rectangle, highlight."
        ),
    )
    group_name: str = Field(default="General", max_length=100)
    group_color: str = Field(default="#3B82F6", max_length=20)
    annotation: str | None = Field(default=None, max_length=500)
    points: list[PointSchema] = Field(
        default_factory=list,
        max_length=_MAX_POINTS_PER_MEASUREMENT,
    )
    measurement_value: float | None = None
    measurement_unit: str = Field(default="m", max_length=20)
    depth: float | None = None
    volume: float | None = None
    perimeter: float | None = None
    count_value: int | None = Field(default=None, ge=0)
    scale_pixels_per_unit: float | None = Field(default=None, gt=0)
    linked_boq_position_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TakeoffMeasurementUpdate(BaseModel):
    """Partial update for a takeoff measurement."""

    model_config = ConfigDict(str_strip_whitespace=True)

    document_id: str | None = None
    page: int | None = Field(default=None, ge=1)
    type: str | None = Field(default=None, max_length=50)
    group_name: str | None = Field(default=None, max_length=100)
    group_color: str | None = Field(default=None, max_length=20)
    annotation: str | None = Field(default=None, max_length=500)
    points: list[PointSchema] | None = Field(
        default=None,
        max_length=_MAX_POINTS_PER_MEASUREMENT,
    )
    measurement_value: float | None = None
    measurement_unit: str | None = Field(default=None, max_length=20)
    depth: float | None = None
    volume: float | None = None
    perimeter: float | None = None
    count_value: int | None = Field(default=None, ge=0)
    scale_pixels_per_unit: float | None = Field(default=None, gt=0)
    linked_boq_position_id: str | None = None
    metadata: dict[str, Any] | None = None


class TakeoffMeasurementResponse(BaseModel):
    """Measurement returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    document_id: str | None = None
    page: int = 1
    type: str
    group_name: str = "General"
    group_color: str = "#3B82F6"
    annotation: str | None = None
    points: list[dict[str, Any]] = Field(default_factory=list)
    measurement_value: float | None = None
    measurement_unit: str = "m"
    depth: float | None = None
    volume: float | None = None
    perimeter: float | None = None
    count_value: int | None = None
    scale_pixels_per_unit: float | None = None
    linked_boq_position_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_by: str = ""
    created_at: datetime
    updated_at: datetime


class TakeoffMeasurementBulkCreate(BaseModel):
    """Bulk create measurements (e.g. importing from localStorage)."""

    measurements: list[TakeoffMeasurementCreate] = Field(..., min_length=1, max_length=2000)


class TakeoffMeasurementSummary(BaseModel):
    """Aggregated measurement stats for a project."""

    total_measurements: int = 0
    by_type: dict[str, int] = Field(default_factory=dict)
    by_group: dict[str, int] = Field(default_factory=dict)
    by_page: dict[int, int] = Field(default_factory=dict)


# ── Revision compare (Item 17) ─────────────────────────────────────────


class TakeoffMeasurementDiffRow(BaseModel):
    """One measurement-level change between two takeoff documents.

    Measurements are matched across the two documents by a stable key:
    ``metadata.compare_key`` when present, otherwise the natural tuple
    ``(page, type, group_name, annotation)``. A measurement present only
    in the new document is ``added``; only in the old one ``removed``; a
    measured-value change is ``modified``; identical value ``unchanged``.

    When the measurement is linked to a BOQ position and its value
    changed, ``cost_impact`` carries the signed money delta
    ``(new - old) * unit_rate`` in the project's base currency (Decimal
    string; never blended across currencies).
    """

    change_type: Literal["added", "removed", "modified", "unchanged"]
    measurement_id: str
    type: str
    group_name: str = "General"
    page: int = 1
    label: str | None = None
    old_value: float | None = None
    new_value: float | None = None
    measurement_unit: str | None = None
    linked_boq_position_id: str | None = None
    cost_impact: str | None = None  # signed Decimal string in base currency
    cost_currency: str | None = None


class TakeoffCompareResponse(BaseModel):
    """Full revision-compare payload for two takeoff documents."""

    project_id: UUID
    from_document_id: str
    to_document_id: str
    measurement_rows: list[TakeoffMeasurementDiffRow] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)


# ── Create-variation-from-delta handoff (Item 17) ───────────────────────


class CreateVariationFromCompareRequest(BaseModel):
    """Turn a PDF revision-compare delta into a draft variation request.

    The compare is recomputed server-side from the two document ids (the
    deterministic :meth:`compare_documents` is the single source of
    truth), so the client only carries the project + document pair and an
    optional title override. The created variation is always a *draft* -
    automation proposes, a human confirms and submits it.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    from_document_id: str = Field(..., min_length=1, max_length=255)
    to_document_id: str = Field(..., min_length=1, max_length=255)
    title: str | None = Field(default=None, max_length=500)


class CreateVariationFromCompareResponse(BaseModel):
    """The draft variation request minted from a PDF revision-compare delta."""

    variation_request_id: UUID
    code: str
    estimated_cost_impact: str = "0"  # signed Decimal string in base currency
    currency: str = ""


class LinkToBoqRequest(BaseModel):
    """Request to link a measurement to a BOQ position."""

    boq_position_id: str = Field(..., min_length=1, max_length=255)
    push_quantity: bool = Field(
        default=False,
        description=(
            "When true, copy the measurement's measured value into the "
            "target BOQ position's quantity and recompute the position "
            "total. A measurement with no usable value is a no-op (the "
            "existing quantity is left untouched). Default false keeps "
            "existing callers backward-compatible."
        ),
    )


# ── Vision-LLM plan reading (issue #194) ────────────────────────────────────
#
# The vision-LLM path is an ADDITIONAL, higher-quality suggestion source that
# sits alongside the offline OpenCV "Recognize" tool, never replacing it. Every
# model output is a SUGGESTION carrying a real confidence; nothing is applied to
# the takeoff or the BOQ without an explicit human accept (CLAUDE.md rule 7).
#
# Takeoff-local confidence band thresholds, mirroring the canonical values in
# ``ai_estimator/service.py`` (0.78 / 0.62). Exposed through ``/plan-read/meta``
# so the UI never hardcodes them.
TAKEOFF_CONFIDENCE_HIGH_THRESHOLD = 0.78
TAKEOFF_CONFIDENCE_MEDIUM_THRESHOLD = 0.62
# The largest polygon the model may return for a single room. Bounds the
# shoelace loop and the JSON payload. Aligned with the prompt's "4 to 60".
MAX_PLAN_POLYGON_VERTICES = 60
# The largest count cluster the model may return for a single symbol class.
MAX_PLAN_SYMBOL_CENTERS = 400


class NormPoint(BaseModel):
    """A single normalized [0, 1] image/page coordinate (top-left origin).

    Reuses the :class:`PointSchema` NaN/Inf guard but bounds both axes to
    ``[0, 1]`` because the vision model is told to emit normalized coordinates.
    An out-of-range or non-finite value is rejected so a malformed model output
    can never map to an off-page PDF point or a NaN area.
    """

    x: float = Field(..., ge=0.0, le=1.0)
    y: float = Field(..., ge=0.0, le=1.0)

    @field_validator("x", "y")
    @classmethod
    def _reject_nan_inf(cls, v: float) -> float:
        if math.isnan(v) or math.isinf(v):
            raise ValueError("coordinate must be a finite real number")
        return v


class PlanScale(BaseModel):
    """A scale candidate read from the drawing by the vision model.

    The model returns two normalized endpoints it claims span a known real
    distance, the real value, the unit, and which evidence it used. The server
    derives ``ratio_px_per_unit`` from the endpoints and validates it against
    the plausibility belt before this is ever offered to the user; the model's
    own ratio is never trusted.
    """

    value: float | None = Field(default=None, gt=0)
    unit: Literal["m", "mm", "ft", "in"] | None = None
    source: Literal["dimension_string", "scale_bar", "inferred"] | None = None
    confidence: float = Field(..., ge=0.0, le=1.0)
    ref_pixels: tuple[NormPoint, NormPoint] | None = None
    ref_real_value: float | None = Field(default=None, gt=0)
    ref_unit: Literal["m", "mm", "ft", "in"] | None = None


class PlanRoom(BaseModel):
    """One enclosed room traced by the vision model as a normalized polygon."""

    name: str = Field(default="", max_length=200)
    polygon: list[NormPoint] = Field(..., min_length=3, max_length=MAX_PLAN_POLYGON_VERTICES)
    confidence: float = Field(..., ge=0.0, le=1.0)


class PlanSymbol(BaseModel):
    """A class of repeated symbols clustered into one count proposal."""

    element_class: str = Field(default="", max_length=80)
    centers: list[NormPoint] = Field(..., min_length=1, max_length=MAX_PLAN_SYMBOL_CENTERS)
    confidence: float = Field(..., ge=0.0, le=1.0)


class PlanReadResult(BaseModel):
    """The validated structured output of one vision plan-read call."""

    page: int = Field(..., ge=1)
    scale: PlanScale | None = None
    rooms: list[PlanRoom] = Field(default_factory=list)
    symbols: list[PlanSymbol] = Field(default_factory=list)
    image_dpi: int = 0
    page_width_pt: float = 0.0
    page_height_pt: float = 0.0
    model_used: str = ""
    provider: str = ""
    tokens_used: int = 0
    cost_usd_estimate: Decimal = Decimal("0")
    notes: str | None = None

    @field_serializer("cost_usd_estimate", when_used="json")
    def _ser_cost(self, v: Decimal | None) -> str | None:
        return _serialise_money(v)


class PlanReadRequest(BaseModel):
    """Request to start a vision-LLM plan-read run for one page."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    document_id: str = Field(..., min_length=1, max_length=255)
    page: int = Field(default=1, ge=1)
    scale_pixels_per_unit: float | None = Field(default=None, gt=0)
    mode: Literal["scale", "rooms", "symbols", "full"] = "rooms"
    do_cost_match: bool = False


class AiTakeoffRunResponse(BaseModel):
    """Pollable state of one vision plan-read run."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    status: str
    project_id: UUID
    document_id: str | None = None
    page: int = 1
    mode: str = "rooms"
    provider: str | None = None
    model_used: str | None = None
    total_tokens: int = 0
    cost_usd_estimate: Decimal = Decimal("0")
    duration_ms: int = 0
    proposal_count: int = 0
    accepted_count: int = 0
    validation_report: dict[str, Any] | None = None
    failure_reason: str | None = None
    created_at: datetime | None = None

    @field_serializer("cost_usd_estimate", when_used="json")
    def _ser_cost(self, v: Decimal | None) -> str | None:
        return _serialise_money(v)


class PlanReadAcceptRequest(BaseModel):
    """Confirm a subset of a run's proposals into billed measurements.

    Either an explicit ``measurement_ids`` selection or a ``min_confidence``
    threshold (bulk-confirm-by-threshold) selects what to accept. A proposal
    carrying a self-intersection ERROR verdict is always blocked (redraw first);
    low confidence is a warning, not a block.
    """

    measurement_ids: list[str] | None = Field(default=None, max_length=2000)
    min_confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class PlanReadAcceptResponse(BaseModel):
    """Outcome of a plan-read accept call."""

    confirmed: int = 0
    skipped: int = 0
    blocked: int = 0
    measurement_ids: list[str] = Field(default_factory=list)


class PlanReadMetaResponse(BaseModel):
    """Thresholds, capabilities, and caps for the plan-read UI.

    The UI never hardcodes thresholds or limits; it reads them here (same
    pattern as ``/ai-estimator/meta``). ``vision_available`` lets the takeoff
    viewer hide / disable the "Read plan with AI" action when no vision-capable
    key is configured, so the feature degrades gracefully.
    """

    confidence_high_threshold: float = TAKEOFF_CONFIDENCE_HIGH_THRESHOLD
    confidence_medium_threshold: float = TAKEOFF_CONFIDENCE_MEDIUM_THRESHOLD
    vision_providers: list[str] = Field(default_factory=list)
    max_polygon_vertices: int = MAX_PLAN_POLYGON_VERTICES
    max_cost_usd: Decimal = Decimal("0")
    rolling_spend_usd: Decimal = Decimal("0")
    modes: list[str] = Field(default_factory=lambda: ["scale", "rooms", "symbols", "full"])
    vision_available: bool = False
    provider: str | None = None
    model_used: str | None = None
    reason: str | None = None

    @field_serializer("max_cost_usd", "rolling_spend_usd", when_used="json")
    def _ser_usd(self, v: Decimal | None) -> str | None:
        return _serialise_money(v)
