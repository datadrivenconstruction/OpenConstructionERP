"""‌⁠‍BIM Hub Pydantic schemas — request/response models.

Defines create, update, and response schemas for BIM models, elements,
BOQ links, quantity maps, element groups, and model diffs.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator


# ── v3 §10 money serialisation helper ─────────────────────────────────────
# Money fields are stored / accepted as ``Decimal`` but emitted as plain
# decimal *strings* in JSON. Float forces every consumer to parse a
# locale-coloured number and silently drops precision past ~15 sig figs.
# Mirrors ``backend/app/modules/boq/schemas.py::PositionResponse``.
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


def _validate_multiplier(raw: str | None) -> str | None:
    """QR-001 — reject a structurally invalid quantity-map multiplier.

    The multiplier feeds ``qty * multiplier * (1 + waste/100)`` at
    apply-time. A free string previously let ``"1e500"`` (overflows to
    ``inf`` after ``float()`` and serialises to JSON ``null``),
    ``"-2"`` (silently flips sign of every matched quantity), or
    ``"__import__('os')"`` (a rule that always hard-fails at apply
    time, silently dropping every matched element) be persisted as a
    "valid" rule.

    A valid multiplier is a *finite, strictly-positive* decimal. We
    parse with :class:`~decimal.Decimal` (locale-independent, no
    binary float rounding) and bound the magnitude so the downstream
    ``float()`` cannot reach non-finite territory. ``None`` / unset is
    left untouched (the create-schema default ``"1"`` applies).
    """
    if raw is None:
        return raw
    text = raw.strip()
    if not text:
        # Empty string is meaningless for a multiplier — treat as the
        # neutral element rather than rejecting (back-compat with rows
        # that stored "").
        return "1"
    try:
        value = Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"multiplier must be a finite positive number, got {raw!r}") from exc
    if not value.is_finite():
        raise ValueError(f"multiplier must be finite, got {raw!r}")
    if value <= 0:
        raise ValueError(
            f"multiplier must be strictly positive, got {raw!r} "
            f"(a non-positive multiplier would zero-out or sign-flip "
            f"every matched quantity)"
        )
    # 1e15 is already absurd for any real construction quantity factor;
    # keeping well under float-overflow territory means the apply-time
    # float() can never yield inf even after the waste multiplier.
    if value > Decimal("1e15"):
        raise ValueError(f"multiplier {raw!r} is implausibly large (max 1e15)")
    return text


def _validate_waste_pct(raw: str | None) -> str | None:
    """QR-001 — bound the quantity-map waste factor to a sane percentage.

    ``waste_factor_pct`` enters the apply-time math as
    ``(1 + waste/100)``. A negative value (e.g. ``"-50"``) silently
    *halves* every matched quantity instead of adding waste — the
    opposite of the field's intent and impossible to spot in the
    dry-run preview. We require ``0 <= waste <= 100`` (a >100 % waste
    factor on a takeoff quantity is never legitimate). ``None`` / unset
    is left untouched.
    """
    if raw is None:
        return raw
    text = raw.strip()
    if not text:
        return "0"
    try:
        value = Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"waste_factor_pct must be a number 0-100, got {raw!r}") from exc
    if not value.is_finite():
        raise ValueError(f"waste_factor_pct must be finite, got {raw!r}")
    if value < 0 or value > 100:
        raise ValueError(f"waste_factor_pct must be between 0 and 100, got {raw!r}")
    return text


# ── BIMModel schemas ─────────────────────────────────────────────────────────


class BIMUnitsMetadata(BaseModel):
    """Resolved IFCUNITASSIGNMENT for a converted BIM model.

    Populated by the IFC text-fallback parser
    (``bim_hub/ifc_processor.py::_parse_unit_assignment``) per ISO
    16739-1:2024 §5.4.3 and copied into ``BIMModel.metadata_['units']``
    by the bim_hub router.  Surfaces the unit system the IFC was
    authored in PLUS the scale table that was applied to convert
    extracted quantities into canonical SI (metres, m², m³, kg, s).

    Quantities stored on ``BIMElement.quantities`` are always already
    in canonical SI — this block exists so the frontend viewer can
    display the SOURCE unit label ("12.5 mm originally → 0.0125 m"),
    validation rules can branch on imperial vs metric authoring, and
    the BOQ aggregator can detect mixed-system projects.
    """

    model_config = ConfigDict(extra="allow")

    # ``metric`` | ``imperial`` | ``mixed`` | ``unknown``
    unit_system: str = "metric"
    # True iff the IFC declared an IFCUNITASSIGNMENT block.  False
    # means the parser fell back to ISO 16739 metric defaults.
    had_assignment: bool = False
    # True iff every declared unit has scale 1.0 (canonical SI).
    is_canonical: bool = True
    # ISO 4217 currency code resolved from IfcMonetaryUnit, if any.
    currency_code: str | None = None
    # {IfcUnitEnum → scale multiplier applied to source values}
    scale_table: dict[str, float] = Field(default_factory=dict)
    # {IfcUnitEnum → human-readable unit name as resolved}
    label_table: dict[str, str] = Field(default_factory=dict)
    # {IfcUnitEnum → canonical SI base symbol (e.g. "m", "m^2")}
    canonical_base: dict[str, str] = Field(default_factory=dict)


class BIMModelCreate(BaseModel):
    """‌⁠‍Create a new BIM model record."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    name: str = Field(..., min_length=1, max_length=255)
    discipline: str | None = Field(default=None, max_length=50)
    model_format: str | None = Field(default=None, max_length=20)
    version: str = Field(default="1", max_length=20)
    import_date: str | None = Field(default=None, max_length=20)
    status: str = Field(default="processing", max_length=50)
    bounding_box: dict[str, Any] | None = None
    original_file_id: str | None = Field(default=None, max_length=36)
    canonical_file_path: str | None = Field(default=None, max_length=500)
    parent_model_id: UUID | None = None
    # The ``metadata`` blob accepts an optional ``units`` sub-key
    # following the ``BIMUnitsMetadata`` schema above — see audit C2.
    metadata: dict[str, Any] = Field(default_factory=dict)


class BIMModelUpdate(BaseModel):
    """‌⁠‍Partial update for a BIM model."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    discipline: str | None = Field(default=None, max_length=50)
    model_format: str | None = Field(default=None, max_length=20)
    version: str | None = Field(default=None, max_length=20)
    import_date: str | None = Field(default=None, max_length=20)
    status: str | None = Field(default=None, max_length=50)
    element_count: int | None = None
    storey_count: int | None = None
    bounding_box: dict[str, Any] | None = None
    original_file_id: str | None = Field(default=None, max_length=36)
    canonical_file_path: str | None = Field(default=None, max_length=500)
    parent_model_id: UUID | None = None
    error_message: str | None = None
    metadata: dict[str, Any] | None = None


class BIMModelResponse(BaseModel):
    """BIM model returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    name: str
    discipline: str | None = None
    model_format: str | None = None
    version: str
    import_date: str | None = None
    status: str
    element_count: int
    storey_count: int
    bounding_box: dict[str, Any] | None = None
    original_file_id: str | None = None
    canonical_file_path: str | None = None
    parent_model_id: UUID | None = None
    error_message: str | None = None
    # ``error_code`` is a stable machine-readable identifier copied out of
    # ``metadata`` so the frontend can branch on it without parsing the
    # blob.  Common values: ``ddc_not_found``, ``ddc_failed``,
    # ``zero_elements``, ``unexpected``.
    error_code: str | None = None
    # Total disk usage of the conversion artifacts (GLB, DAE, parquet,
    # thumbnails) for this model, in megabytes.  ``None`` when the backend
    # could not be probed (set on every successful list response).
    conversion_artifact_size_mb: float | None = None
    # ``True`` iff the raw uploaded ``original.{ext}`` blob is still on
    # storage.  Drives the "Reconvert from original" affordance and the
    # disk-usage tooltip.  Pre-v2.6.29 rows in the DB still report this
    # field; the value just reflects the present state of the storage.
    has_original: bool | None = None
    # ``True`` iff geometry (GLB or DAE) is available for this model.
    # Derived at response time from ``canonical_file_path`` (set by the
    # background converter when DDC produced a usable mesh) — the
    # frontend BIM viewer uses this to decide whether to mount the 3D
    # canvas vs. show the "data only" element list. Defaults to False
    # so the field is always present in the JSON response (frontend
    # treats undefined as false, which is correct but noisy).
    has_geometry: bool = False
    created_by: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class BIMModelListResponse(BaseModel):
    """Paginated list of BIM models."""

    items: list[BIMModelResponse] = Field(default_factory=list)
    total: int = 0
    offset: int = 0
    limit: int = 50
    # Aggregate disk usage across all models in the list response.
    # Surfaced in the BIM page header chip.
    total_artifact_size_mb: float = 0.0
    total_original_size_mb: float = 0.0
    storage_root_label: str | None = None


# ── BIMElement schemas ───────────────────────────────────────────────────────


class BIMElementCreate(BaseModel):
    """Create a single BIM element."""

    model_config = ConfigDict(str_strip_whitespace=True)

    stable_id: str = Field(..., min_length=1, max_length=255)
    element_type: str | None = Field(default=None, max_length=100)
    name: str | None = Field(default=None, max_length=500)
    storey: str | None = Field(default=None, max_length=255)
    discipline: str | None = Field(default=None, max_length=50)
    properties: dict[str, Any] = Field(default_factory=dict)
    quantities: dict[str, Any] = Field(default_factory=dict)
    geometry_hash: str | None = Field(default=None, max_length=64)
    bounding_box: dict[str, Any] | None = None
    mesh_ref: str | None = Field(default=None, max_length=500)
    lod_variants: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class BIMElementBulkImport(BaseModel):
    """Bulk import of elements for a model."""

    model_config = ConfigDict(str_strip_whitespace=True)

    elements: list[BIMElementCreate] = Field(..., min_length=1, max_length=50000)


class BOQElementLinkBrief(BaseModel):
    """Lightweight BOQ link summary embedded in a BIM element response.

    Contains just enough data for the viewer to render a link badge and
    navigate to the linked BOQ position without a second round trip.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    boq_position_id: UUID
    boq_position_ordinal: str | None = None
    boq_position_description: str | None = None
    boq_position_quantity: float | None = None  # measurement, not money
    boq_position_unit: str | None = None
    # v3 §10 — money as Decimal, serialised to JSON as a plain string.
    boq_position_unit_rate: Decimal | None = None
    boq_position_total: Decimal | None = None
    link_type: str
    confidence: str | None = None

    @field_serializer("boq_position_unit_rate", "boq_position_total", when_used="json")
    def _ser_money(self, v: Decimal | None) -> str | None:
        return _serialise_money(v)


class DocumentLinkBrief(BaseModel):
    """Lightweight Document link summary embedded in a BIM element response.

    Mirrors ``BOQElementLinkBrief`` but lives in ``bim_hub.schemas`` to avoid
    a circular import with ``documents.schemas.DocumentBIMLinkBrief``. The
    two shapes must stay in sync — add fields in both files.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    document_id: UUID
    document_name: str | None = None
    document_category: str | None = None
    link_type: str
    confidence: str | None = None


class TaskBrief(BaseModel):
    """Lightweight Task summary embedded in a BIM element response.

    Mirrors ``app.modules.tasks.schemas.TaskBrief`` but is defined locally
    here to avoid a circular import between ``bim_hub.schemas`` and
    ``tasks.schemas``. The two shapes MUST stay in sync — add fields in
    both files.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    title: str
    status: str
    task_type: str
    due_date: str | None = None


class ActivityBrief(BaseModel):
    """Lightweight schedule activity summary embedded in a BIM element response.

    Mirrors ``app.modules.schedule.schemas.ActivityBrief`` but is defined
    locally here to avoid a circular import between ``bim_hub.schemas`` and
    ``schedule.schemas``. The two shapes MUST stay in sync — add fields in
    both files.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    name: str
    start_date: str | None = None
    end_date: str | None = None
    status: str
    percent_complete: float = 0.0


class ElementValidationSummary(BaseModel):
    """Lightweight per-element validation finding.

    Mirrors the shape stored inside ``ValidationReport.results`` when the
    report's ``target_type`` is ``'bim_model'``. Only failing checks
    produce these entries — a fully-passing element receives an empty
    ``validation_results`` list and ``validation_status='pass'``.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    rule_id: str
    severity: Literal["error", "warning", "info"]
    message: str


class RequirementBrief(BaseModel):
    """Lightweight requirement summary embedded in a BIM element response.

    Mirrors the relevant subset of
    ``app.modules.requirements.schemas.RequirementResponse`` but is
    defined locally to avoid a circular import between ``bim_hub`` and
    ``requirements``.  The two shapes MUST stay in sync — add fields in
    both files together.

    Surfaces the EAC triplet (entity / attribute / constraint) so the
    BIM viewer's "Linked requirements" section can render a meaningful
    one-line summary without an extra Postgres roundtrip.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    requirement_set_id: UUID
    entity: str
    attribute: str
    constraint_type: str = "equals"
    constraint_value: str
    unit: str = ""
    category: str = "general"
    priority: str = "must"
    status: str = "open"


class BIMElementResponse(BaseModel):
    """BIM element returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    model_id: UUID
    stable_id: str
    element_type: str | None = None
    name: str | None = None
    storey: str | None = None
    discipline: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)
    quantities: dict[str, Any] = Field(default_factory=dict)
    geometry_hash: str | None = None
    bounding_box: dict[str, Any] | None = None
    mesh_ref: str | None = None
    lod_variants: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    asset_info: dict[str, Any] = Field(default_factory=dict)
    is_tracked_asset: bool = False
    boq_links: list[BOQElementLinkBrief] = Field(default_factory=list)
    linked_documents: list[DocumentLinkBrief] = Field(default_factory=list)
    linked_tasks: list[TaskBrief] = Field(default_factory=list)
    linked_activities: list[ActivityBrief] = Field(default_factory=list)
    linked_requirements: list[RequirementBrief] = Field(default_factory=list)
    validation_results: list[ElementValidationSummary] = Field(default_factory=list)
    validation_status: Literal["pass", "warning", "error", "unchecked"] = "unchecked"
    created_at: datetime
    updated_at: datetime


class BIMElementListResponse(BaseModel):
    """Paginated list of BIM elements."""

    items: list[BIMElementResponse] = Field(default_factory=list)
    total: int = 0
    offset: int = 0
    limit: int = 200


# ── Asset Register schemas (v2.3.0) ──────────────────────────────────────────


class AssetInfoPayload(BaseModel):
    """Operational-phase metadata written into ``BIMElement.asset_info``.

    All fields optional — the asset workflow is incremental (user fills
    in what they know, updates later). Extra keys outside this schema
    are preserved on write so tenants can extend the bag.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="allow")

    manufacturer: str | None = Field(default=None, max_length=255)
    model: str | None = Field(default=None, max_length=255)
    serial_number: str | None = Field(default=None, max_length=255)
    # ISO-8601 date — stored as string for cross-DB portability.
    warranty_until: str | None = Field(default=None, max_length=20)
    commissioned_at: str | None = Field(default=None, max_length=20)
    # operational | decommissioned | under_maintenance | retired | unknown
    operational_status: str | None = Field(default=None, max_length=50)
    # Parent system grouping for COBie System-sheet and hierarchy views.
    # Free-form string (e.g. "HVAC-01", "Electrical Main Board").
    parent_system: str | None = Field(default=None, max_length=255)
    # Stable asset tag used on physical labels / QR stickers.
    asset_tag: str | None = Field(default=None, max_length=100)
    # Notes field — whatever the facility manager wants to remember.
    notes: str | None = Field(default=None, max_length=2000)


class AssetInfoUpdateRequest(BaseModel):
    """Request body for PATCH /assets/{element_id}/asset-info.

    Merges into the existing ``asset_info`` JSON. Pass ``is_tracked_asset``
    explicitly to override the auto-derived flag (auto: ``True`` when any
    asset_info field is set for the first time).
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    asset_info: AssetInfoPayload
    is_tracked_asset: bool | None = None


class AssetSummary(BaseModel):
    """Thin row for the Assets list view — does NOT hydrate relationships.

    Joins BIMElement + BIMModel so the list shows project/model context
    without a second round-trip.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    model_id: UUID
    project_id: UUID
    model_name: str
    stable_id: str
    element_type: str | None = None
    name: str | None = None
    storey: str | None = None
    discipline: str | None = None
    asset_info: dict[str, Any] = Field(default_factory=dict)
    # Convenience copies lifted out of asset_info so the frontend can
    # render sortable columns without peeking into the JSON blob.
    manufacturer: str | None = None
    model: str | None = None
    serial_number: str | None = None
    warranty_until: str | None = None
    operational_status: str | None = None
    asset_tag: str | None = None


class AssetListResponse(BaseModel):
    """Paginated Assets list response."""

    items: list[AssetSummary] = Field(default_factory=list)
    total: int = 0
    offset: int = 0
    limit: int = 100


# ── BOQElementLink schemas ───────────────────────────────────────────────────


class BOQElementLinkCreate(BaseModel):
    """Create a link between a BOQ position and a BIM element."""

    model_config = ConfigDict(str_strip_whitespace=True)

    boq_position_id: UUID
    bim_element_id: UUID
    link_type: str = Field(default="manual", max_length=50)
    confidence: str | None = Field(default=None, max_length=10)
    rule_id: str | None = Field(default=None, max_length=100)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BOQElementLinkResponse(BaseModel):
    """BOQ-BIM link returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    boq_position_id: UUID
    bim_element_id: UUID
    link_type: str
    confidence: str | None = None
    rule_id: str | None = None
    created_by: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class BOQElementLinkListResponse(BaseModel):
    """List of BOQ-BIM links."""

    items: list[BOQElementLinkResponse] = Field(default_factory=list)
    total: int = 0


class BIMModelBOQLinkAggregate(BaseModel):
    """Aggregated BOQ position + linked BIM element IDs for one model.

    Returned by ``GET /models/{model_id}/boq-links/``. Each entry is a BOQ
    position linked to at least one element in the model, with the full
    list of element UUIDs so the viewer can highlight the selection.
    Cheaper than fetching enriched elements and aggregating client-side
    when the model has thousands of elements.
    """

    model_config = ConfigDict(from_attributes=True)

    boq_position_id: UUID
    boq_id: UUID
    boq_position_ordinal: str | None = None
    boq_position_description: str | None = None
    boq_position_quantity: float | None = None  # measurement, not money
    boq_position_unit: str | None = None
    # v3 §10 — money as Decimal, serialised to JSON as a plain string.
    boq_position_unit_rate: Decimal | None = None
    boq_position_total: Decimal | None = None
    link_type: str
    confidence: str | None = None
    element_ids: list[UUID] = Field(default_factory=list)

    @field_serializer("boq_position_unit_rate", "boq_position_total", when_used="json")
    def _ser_money(self, v: Decimal | None) -> str | None:
        return _serialise_money(v)


class BIMModelBOQLinksResponse(BaseModel):
    """Aggregated BOQ links for a whole BIM model."""

    items: list[BIMModelBOQLinkAggregate] = Field(default_factory=list)
    total: int = 0


# ── BIMQuantityMap schemas ───────────────────────────────────────────────────


class BIMQuantityMapCreate(BaseModel):
    """Create a quantity mapping rule."""

    model_config = ConfigDict(str_strip_whitespace=True)

    org_id: UUID | None = None
    project_id: UUID | None = None
    name: str = Field(..., min_length=1, max_length=255)
    name_translations: dict[str, str] | None = None
    element_type_filter: str | None = Field(default=None, max_length=100)
    property_filter: dict[str, Any] | None = None
    quantity_source: str = Field(..., min_length=1, max_length=100)
    multiplier: str = Field(default="1", max_length=20)
    unit: str | None = Field(default=None, max_length=20)
    waste_factor_pct: str = Field(default="0", max_length=10)
    boq_target: dict[str, Any] | None = None
    is_active: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)

    _check_multiplier = field_validator("multiplier")(_validate_multiplier)
    _check_waste = field_validator("waste_factor_pct")(_validate_waste_pct)


class BIMQuantityMapUpdate(BaseModel):
    """Partial update for a quantity mapping rule."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    name_translations: dict[str, str] | None = None
    element_type_filter: str | None = Field(default=None, max_length=100)
    property_filter: dict[str, Any] | None = None
    quantity_source: str | None = Field(default=None, min_length=1, max_length=100)
    multiplier: str | None = Field(default=None, max_length=20)
    unit: str | None = Field(default=None, max_length=20)
    waste_factor_pct: str | None = Field(default=None, max_length=10)
    boq_target: dict[str, Any] | None = None
    is_active: bool | None = None
    metadata: dict[str, Any] | None = None

    _check_multiplier = field_validator("multiplier")(_validate_multiplier)
    _check_waste = field_validator("waste_factor_pct")(_validate_waste_pct)


class BIMQuantityMapResponse(BaseModel):
    """Quantity mapping rule returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    org_id: UUID | None = None
    project_id: UUID | None = None
    name: str
    name_translations: dict[str, str] | None = None
    element_type_filter: str | None = None
    property_filter: dict[str, Any] | None = None
    quantity_source: str
    multiplier: str
    unit: str | None = None
    waste_factor_pct: str
    boq_target: dict[str, Any] | None = None
    is_active: bool
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class BIMQuantityMapListResponse(BaseModel):
    """List of quantity mapping rules."""

    items: list[BIMQuantityMapResponse] = Field(default_factory=list)
    total: int = 0


class QuantityMapApplyRequest(BaseModel):
    """Request to apply quantity mapping rules to a model's elements."""

    model_config = ConfigDict(str_strip_whitespace=True)

    model_id: UUID
    dry_run: bool = Field(
        default=True,
        description=(
            "If True (default), return the preview without creating any "
            "BOQElementLink or BOQPosition rows. Set to False to actually "
            "persist links and auto-created positions."
        ),
    )


class QuantityMapApplyResult(BaseModel):
    """Result of applying quantity mapping rules.

    ``links_created`` and ``positions_created`` are always reported — they
    stay at 0 on a ``dry_run`` so the caller can safely display them as
    "would-be" counters without extra branching.

    ``skipped_count`` / ``skipped`` surface every (element, rule) pair
    that the engine considered but could not extract a quantity from.
    Each skip carries a ``reason`` so estimators can see at a glance
    *why* their expected elements were excluded — the previous version
    silently dropped these and made under-population invisible.
    """

    matched_elements: int = 0
    rules_applied: int = 0
    links_created: int = 0
    positions_created: int = 0
    skipped_count: int = 0
    results: list[dict[str, Any]] = Field(default_factory=list)
    skipped: list[dict[str, Any]] = Field(default_factory=list)


# ── BIMModelDiff schemas ─────────────────────────────────────────────────────


class BIMModelDiffResponse(BaseModel):
    """Model diff returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    old_model_id: UUID
    new_model_id: UUID
    diff_summary: dict[str, Any]
    diff_details: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── BIMElementGroup schemas ──────────────────────────────────────────────────


class BIMElementGroupCreate(BaseModel):
    """Create a new BIM element group (saved selection).

    When ``is_dynamic`` is True (default), ``filter_criteria`` is evaluated
    against ``oe_bim_element`` at create time and the resolved ids are cached
    in ``element_ids`` automatically; callers do not need to send
    ``element_ids``.

    When ``is_dynamic`` is False, the caller is expected to send an explicit
    ``element_ids`` list.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    model_id: UUID | None = None
    is_dynamic: bool = True
    filter_criteria: dict[str, Any] = Field(default_factory=dict)
    element_ids: list[UUID] = Field(default_factory=list)
    color: str | None = Field(default=None, max_length=20)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BIMElementGroupUpdate(BaseModel):
    """Partial update for a BIM element group.

    Any field can be omitted. If ``filter_criteria`` or ``is_dynamic`` is
    supplied, the service re-resolves the member list and re-caches
    ``element_ids`` + ``element_count``.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    model_id: UUID | None = None
    is_dynamic: bool | None = None
    filter_criteria: dict[str, Any] | None = None
    element_ids: list[UUID] | None = None
    color: str | None = Field(default=None, max_length=20)
    metadata: dict[str, Any] | None = None


class BIMElementGroupResponse(BaseModel):
    """BIM element group returned from the API.

    ``member_element_ids`` is the resolved list of element UUIDs. For dynamic
    groups this mirrors the freshly-recomputed cache; for static groups it
    mirrors the persisted ``element_ids`` snapshot. Clients should use this
    field for rendering instead of ``element_ids``.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    model_id: UUID | None = None
    name: str
    description: str | None = None
    is_dynamic: bool
    filter_criteria: dict[str, Any] = Field(default_factory=dict)
    element_ids: list[UUID] = Field(default_factory=list)
    element_count: int = 0
    color: str | None = None
    created_by: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime
    member_element_ids: list[UUID] = Field(default_factory=list)


# ── Smart Views — canonical-format rule builder (Phase 2.A) ─────────────────


class SmartViewPropertyEntry(BaseModel):
    """One row in the Property Catalog returned to the Smart View builder.

    The catalog is the union of every queryable field exposed by the
    canonical element format, grouped by Identity / Geometry / Quantities
    / Properties and stamped with the source-format badge ("RVT" / "IFC"
    / "DWG" / "DGN" / "PDF").  ``sample_values`` is the alphabetically
    sorted prefix of the distinct values observed in the model — feeds
    enum dropdowns in the UI without an extra fetch.
    """

    model_config = ConfigDict(extra="forbid")

    field: str
    label: str
    group: Literal["identity", "geometry", "quantities", "properties"]
    data_type: Literal["string", "number", "enum", "boolean"]
    source_formats: list[str] = Field(default_factory=list)
    sample_values: list[str] = Field(default_factory=list)
    distinct_count: int = 0
    truncated: bool = False


class SmartViewPropertyCatalogResponse(BaseModel):
    """Property catalog payload returned by ``GET /smart-views/properties``."""

    model_config = ConfigDict(extra="forbid")

    model_id: UUID | None = None
    source_format: str = "other"
    element_count: int = 0
    entries: list[SmartViewPropertyEntry] = Field(default_factory=list)


class SmartViewPreviewRequest(BaseModel):
    """Body of ``POST /smart-views/preview``.

    ``rule_tree`` is the validated rule tree (see ``smart_views.py``);
    callers may also send the legacy ``filter_criteria`` shape and the
    server will up-convert it on the fly.
    """

    model_config = ConfigDict(extra="forbid")

    model_id: UUID | None = None
    project_id: UUID | None = None
    rule_tree: dict[str, Any] | None = None
    filter_criteria: dict[str, Any] | None = None
    sample_limit: int = Field(default=20, ge=0, le=200)


class SmartViewPreviewResponse(BaseModel):
    """Element count + sample id list for a Smart View rule tree."""

    model_config = ConfigDict(extra="forbid")

    matched_count: int = 0
    sample_element_ids: list[UUID] = Field(default_factory=list)
    truncated: bool = False
    normalised_rule_tree: dict[str, Any] = Field(default_factory=dict)


# ── Model schema introspection (RFC 24 — Quantity Rules editor) ──────────────


class BIMModelSchemaResponse(BaseModel):
    """Distinct types + property keys/values harvested from a BIM model.

    Feeds the quantity-rule editor comboboxes so the user picks real values
    from their actual model instead of typing blindly. Caps at 1000 distinct
    values per property to protect the response payload.
    """

    distinct_types: list[str] = Field(default_factory=list)
    property_keys: dict[str, list[str]] = Field(default_factory=dict)
    property_keys_truncated: dict[str, bool] = Field(default_factory=dict)
    available_quantities: list[str] = Field(
        default_factory=lambda: ["area_m2", "volume_m3", "length_m", "weight_kg", "count"],
    )
    element_count: int = 0
    member_element_ids: list[UUID] = Field(default_factory=list)


# ── BIM Federation schemas (v4.0 / Slice 1) ──────────────────────────────────


FederationDiscipline = Literal[
    "arch",
    "struct",
    "mep",
    "landscape",
    "civil",
    "other",
]


class FederationOriginOffset(BaseModel):
    """Shared origin offset applied to every federation member at render time."""

    model_config = ConfigDict(extra="forbid")

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


class FederationCreate(BaseModel):
    """Create a new BIM federation under a project."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    origin_offset: FederationOriginOffset = Field(default_factory=FederationOriginOffset)
    shared_units: str = Field(default="m", min_length=1, max_length=20)


class FederationUpdate(BaseModel):
    """Partial update for a federation header (metadata only)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    origin_offset: FederationOriginOffset | None = None
    shared_units: str | None = Field(default=None, min_length=1, max_length=20)


class FederationModelAdd(BaseModel):
    """Add an existing BIM model to a federation."""

    model_config = ConfigDict(str_strip_whitespace=True)

    bim_model_id: UUID
    discipline: FederationDiscipline = "other"
    color_hint: str | None = Field(default=None, max_length=20)
    visible: bool = True
    z_order: int = 0


class FederationModelResponse(BaseModel):
    """A single member-model link inside a federation."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    federation_id: UUID
    bim_model_id: UUID
    discipline: str
    color_hint: str | None = None
    visible: bool
    z_order: int
    created_at: datetime
    updated_at: datetime


class FederationResponse(BaseModel):
    """Federation header (no members) returned from list / create endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    name: str
    description: str | None = None
    origin_offset: dict[str, Any] = Field(default_factory=dict)
    shared_units: str
    member_count: int = 0
    created_at: datetime
    updated_at: datetime


class FederationFullResponse(FederationResponse):
    """Federation header *plus* its members, ordered by z_order ascending."""

    members: list[FederationModelResponse] = Field(default_factory=list)


class FederationListResponse(BaseModel):
    """Paginated federation list."""

    items: list[FederationResponse] = Field(default_factory=list)
    total: int = 0


# ── Federation Type Tree (v4.0 / Slice 2) ─────────────────────────────────
#
# Counter-intuitive design note
# -----------------------------
# Most BIM viewers nest the federation tree as
# ``Federation › Model › Storey › Element``. BIMcollab Zoom inverts it to
# ``Federation › IfcClass › [all instances across all models]``. The flat-
# by-class layout is what makes "color all mechanical ducts red across 12
# models" a single click instead of a 12-step traversal. The endpoint and
# schemas below model the flat-by-class shape; the per-model split is
# kept as a drill-down (``member_breakdown``) so the user can still see
# how a given class is distributed across the federation members.


class FederationTypeTreeMember(BaseModel):
    """Per-member breakdown for one IfcClass inside the federation.

    Surfaces in the type-tree drill-down: "IfcWall has 1 234 instances
    across 3 members — 600 in ARCH, 500 in STRUCT, 134 in MEP".
    """

    model_config = ConfigDict(from_attributes=True)

    model_id: UUID
    model_name: str
    discipline: str
    element_count: int


class FederationTypeTreeClass(BaseModel):
    """A single IfcClass row in the federation-flat type tree."""

    model_config = ConfigDict(from_attributes=True)

    ifc_class: str
    display_name: str
    element_count: int
    member_breakdown: list[FederationTypeTreeMember] = Field(default_factory=list)
    sample_properties: list[str] = Field(default_factory=list)


class FederationTypeTreeResponse(BaseModel):
    """Aggregated, federation-flat type tree response.

    Empty (``total_elements=0``, ``classes=[]``) but valid when the
    federation has no members or none of the members have ingested
    elements yet — the page renders an explicit empty state instead of
    blowing up.
    """

    model_config = ConfigDict(from_attributes=True)

    federation_id: UUID
    total_elements: int = 0
    classes: list[FederationTypeTreeClass] = Field(default_factory=list)
