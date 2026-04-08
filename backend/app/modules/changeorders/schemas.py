"""Change Order Pydantic schemas — request/response models.

Defines create, update, and response schemas for change orders and their items.
Numeric values (cost_impact, cost_delta, quantities, rates) are exposed as floats
in the API but stored as strings in SQLite-compatible models.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ── Change Order schemas ─────────────────────────────────────────────────────


class ChangeOrderCreate(BaseModel):
    """Create a new change order."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    title: str = Field(..., min_length=1, max_length=255)
    description: str = ""
    reason_category: str = Field(
        default="client_request",
        pattern=r"^(client_request|design_change|unforeseen|regulatory|error)$",
    )
    schedule_impact_days: int = Field(default=0, ge=0)
    currency: str = Field(default="EUR", max_length=10)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChangeOrderUpdate(BaseModel):
    """Partial update for a change order."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    reason_category: str | None = Field(
        default=None,
        pattern=r"^(client_request|design_change|unforeseen|regulatory|error)$",
    )
    schedule_impact_days: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=10)
    metadata: dict[str, Any] | None = None


class ChangeOrderItemResponse(BaseModel):
    """Change order item returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    change_order_id: UUID
    description: str
    change_type: str
    original_quantity: float = 0.0
    new_quantity: float = 0.0
    original_rate: float = 0.0
    new_rate: float = 0.0
    cost_delta: float = 0.0
    unit: str
    sort_order: int
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class ChangeOrderResponse(BaseModel):
    """Change order returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    code: str
    title: str
    description: str
    reason_category: str
    status: str
    submitted_by: str | None = None
    approved_by: str | None = None
    submitted_at: str | None = None
    approved_at: str | None = None
    cost_impact: float = 0.0
    schedule_impact_days: int = 0
    currency: str
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime
    item_count: int = 0


class ChangeOrderWithItems(ChangeOrderResponse):
    """Change order response including all line items."""

    items: list[ChangeOrderItemResponse] = []


# ── Item schemas ─────────────────────────────────────────────────────────────


class ChangeOrderItemCreate(BaseModel):
    """Create a new change order item."""

    model_config = ConfigDict(str_strip_whitespace=True)

    description: str = Field(..., min_length=1)
    change_type: str = Field(
        default="modified",
        pattern=r"^(added|removed|modified)$",
    )
    original_quantity: float = Field(default=0.0, ge=0.0)
    new_quantity: float = Field(default=0.0, ge=0.0)
    original_rate: float = Field(default=0.0, ge=0.0)
    new_rate: float = Field(default=0.0, ge=0.0)
    unit: str = Field(default="", max_length=20)
    sort_order: int = Field(default=0, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChangeOrderItemUpdate(BaseModel):
    """Partial update for a change order item."""

    model_config = ConfigDict(str_strip_whitespace=True)

    description: str | None = Field(default=None, min_length=1)
    change_type: str | None = Field(
        default=None,
        pattern=r"^(added|removed|modified)$",
    )
    original_quantity: float | None = Field(default=None, ge=0.0)
    new_quantity: float | None = Field(default=None, ge=0.0)
    original_rate: float | None = Field(default=None, ge=0.0)
    new_rate: float | None = Field(default=None, ge=0.0)
    unit: str | None = Field(default=None, max_length=20)
    sort_order: int | None = Field(default=None, ge=0)
    metadata: dict[str, Any] | None = None


# ── Summary schema ───────────────────────────────────────────────────────────


class ChangeOrderSummary(BaseModel):
    """Aggregated change order stats for a project."""

    total: int = 0
    total_orders: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
    by_type: dict[str, int] = Field(default_factory=dict)
    draft_count: int = 0
    submitted_count: int = 0
    approved_count: int = 0
    rejected_count: int = 0
    total_approved_amount: float = 0.0
    total_cost_impact: float = 0.0
    total_time_impact_days: int = 0
    total_schedule_impact_days: int = 0
    currency: str = "EUR"
