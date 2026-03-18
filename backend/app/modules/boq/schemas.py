"""BOQ Pydantic schemas — request/response models.

Defines create, update, and response schemas for BOQs and positions.
Numeric values (quantity, unit_rate, total) are exposed as floats in the API
but stored as strings in SQLite-compatible models.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ── BOQ schemas ───────────────────────────────────────────────────────────────


class BOQCreate(BaseModel):
    """Create a new Bill of Quantities."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    name: str = Field(..., min_length=1, max_length=255)
    description: str = ""


class BOQUpdate(BaseModel):
    """Partial update for a BOQ."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    status: str | None = Field(default=None, pattern=r"^(draft|final|archived)$")
    metadata: dict[str, Any] | None = None


class BOQResponse(BaseModel):
    """BOQ returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    name: str
    description: str
    status: str
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Position schemas ──────────────────────────────────────────────────────────


class PositionCreate(BaseModel):
    """Create a new BOQ position."""

    model_config = ConfigDict(str_strip_whitespace=True)

    boq_id: UUID
    parent_id: UUID | None = None
    ordinal: str = Field(..., min_length=1, max_length=50)
    description: str = Field(default='')
    unit: str = Field(..., min_length=1, max_length=20)
    quantity: float = Field(default=0.0, ge=0.0)
    unit_rate: float = Field(default=0.0, ge=0.0)
    classification: dict[str, Any] = Field(default_factory=dict)
    source: str = "manual"
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    cad_element_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PositionUpdate(BaseModel):
    """Partial update for a BOQ position."""

    model_config = ConfigDict(str_strip_whitespace=True)

    parent_id: UUID | None = None
    ordinal: str | None = Field(default=None, min_length=1, max_length=50)
    description: str | None = Field(default=None)
    unit: str | None = Field(default=None, min_length=1, max_length=20)
    quantity: float | None = Field(default=None, ge=0.0)
    unit_rate: float | None = Field(default=None, ge=0.0)
    classification: dict[str, Any] | None = None
    source: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    cad_element_ids: list[str] | None = None
    validation_status: str | None = None
    metadata: dict[str, Any] | None = None
    sort_order: int | None = None


class PositionResponse(BaseModel):
    """Position returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    boq_id: UUID
    parent_id: UUID | None
    ordinal: str
    description: str
    unit: str
    quantity: float
    unit_rate: float
    total: float
    classification: dict[str, Any]
    source: str
    confidence: float | None
    cad_element_ids: list[str]
    validation_status: str
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")
    sort_order: int
    created_at: datetime
    updated_at: datetime


# ── Composite schemas ─────────────────────────────────────────────────────────


class BOQWithPositions(BOQResponse):
    """BOQ with all its positions and computed grand total."""

    positions: list[PositionResponse] = Field(default_factory=list)
    grand_total: float = 0.0
