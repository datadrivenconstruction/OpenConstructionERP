"""Cost item Pydantic schemas for request/response validation."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ── Create / Update ───────────────────────────────────────────────────────


class CostItemCreate(BaseModel):
    """Create a new cost item."""

    code: str = Field(..., min_length=1, max_length=100)
    description: str = Field(..., min_length=1)
    descriptions: dict[str, str] = Field(default_factory=dict)
    unit: str = Field(..., min_length=1, max_length=20)
    rate: float = Field(..., ge=0)
    currency: str = Field(default="EUR", max_length=10)
    source: str = Field(default="cwicr", max_length=50)
    classification: dict[str, str] = Field(default_factory=dict)
    components: list[dict[str, Any]] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    region: str | None = Field(default=None, max_length=50)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CostItemUpdate(BaseModel):
    """Update a cost item (all fields optional)."""

    code: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, min_length=1)
    descriptions: dict[str, str] | None = None
    unit: str | None = Field(default=None, min_length=1, max_length=20)
    rate: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=10)
    source: str | None = Field(default=None, max_length=50)
    classification: dict[str, str] | None = None
    components: list[dict[str, Any]] | None = None
    tags: list[str] | None = None
    region: str | None = Field(default=None, max_length=50)
    is_active: bool | None = None
    metadata: dict[str, Any] | None = None


# ── Response ──────────────────────────────────────────────────────────────


class CostItemResponse(BaseModel):
    """Cost item in API responses."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    description: str
    descriptions: dict[str, str]
    unit: str
    rate: float
    currency: str
    source: str
    classification: dict[str, str]
    components: list[dict[str, Any]]
    tags: list[str]
    region: str | None
    is_active: bool
    metadata: dict[str, Any] = Field(alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Search ────────────────────────────────────────────────────────────────


class CostSearchQuery(BaseModel):
    """Query parameters for cost item search."""

    q: str | None = Field(default=None, description="Text search on code and description")
    unit: str | None = None
    source: str | None = None
    min_rate: float | None = Field(default=None, ge=0)
    max_rate: float | None = Field(default=None, ge=0)
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)
