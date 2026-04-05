"""Takeoff Pydantic schemas (request/response)."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TakeoffDocumentResponse(BaseModel):
    """Response after uploading a PDF document."""

    id: str
    filename: str
    pages: int
    size_bytes: int
    status: str
    content_type: str
    uploaded_at: datetime | None = Field(None, alias="created_at")

    model_config = {"from_attributes": True, "populate_by_name": True}


class ExtractedElement(BaseModel):
    """A single element extracted from AI analysis."""

    id: str
    category: str
    description: str
    quantity: float
    unit: str
    confidence: float


class AnalysisResultResponse(BaseModel):
    """AI analysis result for a document."""

    elements: list[ExtractedElement]
    summary: dict


class ExtractTablesResponse(BaseModel):
    """Table extraction result for a document."""

    elements: list[ExtractedElement]
    summary: dict


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
    """A single 2D point in page coordinates."""

    x: float
    y: float


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
        description="Measurement type: distance, area, count, polyline, volume",
    )
    group_name: str = Field(default="General", max_length=100)
    group_color: str = Field(default="#3B82F6", max_length=20)
    annotation: str | None = Field(default=None, max_length=500)
    points: list[PointSchema] = Field(default_factory=list)
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
    points: list[PointSchema] | None = None
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

    measurements: list[TakeoffMeasurementCreate] = Field(
        ..., min_length=1, max_length=500
    )


class TakeoffMeasurementSummary(BaseModel):
    """Aggregated measurement stats for a project."""

    total_measurements: int = 0
    by_type: dict[str, int] = Field(default_factory=dict)
    by_group: dict[str, int] = Field(default_factory=dict)
    by_page: dict[int, int] = Field(default_factory=dict)


class LinkToBoqRequest(BaseModel):
    """Request to link a measurement to a BOQ position."""

    boq_position_id: str = Field(..., min_length=1, max_length=255)
