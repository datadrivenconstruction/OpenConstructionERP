"""Tendering Pydantic schemas — request/response models.

Defines create, update, and response schemas for tender packages and bids.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ── Package schemas ──────────────────────────────────────────────────────────


class PackageCreate(BaseModel):
    """Create a new tender package."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    boq_id: UUID | None = None
    name: str = Field(..., min_length=1, max_length=255)
    description: str = ""
    deadline: str | None = Field(default=None, max_length=20)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PackageUpdate(BaseModel):
    """Partial update for a tender package."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    status: str | None = Field(
        default=None,
        pattern=r"^(draft|issued|collecting|evaluating|awarded|closed)$",
    )
    deadline: str | None = None
    metadata: dict[str, Any] | None = None


class PackageResponse(BaseModel):
    """Tender package returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    boq_id: UUID | None = None
    name: str
    description: str
    status: str
    deadline: str | None
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")
    created_at: datetime
    updated_at: datetime
    bid_count: int = 0


class PackageWithBidsResponse(PackageResponse):
    """Package response including all bids."""

    bids: list["BidResponse"] = []


# ── Bid schemas ──────────────────────────────────────────────────────────────


class BidLineItem(BaseModel):
    """A single line item within a bid."""

    position_id: str | None = None
    description: str = ""
    unit: str = ""
    quantity: float = 0.0
    unit_rate: float = 0.0
    total: float = 0.0


class BidCreate(BaseModel):
    """Create a new bid for a tender package."""

    model_config = ConfigDict(str_strip_whitespace=True)

    company_name: str = Field(..., min_length=1, max_length=255)
    contact_email: str = Field(default="", max_length=255)
    total_amount: str = Field(default="0", max_length=50)
    currency: str = Field(default="EUR", max_length=10)
    submitted_at: str | None = Field(default=None, max_length=20)
    status: str = Field(default="pending", pattern=r"^(pending|submitted|accepted|rejected)$")
    notes: str = ""
    line_items: list[BidLineItem] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BidUpdate(BaseModel):
    """Partial update for a bid."""

    model_config = ConfigDict(str_strip_whitespace=True)

    company_name: str | None = Field(default=None, min_length=1, max_length=255)
    contact_email: str | None = None
    total_amount: str | None = None
    currency: str | None = None
    submitted_at: str | None = None
    status: str | None = Field(
        default=None, pattern=r"^(pending|submitted|accepted|rejected)$"
    )
    notes: str | None = None
    line_items: list[BidLineItem] | None = None
    metadata: dict[str, Any] | None = None


class BidResponse(BaseModel):
    """Bid returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    package_id: UUID
    company_name: str
    contact_email: str
    total_amount: str
    currency: str
    submitted_at: str | None
    status: str
    notes: str
    line_items: list[dict[str, Any]]
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Comparison schema ────────────────────────────────────────────────────────


class BidComparisonRow(BaseModel):
    """A single row in the bid comparison matrix."""

    position_id: str | None = None
    description: str = ""
    unit: str = ""
    budget_quantity: float = 0.0
    budget_rate: float = 0.0
    budget_total: float = 0.0
    bids: list[dict[str, Any]] = Field(default_factory=list)


class BidComparisonResponse(BaseModel):
    """Full bid comparison for a package."""

    package_id: UUID
    package_name: str
    bid_count: int = 0
    bid_companies: list[str] = Field(default_factory=list)
    budget_total: float = 0.0
    rows: list[BidComparisonRow] = Field(default_factory=list)
    bid_totals: list[dict[str, Any]] = Field(default_factory=list)
