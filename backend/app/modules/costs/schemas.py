"""Cost item Pydantic schemas for request/response validation."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ── Create / Update ───────────────────────────────────────────────────────


class CostItemCreate(BaseModel):
    """Create a new cost item."""

    code: str = Field(
        ..., min_length=1, max_length=100, description="Unique cost item code / rate code"
    )
    description: str = Field(default="", description="Cost item description text")
    descriptions: dict[str, str] = Field(
        default_factory=dict,
        description="Localized descriptions keyed by locale (e.g. {\"en\": \"...\", \"de\": \"...\"})",
    )
    unit: str = Field(
        ...,
        min_length=1,
        max_length=20,
        description="Unit of measurement (m, m2, m3, kg, pcs, hr, etc.)",
    )
    rate: float = Field(..., ge=0, description="Unit rate (must be >= 0)")
    currency: str = Field(
        default="EUR", max_length=10, description="ISO 4217 currency code"
    )
    source: str = Field(
        default="cwicr", max_length=50, description="Data source (e.g. cwicr, rsmeans, manual)"
    )
    classification: dict[str, str] = Field(
        default_factory=dict,
        description="Classification codes (e.g. {\"din276\": \"330\", \"masterformat\": \"03 30 00\"})",
    )
    components: list[dict[str, Any]] = Field(
        default_factory=list, description="Assembly components (labor, material, equipment breakdown)"
    )
    tags: list[str] = Field(default_factory=list, description="Searchable tags")
    region: str | None = Field(
        default=None, max_length=50, description="Regional identifier (e.g. DACH, UK, US)"
    )
    metadata: dict[str, Any] = Field(default_factory=dict, description="Arbitrary metadata")


class CostItemUpdate(BaseModel):
    """Update a cost item (all fields optional)."""

    code: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None)
    descriptions: dict[str, str] | None = None
    unit: str | None = Field(default=None, min_length=1, max_length=20)
    rate: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=10)
    source: str | None = Field(default=None, max_length=50)
    classification: dict[str, str] | None = None
    components: list[dict[str, Any]] | None = None
    region: str | None = Field(default=None, max_length=50)
    tags: list[str] | None = None
    metadata: dict[str, Any] | None = None
    is_active: bool | None = None


# ── Response ───────────────────────────────────────────────────────────


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


class CostAutocompleteItem(BaseModel):
    """Compact cost item result for autocomplete dropdown."""

    code: str
    description: str
    unit: str
    rate: float
    classification: dict[str, str]
    components: list[dict[str, Any]] = Field(default_factory=list)


class CostSearchQuery(BaseModel):
    """Query parameters for cost item search."""

    q: str | None = Field(default=None, description="Text search on code and description")
    unit: str | None = None
    source: str | None = None
    region: str | None = Field(default=None, description="Filter by region (e.g. DE_BERLIN)")
    category: str | None = Field(default=None, description="Filter by classification.collection value")
    min_rate: float | None = Field(default=None, ge=0)
    max_rate: float | None = Field(default=None, ge=0)
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


class CostSearchResponse(BaseModel):
    """Paginated search response for cost items."""

    items: list[CostItemResponse]
    total: int
    limit: int
    offset: int


# ── BIM suggestion ────────────────────────────────────────────────────────


class CostSuggestion(BaseModel):
    """A ranked cost-item suggestion for a BIM element.

    Returned by ``POST /api/v1/costs/suggest-for-element``.  The frontend
    renders these as chips in the AddToBOQ modal so the estimator can
    one-click populate a BOQ position's unit rate.
    """

    cost_item_id: str = Field(..., description="UUID of the underlying CostItem")
    code: str = Field(..., description="CWICR rate code / cost item code")
    description: str = Field(..., description="Human-readable description")
    unit: str = Field(..., description="Unit of measurement")
    unit_rate: float | str = Field(..., description="Unit rate (numeric if parseable)")
    classification: dict[str, str] = Field(
        default_factory=dict,
        description="Classification codes forwarded from the CostItem",
    )
    score: float = Field(
        ..., ge=0.0, le=1.0, description="Relevance score 0..1 (higher = better)"
    )
    match_reasons: list[str] = Field(
        default_factory=list,
        description="Short human-readable strings explaining why this matched",
    )


class SuggestCostsForElementRequest(BaseModel):
    """Request body for BIM-element cost suggestion endpoint."""

    element_type: str | None = None
    name: str | None = None
    discipline: str | None = None
    properties: dict[str, Any] | None = None
    quantities: dict[str, float] | None = None
    classification: dict[str, str] | None = None
    limit: int = Field(default=5, ge=1, le=50)
    region: str | None = None
