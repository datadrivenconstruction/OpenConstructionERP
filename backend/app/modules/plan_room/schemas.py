# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Plan Room Pydantic schemas - request / response models.

The read-only overlay composite (positioned pins, markups, measurements and
photos) for one document page, plus the create schema for a positioned photo /
note pin. No money is involved. Normalized page coordinates are validated to
``[0.0, 1.0]`` at the edge. Quantity values that are ``Decimal`` on their source
row (markup / measurement values) are rendered as strings so no binary-float
drift is introduced on the read path.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# -- Plan pin (owned by this module) ----------------------------------------


class PlanPinCreate(BaseModel):
    """Create a positioned photo / note pin on a document page.

    ``page`` is required and must match the page in the request URL; ``x`` and
    ``y`` are normalized page coordinates in ``[0, 1]``.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    page: int = Field(..., ge=1)
    x: float = Field(..., ge=0.0, le=1.0)
    y: float = Field(..., ge=0.0, le=1.0)
    note: str | None = None
    photo_ref: str | None = Field(default=None, max_length=500)
    file_version_id: str | None = Field(default=None, max_length=36)
    metadata: dict[str, Any] = Field(default_factory=dict)


PIN_TARGET_KINDS = ("rfi", "punch", "inspection", "ncr", "photo", "observation", "note")
PIN_REVISION_STATES = ("current", "carried", "needs_review", "orphaned")


class PlanPinResponse(BaseModel):
    """A pin returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    document_id: str
    page: int
    x: float
    y: float
    note: str | None = None
    photo_ref: str | None = None
    file_version_id: str | None = None
    created_by: str | None = None
    target_kind: str = "note"
    target_id: str | None = None
    target_label: str | None = None
    sheet_id: str | None = None
    bim_model_id: str | None = None
    bim_element_id: str | None = None
    bim_xyz: list[float] | None = None
    status: str | None = None
    revision_state: str = "current"
    carried_from_pin_id: str | None = None
    client_op_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime
    # Non-blocking findings of the plan_room rule set for the write that produced this response.
    validation_warnings: list[dict[str, Any]] = Field(default_factory=list)


class PinCreate(BaseModel):
    """Create a pin on a drawing page or on a BIM element (exactly one of the two)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    target_kind: str = Field(default="note", pattern=r"^(rfi|punch|inspection|ncr|photo|observation|note)$")
    target_id: str | None = Field(default=None, max_length=36)
    document_id: str | None = Field(default=None, max_length=255)
    page: int | None = Field(default=None, ge=1)
    x: float | None = Field(default=None, ge=0.0, le=1.0)
    y: float | None = Field(default=None, ge=0.0, le=1.0)
    sheet_id: str | None = Field(default=None, max_length=36)
    bim_model_id: str | None = Field(default=None, max_length=36)
    bim_element_id: str | None = Field(default=None, max_length=36)
    bim_xyz: list[float] | None = Field(default=None, min_length=3, max_length=3)
    note: str | None = None
    photo_ref: str | None = Field(default=None, max_length=500)
    file_version_id: str | None = Field(default=None, max_length=36)
    client_op_id: str | None = Field(default=None, min_length=8, max_length=128)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PinUpdate(BaseModel):
    """Move, relink or review a pin. Only the fields sent change."""

    model_config = ConfigDict(str_strip_whitespace=True)

    document_id: str | None = Field(default=None, max_length=255)
    page: int | None = Field(default=None, ge=1)
    x: float | None = Field(default=None, ge=0.0, le=1.0)
    y: float | None = Field(default=None, ge=0.0, le=1.0)
    sheet_id: str | None = Field(default=None, max_length=36)
    bim_model_id: str | None = Field(default=None, max_length=36)
    bim_element_id: str | None = Field(default=None, max_length=36)
    bim_xyz: list[float] | None = Field(default=None, min_length=3, max_length=3)
    target_kind: str | None = Field(default=None, pattern=r"^(rfi|punch|inspection|ncr|photo|observation|note)$")
    target_id: str | None = Field(default=None, max_length=36)
    revision_state: str | None = Field(default=None, pattern=r"^(current|carried|needs_review|orphaned)$")
    note: str | None = None


class PinListResponse(BaseModel):
    """Envelope for a list of pins."""

    items: list[PlanPinResponse]
    total: int
    offset: int = 0
    limit: int = 200


# -- Overlay composite pieces -----------------------------------------------


class OverlayPin(BaseModel):
    """A positioned pin composited onto a page overlay.

    ``kind`` is ``punch`` (a punch-list defect pin read from the punchlist
    module) or ``plan`` (a Plan Room photo / note pin owned here). Fields not
    relevant to a given kind are ``None``.
    """

    kind: str
    id: str
    x: float
    y: float
    title: str | None = None
    note: str | None = None
    status: str | None = None
    priority: str | None = None
    assigned_to: str | None = None
    photo_ref: str | None = None
    file_version_id: str | None = None
    target_kind: str | None = None
    target_id: str | None = None
    revision_state: str | None = None


class OverlayMarkup(BaseModel):
    """A drawing markup composited onto a page overlay."""

    id: str
    page: int
    type: str
    geometry: dict[str, Any] = Field(default_factory=dict)
    color: str | None = None
    line_width: int | None = None
    opacity: float | None = None
    text: str | None = None
    label: str | None = None
    layer: str | None = None
    status: str | None = None
    measurement_value: str | None = None
    measurement_unit: str | None = None
    file_version_id: str | None = None


class OverlayMeasurement(BaseModel):
    """A takeoff measurement composited onto a page overlay."""

    id: str
    type: str
    points: list[Any] = Field(default_factory=list)
    measurement_value: str | None = None
    measurement_unit: str | None = None
    group_name: str | None = None
    group_color: str | None = None
    annotation: str | None = None


class OverlayPhoto(BaseModel):
    """A project photo composited onto a page overlay (document-level).

    Photos carry no page or (x, y) on their source row, so they are surfaced at
    the document level for every page of the document.
    """

    id: str
    document_id: str | None = None
    filename: str
    thumbnail_path: str | None = None
    caption: str | None = None
    taken_at: datetime | None = None


class OverlayVersion(BaseModel):
    """The document revision the overlay was composited against."""

    document_id: str
    revision_code: str | None = None
    is_current_revision: bool | None = None


class OverlaysResponse(BaseModel):
    """Read-only composite of every overlay on one document page."""

    document_id: str
    page: int
    version: OverlayVersion
    pins: list[OverlayPin] = Field(default_factory=list)
    markups: list[OverlayMarkup] = Field(default_factory=list)
    measurements: list[OverlayMeasurement] = Field(default_factory=list)
    photos: list[OverlayPhoto] = Field(default_factory=list)
