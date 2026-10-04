# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Takeoff Pydantic schemas (request/response)."""

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
    """Response after uploading a PDF document."""

    id: str
    filename: str
    pages: int
    size_bytes: int
    status: str
    content_type: str
    uploaded_at: datetime | None = Field(None, alias="created_at")
    # The owning project. The viewer scopes measurement loading to this when no
    # project is active in the app header; without it a server document opened
    # from /markups or the documents tab on a clean profile never fetches its
    # measurements. Nullable because legacy direct uploads may carry no project.
    project_id: UUID | None = None
    # Per-page text-layer audit (8.2.0). ``pages_without_text`` is how many
    # pages came back with no text layer (usually scanned drawings that need
    # OCR); ``pages_without_text_list`` is their 1-based page numbers. Both
    # default to 0 / [] so a document with a full text layer - and any caller
    # that ignores the fields - is unaffected.
    pages_without_text: int = 0
    pages_without_text_list: list[int] = Field(default_factory=list)
    # Document-level per-page scale calibration (issue #334). Mirrors the
    # frontend ``PageScales`` shape ({defaultScale, byPage}); ``None`` when the
    # document was never calibrated at the document level (the viewer then falls
    # back to the legacy per-measurement scale stamps).
    page_scales: dict[str, Any] | None = None

    model_config = {"from_attributes": True, "populate_by_name": True}


class DocumentPageScalesUpdate(BaseModel):
    """Persist the document-level per-page scale calibration (issue #334).

    Calibration used to live only in the browser (localStorage) plus a weak
    per-measurement echo, so a reload where a stale local default won - or a
    non-geometry edit that re-stamped the live view scale - silently dropped a
    real calibration. Storing it once at the document level makes it the
    authoritative, durable source across reloads and devices.

    The payload mirrors the frontend ``PageScales`` shape
    (``{defaultScale: {pixelsPerUnit, unitLabel}, byPage: {<page>: {...}}}``).
    It is the user's own calibration for their own document, so it is stored
    verbatim (like the ``analysis`` / ``metadata`` JSON columns) behind the
    same ownership gate, with only a size guard against an abusive payload.
    """

    page_scales: dict[str, Any] = Field(default_factory=dict)

    @field_validator("page_scales")
    @classmethod
    def _bounded(cls, v: dict[str, Any]) -> dict[str, Any]:
        by_page = v.get("byPage")
        if isinstance(by_page, dict) and len(by_page) > 5000:
            raise ValueError("too many per-page scales")
        return v


class ExtractedElement(BaseModel):
    """A single element extracted from AI analysis."""

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
    # Id of the ``proposed`` row this candidate was stored as, which is what
    # the review endpoint addresses. Optional so a caller that only wants a
    # geometry preview keeps parsing older payloads.
    measurement_id: str | None = None


class RecognizeResponse(BaseModel):
    """Result of offline vector recognition for one page.

    Candidates are persisted as ``proposed`` rows before this returns, so a
    review decision survives a reload and is visible to colleagues. They are
    proposals, never billed work.
    """

    candidates: list[RecognizeCandidate] = Field(default_factory=list)
    page: int
    source: str = "vector_recognize"
    notes: str | None = None


class SimilarSymbolHit(BaseModel):
    """One matched symbol from a seeded "count by example" search.

    Coordinates are in PDF points - the same space the canvas stores
    measurements in - so the frontend can place a marker directly.
    """

    x: float
    y: float
    bbox_x0: float
    bbox_y0: float
    bbox_x1: float
    bbox_y1: float
    confidence: float
    is_seed: bool = False


class SimilarSymbolsResponse(BaseModel):
    """Result of a seeded similar-symbol search.

    ``note`` is ``no_vector_layer`` (the page is a scan with no drawing
    layer), ``no_symbol_at_point`` (nothing small enough under the click) or
    ``None`` on success.

    A non-empty search is stored as one ``proposed`` count row carrying every
    hit, and ``measurement_id`` addresses it for review. It stays ``None``
    when nothing matched, since there is no proposal to review.
    """

    hits: list[SimilarSymbolHit] = Field(default_factory=list)
    seed_found: bool = False
    page: int
    note: str | None = None
    measurement_id: str | None = None


# ── Tier-1 scale detection from the PDF text layer ──────────────────────────
#
# The deterministic, AI-free counterpart to the vision plan-reader's scale
# proposal: read the explicit scale note the architect already typed in the
# title block ("SCALE 1:100", '1/4" = 1\'-0"') and offer it as a one-click
# calibration the user confirms. Nothing is persisted or auto-applied.


class ScaleDetectionCandidate(BaseModel):
    """One drawing-scale candidate read from the extracted text layer.

    ``ratio`` is the integer ``N`` of a ``1:N`` paper scale (one paper unit
    represents ``N`` real-world units), which the frontend turns into a
    pixels-per-metre calibration through its single-sourced ``presetScale``
    (``72 / (0.0254 * N)``). ``label`` is the display form ("1:100"); for an
    imperial equation the original notation is preserved in ``detail`` for the
    badge. ``confidence`` orders candidates so the UI offers the strongest one.
    """

    ratio: int = Field(..., ge=1, description="The N of a 1:N paper scale")
    label: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    page: int = Field(..., ge=1)
    evidence: str = Field("", description="The exact matched substring from the sheet")
    source: str = Field("ratio", description="ratio | imperial")
    detail: dict[str, Any] = Field(default_factory=dict)


class ScaleDetectionResponse(BaseModel):
    """Detected scale(s) for a document (nothing persisted or applied).

    ``best`` is the single strongest candidate (``None`` when the drawing
    carries no explicit scale note - an honest "nothing detected", not a
    fabricated guess); ``candidates`` is the full ranked list for an "other
    matches" affordance.
    """

    best: ScaleDetectionCandidate | None = None
    candidates: list[ScaleDetectionCandidate] = Field(default_factory=list)
    source: str = "text_layer"


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


# Where a measurement's scale ratio came from. The client is the only place
# that knows this for a hand-drawn measurement - it is the surface where the
# user calibrated, picked a preset, or drew on a page that already had a scale
# - so it is sent rather than guessed server-side. Server-generated proposals
# stamp their own source instead of trusting the request.
#
# A closed set rather than free text: this feeds a "recompute these rows"
# decision, and a field that can hold anything is a field nothing can filter on.
ScaleSource = Literal[
    # Read from the PDF's own text layer (``scale_detect.py``).
    "page_text",
    # Read by OCR from a scanned sheet that has no text layer.
    "recovered_text",
    # Read by a vision model off the rendered page. Kept apart from
    # ``page_text`` on purpose: the same "1:100" carries a different weight
    # depending on whether it was parsed from the text layer or inferred from
    # pixels, and collapsing the two would hide exactly the distinction this
    # column exists to record.
    "vision_read",
    # The user drew a known dimension and set the scale from it.
    "manual_calibration",
    # A standard ratio picked from the list (1:50, 1:100).
    "preset",
    # Taken from the page the measurement was drawn on.
    "inherited",
]


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
    # None = "no per-measurement colour override" (issue #378). Since #299 a
    # stored ``group_color`` means the user explicitly recoloured THIS
    # measurement; the client omits the field when they never did. Defaulting to
    # the blue hex here re-stamped that override onto every uncoloured row, so a
    # cache-less load painted blue instead of following the group colour. A
    # None default stores a genuine NULL for an uncoloured measurement (the
    # column is nullable), which the renderers read as "fall back to the group
    # colour". The blue hex constant now lives only where a colour is truly meant.
    group_color: str | None = Field(default=None, max_length=20)
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
    # Optional, and NULL is a real answer: an older client does not send it,
    # and recording "not stated" beats inventing a source that was never known.
    scale_source: ScaleSource | None = None
    linked_boq_position_id: str | None = None
    is_deduction: bool = Field(
        default=False,
        description=(
            "Mark this area measurement as an opening / void (door, window, "
            "cut-out). Its area is subtracted from the gross area of its group "
            "so a net area = gross - openings. Only meaningful for area "
            "measurements; ignored for other types."
        ),
    )
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
    # Recalibrating a measurement changes where its scale came from, so the
    # source travels with the ratio on update as well as on create.
    scale_source: ScaleSource | None = None
    linked_boq_position_id: str | None = None
    is_deduction: bool | None = None
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
    # None = no per-measurement colour override (issue #378); the client reads
    # it as "use the group colour". A row recoloured by the user carries its hex.
    group_color: str | None = None
    annotation: str | None = None
    points: list[dict[str, Any]] = Field(default_factory=list)
    measurement_value: float | None = None
    measurement_unit: str = "m"
    depth: float | None = None
    volume: float | None = None
    perimeter: float | None = None
    count_value: int | None = None
    scale_pixels_per_unit: float | None = None
    # NULL on every row created before the column existed, and on any row whose
    # client never stated a source. Surfaces show that as "Unknown".
    scale_source: str | None = None
    linked_boq_position_id: str | None = None
    is_deduction: bool = False
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
    """Full revision-compare payload for two takeoff documents.

    ``summary`` carries:

    * ``measurements`` - added / removed / modified / unchanged tally
    * ``net_cost_impact`` / ``cost_currency`` - signed money delta
    * ``from_measurement_count`` / ``to_measurement_count`` - rows actually
      compared on each side
    * ``from_measurement_total`` / ``to_measurement_total`` - rows each
      document really holds
    * ``truncated`` - True when a document exceeded the compare row ceiling,
      so the diff covers only part of the drawing set. Clients MUST surface
      this; a truncated compare read as a complete one lets a user conclude
      "nothing changed" from measurements that were never looked at.
    * ``truncation_limit`` - the ceiling that was hit, ``None`` otherwise
    * ``collapsed_duplicate_keys`` - measurements that shared a compare key
      and collapsed onto one diff row (by design, see
      ``_measurement_compare_key``), which is why the row tally can be
      smaller than the compared counts
    """

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


class CreateBoqPositionFromMeasurementRequest(BaseModel):
    """Create a new BOQ position from a measurement and link the two.

    The quantity is NOT taken from the client: the server computes the
    measurement's reported quantity (wall area, openings, slope, wastage,
    multiplier) itself, so the new position carries the same figure the
    takeoff ledger shows.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    boq_id: UUID = Field(..., description="Bill the new position goes into; must be in the measurement's project")
    parent_id: UUID | None = Field(default=None, description="Section to place the position in; None = top level")
    description: str | None = Field(
        default=None,
        max_length=5000,
        description="Position text; defaults to the measurement's annotation",
    )
    unit: str | None = Field(
        default=None,
        max_length=20,
        description=(
            "Unit to state the position in (e.g. ft2 for an imperial bill). The reported quantity is "
            "converted into it; None keeps the measurement's own unit."
        ),
    )
    cost_item_id: UUID | None = Field(default=None, description="Cost database item to price the position from")
    unit_rate: Decimal | None = Field(default=None, ge=0, description="Unit rate; None = 0 (to be priced)")


class CreateBoqPositionFromMeasurementResponse(BaseModel):
    """The created position and the measurement now linked to it."""

    position_id: str
    boq_id: str
    ordinal: str
    description: str
    unit: str
    quantity: float
    measurement: TakeoffMeasurementResponse


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


class MeasurementReviewRequest(BaseModel):
    """Accept or reject one proposal, optionally correcting its geometry.

    ``points`` rides along with an accept to mean "edit then accept": the
    server replaces the geometry and re-derives the value from it, so the
    correction cannot smuggle in a quantity the shape does not support.
    """

    action: Literal["accept", "reject"]
    points: list[dict] | None = Field(default=None, max_length=10000)
    note: str | None = Field(default=None, max_length=2000)


class ProposalQueueResponse(BaseModel):
    """The pending review queue for one document, with progress counts.

    The counts always cover the whole document even when ``proposals`` is
    scoped to one page, so the progress line does not change meaning when the
    reviewer filters.
    """

    proposals: list[TakeoffMeasurementResponse] = Field(default_factory=list)
    page: int | None = None
    proposed_count: int = 0
    confirmed_count: int = 0
    rejected_count: int = 0
    reviewed_count: int = 0
    total_count: int = 0


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
