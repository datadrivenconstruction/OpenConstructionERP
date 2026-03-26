"""Catalog resource Pydantic schemas for request/response validation."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ── Create ────────────────────────────────────────────────────────────────


class CatalogResourceCreate(BaseModel):
    """Create a new catalog resource."""

    resource_code: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=500)
    resource_type: str = Field(
        ..., min_length=1, max_length=20, description="material, equipment, labor, operator"
    )
    category: str = Field(..., min_length=1, max_length=100)
    unit: str = Field(..., min_length=1, max_length=20)
    base_price: float = Field(..., ge=0)
    min_price: float = Field(default=0, ge=0)
    max_price: float = Field(default=0, ge=0)
    currency: str = Field(default="EUR", max_length=10)
    source: str = Field(default="manual", max_length=50)
    region: str | None = Field(default=None, max_length=50)
    specifications: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Response ──────────────────────────────────────────────────────────────


class CatalogResourceResponse(BaseModel):
    """Catalog resource in API responses."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    resource_code: str
    name: str
    resource_type: str
    category: str
    unit: str
    base_price: float
    min_price: float
    max_price: float
    currency: str
    usage_count: int
    source: str
    region: str | None
    specifications: dict[str, Any]
    is_active: bool
    metadata: dict[str, Any] = Field(alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Search ────────────────────────────────────────────────────────────────


class CatalogSearchQuery(BaseModel):
    """Query parameters for catalog resource search."""

    q: str | None = Field(default=None, description="Text search on code and name")
    resource_type: str | None = Field(
        default=None, description="Filter by type: material, equipment, labor, operator"
    )
    category: str | None = Field(default=None, description="Filter by category")
    region: str | None = Field(default=None, description="Filter by region")
    unit: str | None = Field(default=None, description="Filter by unit")
    min_price: float | None = Field(default=None, ge=0)
    max_price: float | None = Field(default=None, ge=0)
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


class CatalogSearchResponse(BaseModel):
    """Paginated search response for catalog resources."""

    items: list[CatalogResourceResponse]
    total: int
    limit: int
    offset: int


# ── Stats ─────────────────────────────────────────────────────────────────


class CatalogTypeStat(BaseModel):
    """Count of resources by type."""

    resource_type: str
    count: int


class CatalogCategoryStat(BaseModel):
    """Count of resources by category."""

    category: str
    count: int


class CatalogStatsResponse(BaseModel):
    """Aggregated statistics for the catalog."""

    total: int
    by_type: list[CatalogTypeStat]
    by_category: list[CatalogCategoryStat]
