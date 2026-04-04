"""Markups & Annotations Pydantic schemas — request/response models.

Defines create, update, and response schemas for markups, scale configs,
and stamp templates.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ── Markup schemas ──────────────────────────────────────────────────────


class MarkupCreate(BaseModel):
    """Create a new markup annotation."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    document_id: str | None = None
    page: int = Field(default=1, ge=1)
    type: str = Field(
        ...,
        max_length=50,
        pattern=r"^(cloud|arrow|text|rectangle|highlight|distance|area|count|stamp|polygon)$",
    )
    geometry: dict[str, Any] = Field(default_factory=dict)
    text: str | None = None
    color: str = Field(default="#3b82f6", max_length=20)
    line_width: int = Field(default=2, ge=1, le=50)
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    author_id: str | None = Field(default=None, max_length=255)
    status: str = Field(
        default="active",
        pattern=r"^(active|resolved|archived)$",
    )
    label: str | None = Field(default=None, max_length=255)
    measurement_value: float | None = None
    measurement_unit: str | None = Field(default=None, max_length=20)
    stamp_template_id: UUID | None = None
    linked_boq_position_id: str | None = Field(default=None, max_length=255)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MarkupUpdate(BaseModel):
    """Partial update for a markup annotation."""

    model_config = ConfigDict(str_strip_whitespace=True)

    document_id: str | None = None
    page: int | None = Field(default=None, ge=1)
    type: str | None = Field(
        default=None,
        max_length=50,
        pattern=r"^(cloud|arrow|text|rectangle|highlight|distance|area|count|stamp|polygon)$",
    )
    geometry: dict[str, Any] | None = None
    text: str | None = None
    color: str | None = Field(default=None, max_length=20)
    line_width: int | None = Field(default=None, ge=1, le=50)
    opacity: float | None = Field(default=None, ge=0.0, le=1.0)
    status: str | None = Field(
        default=None,
        pattern=r"^(active|resolved|archived)$",
    )
    label: str | None = Field(default=None, max_length=255)
    measurement_value: float | None = None
    measurement_unit: str | None = Field(default=None, max_length=20)
    stamp_template_id: UUID | None = None
    linked_boq_position_id: str | None = Field(default=None, max_length=255)
    metadata: dict[str, Any] | None = None


class MarkupResponse(BaseModel):
    """Markup annotation returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    document_id: str | None = None
    page: int = 1
    type: str
    geometry: dict[str, Any] = Field(default_factory=dict)
    text: str | None = None
    color: str = "#3b82f6"
    line_width: int = 2
    opacity: float = 1.0
    author_id: str
    status: str = "active"
    label: str | None = None
    measurement_value: float | None = None
    measurement_unit: str | None = None
    stamp_template_id: UUID | None = None
    linked_boq_position_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_by: str = ""
    created_at: datetime
    updated_at: datetime


class MarkupBulkCreate(BaseModel):
    """Bulk create multiple markups at once."""

    markups: list[MarkupCreate] = Field(..., min_length=1, max_length=500)


class MarkupSummary(BaseModel):
    """Aggregated markup stats for a project."""

    total_markups: int = 0
    by_type: dict[str, int] = Field(default_factory=dict)
    by_status: dict[str, int] = Field(default_factory=dict)


class BoqLinkRequest(BaseModel):
    """Request body for linking a markup to a BOQ position."""

    position_id: str = Field(..., min_length=1, max_length=255)


# ── Scale Config schemas ────────────────────────────────────────────────


class ScaleConfigCreate(BaseModel):
    """Create or update a scale calibration config."""

    model_config = ConfigDict(str_strip_whitespace=True)

    document_id: str = Field(..., max_length=255)
    page: int = Field(default=1, ge=1)
    pixels_per_unit: float = Field(..., gt=0.0)
    unit_label: str = Field(default="m", max_length=20)
    calibration_points: dict[str, Any] = Field(default_factory=dict)
    real_distance: float = Field(..., gt=0.0)


class ScaleConfigResponse(BaseModel):
    """Scale config returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: str
    page: int = 1
    pixels_per_unit: float
    unit_label: str = "m"
    calibration_points: dict[str, Any] = Field(default_factory=dict)
    real_distance: float
    created_by: str = ""
    created_at: datetime
    updated_at: datetime


# ── Stamp Template schemas ──────────────────────────────────────────────


class StampTemplateCreate(BaseModel):
    """Create a new stamp template."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID | None = None
    name: str = Field(..., min_length=1, max_length=255)
    category: str = Field(
        default="custom",
        pattern=r"^(predefined|custom)$",
    )
    text: str = Field(..., min_length=1, max_length=500)
    color: str = Field(default="#22c55e", max_length=20)
    background_color: str | None = Field(default=None, max_length=20)
    icon: str | None = Field(default=None, max_length=100)
    include_date: bool = True
    include_name: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class StampTemplateUpdate(BaseModel):
    """Partial update for a stamp template."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    text: str | None = Field(default=None, min_length=1, max_length=500)
    color: str | None = Field(default=None, max_length=20)
    background_color: str | None = Field(default=None, max_length=20)
    icon: str | None = Field(default=None, max_length=100)
    include_date: bool | None = None
    include_name: bool | None = None
    is_active: bool | None = None
    metadata: dict[str, Any] | None = None


class StampTemplateResponse(BaseModel):
    """Stamp template returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID | None = None
    owner_id: str
    name: str
    category: str = "custom"
    text: str
    color: str = "#22c55e"
    background_color: str | None = None
    icon: str | None = None
    include_date: bool = True
    include_name: bool = True
    is_active: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime
