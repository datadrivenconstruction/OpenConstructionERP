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
    """Create a new assembly component.

    Accepts ``name`` as an alias for ``description`` and ``unit_rate`` as an
    alias for ``unit_cost`` so that the AI-generate preview payload can be
    forwarded directly without field remapping on the frontend.
    ``resource_type`` is stored in the component metadata.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    cost_item_id: UUID | None = None
    catalog_resource_id: UUID | None = None
    description: str = Field(default="", max_length=500)
    name: str | None = Field(default=None, max_length=500, exclude=True)
    factor: float = Field(default=1.0)
    quantity: float = Field(default=1.0)
    unit: str = Field(..., min_length=1, max_length=20)
    unit_cost: float = Field(default=0.0, ge=0.0)
    unit_rate: float | None = Field(default=None, ge=0.0, exclude=True)
    resource_type: str | None = Field(default=None, max_length=50, exclude=True)

    def get_description(self) -> str:
        """Return description, falling back to name if description is empty."""
        return self.description or self.name or ""

    def get_unit_cost(self) -> float:
        """Return unit_cost, falling back to unit_rate if unit_cost is zero."""
        if self.unit_cost > 0:
            return self.unit_cost
        return self.unit_rate if self.unit_rate is not None else 0.0


class ComponentUpdate(BaseModel):
    """Partial update for an assembly component."""

    model_config = ConfigDict(str_strip_whitespace=True)

    cost_item_id: UUID | None = None
    catalog_resource_id: UUID | None = None
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
    catalog_resource_id: UUID | None = None
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
    component_count: int = 0
    usage_count: int = 0
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Paginated response ──────────────────────────────────────────────────────


class AssemblySearchResponse(BaseModel):
    """Paginated assembly search result."""

    items: list[AssemblyResponse]
    total: int
    limit: int
    offset: int


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


class ReorderComponentsRequest(BaseModel):
    """Request body for reordering components within an assembly."""

    component_ids: list[UUID] = Field(
        ..., min_length=1, description="Ordered list of component IDs"
    )


class AssemblyExport(BaseModel):
    """Full assembly export format for sharing/importing."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    code: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=500)
    description: str = Field(default="", max_length=5000)
    unit: str = Field(..., min_length=1, max_length=20)
    category: str = Field(default="", max_length=100)
    classification: dict[str, Any] = Field(default_factory=dict)
    currency: str = Field(default="EUR", max_length=10)
    bid_factor: float = Field(default=1.0, ge=0.0, le=1e6, allow_inf_nan=False)
    regional_factors: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list, max_length=100)
    components: list[dict[str, Any]] = Field(default_factory=list, max_length=1000)


class AssemblyImportRequest(BaseModel):
    """Request body for importing an assembly from JSON."""

    model_config = ConfigDict(extra="ignore")

    assembly: AssemblyExport
