# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠DWG Takeoff Pydantic schemas - request/response models.

Defines create, update, and response schemas for DWG drawings,
drawing versions, annotations, and measurement results.
"""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ── Drawing schemas ────────────────────────────────────────────────────


class DwgDrawingCreate(BaseModel):
    """Create a new DWG drawing record (file uploaded separately via multipart)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    name: str = Field(..., min_length=1, max_length=500)
    discipline: str | None = Field(default=None, max_length=100)
    sheet_number: str | None = Field(default=None, max_length=100)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DwgDrawingFromDocument(BaseModel):
    """Create a DWG drawing from an existing Document on demand.

    Used by the Documents / File Manager "Open in DWG Takeoff" action so a
    CAD file uploaded outside the takeoff module still opens directly in the
    viewer. ``document_id`` must reference a ``.dwg`` / ``.dxf`` document the
    caller can access; the endpoint is idempotent per document.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    document_id: UUID
    name: str | None = Field(default=None, max_length=500)
    discipline: str | None = Field(default=None, max_length=100)


class DwgDrawingResponse(BaseModel):
    """DWG drawing returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    name: str
    filename: str
    file_format: str = "dxf"
    size_bytes: int = 0
    status: str = "uploaded"
    discipline: str | None = None
    sheet_number: str | None = None
    thumbnail_key: str | None = None
    error_message: str | None = None
    scale_denominator: float = 1.0
    scale_mode: str = "preset"
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_by: str = ""
    created_at: datetime
    updated_at: datetime
    latest_version: "DwgDrawingVersionResponse | None" = None


class DwgDrawingScaleUpdate(BaseModel):
    """Persist the scale for a drawing - replaces localStorage-only storage."""

    model_config = ConfigDict(str_strip_whitespace=True)

    scale_denominator: float = Field(..., gt=0, le=100_000)
    scale_mode: str = Field(
        default="preset",
        pattern=r"^(preset|calibrated|per_annotation)$",
    )


# ── Drawing Version schemas ────────────────────────────────────────────


class DwgDrawingVersionResponse(BaseModel):
    """Drawing version returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    drawing_id: UUID
    version_number: int = 1
    layers: list[dict[str, Any]] = Field(default_factory=list)
    entities_key: str | None = None
    entity_count: int = 0
    extents: dict[str, Any] = Field(default_factory=dict)
    units: str | None = None
    status: str = "processing"
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime

    @field_validator("layers", mode="before")
    @classmethod
    def _normalize_layers(cls, v: Any) -> list[dict[str, Any]]:
        """Accept both list and legacy dict-keyed-by-name formats."""
        if isinstance(v, dict):
            return list(v.values()) if v else []
        if isinstance(v, list):
            return v
        return []


# ── Layer schemas ──────────────────────────────────────────────────────


class DwgLayerInfo(BaseModel):
    """Information about a single DWG layer."""

    name: str
    color: str | None = None
    visible: bool = True
    entity_count: int = 0


class DwgLayerVisibilityUpdate(BaseModel):
    """Update layer visibility settings."""

    layers: dict[str, bool] = Field(
        ...,
        description="Mapping of layer name to visibility boolean",
    )


# ── Entity schemas ─────────────────────────────────────────────────────


class DwgEntityInfo(BaseModel):
    """Information about a single DWG entity."""

    entity_type: str
    layer: str = ""
    color: str | None = None
    geometry_data: dict[str, Any] = Field(default_factory=dict)


# ── Annotation schemas ─────────────────────────────────────────────────


class DwgAnnotationCreate(BaseModel):
    """Create a new annotation on a DWG drawing."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    drawing_id: UUID
    drawing_version_id: UUID | None = None
    annotation_type: str = Field(
        ...,
        max_length=50,
        pattern=r"^(text_pin|arrow|rectangle|distance|area|circle|polyline|line|count)$",
    )
    geometry: dict[str, Any] = Field(default_factory=dict)
    text: str | None = None
    color: str = Field(default="#3b82f6", max_length=20)
    line_width: int = Field(default=2, ge=1, le=50)
    thickness: float = Field(default=2.0, ge=0.1, le=50.0)
    layer_name: str = Field(default="USER_MARKUP", max_length=100)
    measurement_value: float | None = None
    measurement_unit: str | None = Field(default=None, max_length=20)
    scale_override: float | None = Field(default=None, gt=0, le=100_000)
    linked_boq_position_id: str | None = Field(default=None, max_length=255)
    linked_task_id: str | None = Field(default=None, max_length=255)
    linked_punch_item_id: str | None = Field(default=None, max_length=255)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DwgAnnotationUpdate(BaseModel):
    """Partial update for an annotation."""

    model_config = ConfigDict(str_strip_whitespace=True)

    annotation_type: str | None = Field(
        default=None,
        max_length=50,
        pattern=r"^(text_pin|arrow|rectangle|distance|area|circle|polyline|line|count)$",
    )
    geometry: dict[str, Any] | None = None
    text: str | None = None
    color: str | None = Field(default=None, max_length=20)
    line_width: int | None = Field(default=None, ge=1, le=50)
    thickness: float | None = Field(default=None, ge=0.1, le=50.0)
    layer_name: str | None = Field(default=None, max_length=100)
    measurement_value: float | None = None
    measurement_unit: str | None = Field(default=None, max_length=20)
    scale_override: float | None = Field(default=None, gt=0, le=100_000)
    linked_boq_position_id: str | None = Field(default=None, max_length=255)
    linked_task_id: str | None = Field(default=None, max_length=255)
    linked_punch_item_id: str | None = Field(default=None, max_length=255)
    metadata: dict[str, Any] | None = None


class DwgAnnotationResponse(BaseModel):
    """Annotation returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    drawing_id: UUID
    drawing_version_id: UUID | None = None
    annotation_type: str
    geometry: dict[str, Any] = Field(default_factory=dict)
    text: str | None = None
    color: str = "#3b82f6"
    line_width: int = 2
    thickness: float = 2.0
    layer_name: str = "USER_MARKUP"
    measurement_value: float | None = None
    measurement_unit: str | None = None
    scale_override: float | None = None
    linked_boq_position_id: str | None = None
    linked_task_id: str | None = None
    linked_punch_item_id: str | None = None
    created_by: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── BOQ link ───────────────────────────────────────────────────────────


class BoqLinkRequest(BaseModel):
    """Request body for linking an annotation to a BOQ position."""

    position_id: str = Field(..., min_length=1, max_length=255)
    push_quantity: bool = Field(
        default=False,
        description=(
            "When true, copy the annotation's measured value into the "
            "target BOQ position's quantity and recompute the position "
            "total. An annotation with no usable value is a no-op (the "
            "existing quantity is left untouched). Default false keeps "
            "existing callers backward-compatible."
        ),
    )


# ── Measurement result ─────────────────────────────────────────────────


class DwgMeasurementResult(BaseModel):
    """Result of a measurement calculation on a DWG entity."""

    entity_type: str
    value: float
    unit: str = "m"
    method: str = "calculated"


# ── Entity Group schemas (RFC 11) ──────────────────────────────────────


class DwgEntityGroupCreate(BaseModel):
    """Create a saved group of DWG entities."""

    model_config = ConfigDict(str_strip_whitespace=True)

    drawing_id: UUID
    entity_ids: list[str] = Field(..., min_length=1)
    name: str = Field(..., min_length=1, max_length=200)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DwgEntityGroupResponse(BaseModel):
    """A saved entity group returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    drawing_id: UUID
    entity_ids: list[str] = Field(default_factory=list)
    name: str
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Offline readiness (R3 #9) ──────────────────────────────────────────


class DwgOfflineReadinessResponse(BaseModel):
    """Local-converter availability probe result for the DWG takeoff page.

    Sibling to the BIM converter-preflight endpoint. ``ready`` is the
    top-level traffic light shown in the UI badge; ``converter_available``
    is what actually drives it (everything else already runs locally).
    """

    ready: bool
    converter_available: bool
    version: str | None = None
    message: str
    # True only when the request reached the backend over the loopback
    # interface AND the server is not a hosted/production deployment - i.e.
    # the browser and the server genuinely run on the same machine, so the
    # "your files never leave your computer" claim is literally true. On a
    # hosted demo this is False and the UI must show the honest "processed
    # on your OpenConstructionERP server" copy instead. Defaults to False so
    # the strong claim is never shown unless explicitly earned.
    local_only: bool = False


# ── Revision compare (Item 17) ─────────────────────────────────────────


class DwgEntityDiffRow(BaseModel):
    """One entity-level change between two parsed drawing versions.

    Entities have no stable identity across re-parses (ezdxf/DDC do not
    preserve handles), so the diff is computed on the *layer profile*:
    for each layer we compare the entity count in the old vs the new
    version. ``entity_id`` is therefore the layer name (the unit the
    user actually toggles in the LayerPanel) and ``delta`` carries the
    signed change in entity count.
    """

    change_type: Literal["added", "removed", "modified", "unchanged"]
    entity_id: str
    entity_type: str
    layer: str
    old_count: int = 0
    new_count: int = 0
    delta: int = 0


class DwgAnnotationDiffRow(BaseModel):
    """One annotation-level change between two drawing versions.

    Annotations DO carry a stable identity (``drawing_version_id`` links
    each annotation to the version it was drawn on), so additions /
    removals / measurement changes are detected per annotation. When an
    annotation is linked to a BOQ position and its measured value
    changed, ``cost_impact`` carries the signed money delta
    ``(new - old) * unit_rate`` in the project's base currency (Decimal
    string; never blended across currencies).
    """

    change_type: Literal["added", "removed", "modified", "unchanged"]
    annotation_id: str
    annotation_type: str
    label: str | None = None
    layer_name: str = "USER_MARKUP"
    old_measurement: float | None = None
    new_measurement: float | None = None
    measurement_unit: str | None = None
    linked_boq_position_id: str | None = None
    cost_impact: str | None = None  # signed Decimal string in base currency
    cost_currency: str | None = None


class DwgDrawingDiffResponse(BaseModel):
    """Full revision-compare payload for a drawing diff.

    ``drawing_id`` is always populated. On the single-drawing path it is
    the drawing whose version pair was diffed. On a drawing-vs-drawing
    compare (two independently uploaded drawings), ``from_drawing_id`` /
    ``to_drawing_id`` additionally identify each side so the UI can label
    both; ``drawing_id`` then carries the baseline drawing for back-compat.
    """

    drawing_id: UUID
    from_drawing_id: UUID | None = None
    to_drawing_id: UUID | None = None
    from_version_id: UUID
    from_version_number: int
    to_version_id: UUID
    to_version_number: int
    entity_rows: list[DwgEntityDiffRow] = Field(default_factory=list)
    annotation_rows: list[DwgAnnotationDiffRow] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)


# ── Create-variation-from-delta handoff (Item 17) ───────────────────────


class CreateVariationFromDiffRequest(BaseModel):
    """Turn a revision-compare delta into a draft variation request.

    The diff itself is recomputed server-side from the two version ids
    (the deterministic :meth:`compare_drawing_versions` is the single
    source of truth), so the client only carries the version pair and an
    optional title override. The created variation is always a *draft* -
    AI/automation proposes, a human confirms and submits it.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    from_version_id: UUID
    to_version_id: UUID
    title: str | None = Field(default=None, max_length=500)


class CreateVariationFromPairRequest(BaseModel):
    """Turn a drawing-vs-drawing compare delta into a draft variation request.

    Mirrors :class:`CreateVariationFromDiffRequest` for the drawing-pair
    path (two independently uploaded drawings). The compare is recomputed
    server-side from the project + drawing pair (the deterministic
    :meth:`compare_drawing_pair` is the single source of truth), so the
    client carries only the ids and an optional title override. The created
    variation is always a *draft* - automation proposes, a human confirms.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    from_drawing_id: UUID
    to_drawing_id: UUID
    title: str | None = Field(default=None, max_length=500)


class CreateVariationFromDiffResponse(BaseModel):
    """The draft variation request minted from a revision-compare delta."""

    variation_request_id: UUID
    code: str
    estimated_cost_impact: str = "0"  # signed Decimal string in base currency
    currency: str = ""


# Forward reference resolution
DwgDrawingResponse.model_rebuild()
