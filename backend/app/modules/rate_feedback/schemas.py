# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Request and response shapes for rate feedback. Numbers cross the wire as decimal strings."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.core.decimal_types import FiniteDecimal


class ProposalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    cost_item_id: uuid.UUID
    cost_item_code: str | None = None
    cost_item_description: str | None = None
    unit: str
    current_rate: Decimal
    suggested_rate: Decimal
    variance_pct: Decimal | None
    current_hours_per_unit: Decimal | None
    observed_hours_per_unit: Decimal | None
    hours_variance_pct: Decimal | None
    project_count: int
    line_count: int
    total_quantity: Decimal
    spread_pct: Decimal | None
    confidence: Decimal
    status: str
    decided_at: datetime | None
    applied_rate: Decimal | None
    decision_note: str | None
    warnings: list[str] = Field(default_factory=list)

    @field_serializer(
        "current_rate",
        "suggested_rate",
        "variance_pct",
        "current_hours_per_unit",
        "observed_hours_per_unit",
        "hours_variance_pct",
        "total_quantity",
        "spread_pct",
        "confidence",
        "applied_rate",
    )
    def _as_string(self, value: Decimal | None) -> str | None:
        return None if value is None else format(value, "f")


class ProposalListResponse(BaseModel):
    items: list[ProposalResponse]
    total: int
    offset: int = 0
    limit: int = 50


class RefreshRequest(BaseModel):
    tolerance: FiniteDecimal = Field(default=Decimal("0.05"), ge=0, le=1)
    min_projects: int = Field(default=1, ge=1, le=50)


class RefreshResponse(BaseModel):
    closed_projects: int
    observed_cost_items: int
    created: int
    unchanged: int


class ConfirmRequest(BaseModel):
    """``rate`` lets the estimator keep a figure of their own instead of the suggestion."""

    rate: FiniteDecimal | None = Field(default=None, gt=0, lt=Decimal("100000000000"), decimal_places=4)
    apply_hours: bool = True
    note: str | None = Field(default=None, max_length=1000)


class RejectRequest(BaseModel):
    note: str | None = Field(default=None, max_length=1000)
