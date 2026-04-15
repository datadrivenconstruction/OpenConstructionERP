"""DWG Takeoff Pydantic schemas — request/response models.

Defines create, update, and response schemas for DWG drawings,
drawing versions, annotations, and measurement results.
"""

from datetime import datetime
from typing import Any
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
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_by: str = ""
    created_at: datetime
    updated_at: datetime
    latest_version: "DwgDrawingVersionResponse | None" = None


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
        pattern=r"^(text_pin|arrow|rectangle|distance|area)$",
    )
    geometry: dict[str, Any] = Field(default_factory=dict)
    text: str | None = None
    color: str = Field(default="#3b82f6", max_length=20)
    line_width: int = Field(default=2, ge=1, le=50)
    measurement_value: float | None = None
    measurement_unit: str | None = Field(default=None, max_length=20)
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
        pattern=r"^(text_pin|arrow|rectangle|distance|area)$",
    )
    geometry: dict[str, Any] | None = None
    text: str | None = None
    color: str | None = Field(default=None, max_length=20)
    line_width: int | None = Field(default=None, ge=1, le=50)
    measurement_value: float | None = None
    measurement_unit: str | None = Field(default=None, max_length=20)
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
    measurement_value: float | None = None
    measurement_unit: str | None = None
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


# ── Measurement result ─────────────────────────────────────────────────


class DwgMeasurementResult(BaseModel):
    """Result of a measurement calculation on a DWG entity."""

    entity_type: str
    value: float
    unit: str = "m"
    method: str = "calculated"


# Forward reference resolution
DwgDrawingResponse.model_rebuild()
