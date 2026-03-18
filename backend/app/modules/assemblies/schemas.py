"""Assembly Pydantic schemas — request/response models.

Defines create, update, and response schemas for assemblies and components.
Numeric values (factor, quantity, unit_cost, total, total_rate, bid_factor)
are exposed as floats in the API but stored as strings in the database for
SQLite compatibility.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ── Component schemas ────────────────────────────────────────────────────────


class ComponentCreate(BaseModel):
    """Create a new assembly component."""

    model_config = ConfigDict(str_strip_whitespace=True)

    cost_item_id: UUID | None = None
    description: str = Field(default='', max_length=500)
    factor: float = Field(default=1.0)
    quantity: float = Field(default=1.0)
    unit: str = Field(..., min_length=1, max_length=20)
    unit_cost: float = Field(default=0.0, ge=0.0)


class ComponentUpdate(BaseModel):
    """Partial update for an assembly component."""

    model_config = ConfigDict(str_strip_whitespace=True)

    cost_item_id: UUID | None = None
    description: str | None = Field(default=None, max_length=500)
    factor: float | None = None
    quantity: float | None = None
    unit: str | None = Field(default=None, min_length=1, max_length=20)
    unit_cost: float | None = Field(default=None, ge=0.0)
    sort_order: int | None = None
    metadata: dict[str, Any] | None = None


class ComponentResponse(BaseModel):
    """Component returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    assembly_id: UUID
    cost_item_id: UUID | None
    description: str
    factor: float
    quantity: float
    unit: str
    unit_cost: float
    total: float
    sort_order: int
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Assembly schemas ─────────────────────────────────────────────────────────


class AssemblyCreate(BaseModel):
    """Create a new assembly."""

    model_config = ConfigDict(str_strip_whitespace=True)

    code: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=255)
    description: str = ""
    unit: str = Field(..., min_length=1, max_length=20)
    category: str = ""
    classification: dict[str, Any] = Field(default_factory=dict)
    currency: str = Field(default="EUR", max_length=10)
    bid_factor: float = Field(default=1.0)
    regional_factors: dict[str, Any] = Field(default_factory=dict)
    is_template: bool = True
    project_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AssemblyUpdate(BaseModel):
    """Partial update for an assembly."""

    model_config = ConfigDict(str_strip_whitespace=True)

    code: str | None = Field(default=None, min_length=1, max_length=100)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    unit: str | None = Field(default=None, min_length=1, max_length=20)
    category: str | None = None
    classification: dict[str, Any] | None = None
    currency: str | None = Field(default=None, max_length=10)
    bid_factor: float | None = None
    regional_factors: dict[str, Any] | None = None
    is_template: bool | None = None
    project_id: UUID | None = None
    is_active: bool | None = None
    metadata: dict[str, Any] | None = None


class AssemblyResponse(BaseModel):
    """Assembly returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    code: str
    name: str
    description: str
    unit: str
    category: str
    classification: dict[str, Any]
    total_rate: float
    currency: str
    bid_factor: float
    regional_factors: dict[str, Any]
    is_template: bool
    project_id: UUID | None
    owner_id: UUID | None
    is_active: bool
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Composite schemas ────────────────────────────────────────────────────────


class AssemblyWithComponents(AssemblyResponse):
    """Assembly with all its components and computed total."""

    components: list[ComponentResponse] = Field(default_factory=list)
    computed_total: float = 0.0


# ── Action schemas ───────────────────────────────────────────────────────────


class ApplyToBOQRequest(BaseModel):
    """Request body for applying an assembly to a BOQ as a new position."""

    boq_id: UUID
    quantity: float = Field(..., gt=0.0)
    ordinal: str = Field(default="", max_length=50, description="Position ordinal; auto-generated if empty")
    region: str | None = Field(default=None, description="Region key for regional factor lookup")


class CloneAssemblyRequest(BaseModel):
    """Request body for cloning an assembly."""

    new_code: str | None = Field(default=None, min_length=1, max_length=100)
    project_id: UUID | None = None
