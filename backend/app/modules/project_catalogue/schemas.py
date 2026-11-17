# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Project catalogue request and response schemas.

Money travels as a decimal string both ways so no rate loses digits through a
JSON float.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.core.decimal_types import FiniteDecimal

ItemType = Literal["work", "labor", "material", "equipment", "other"]
SourceType = Literal["cost_item", "catalog_resource"]
SyncAction = Literal["take_source", "keep_local"]


def money_str(value: Decimal | None) -> str | None:
    """A rate as a string with at least two places and no padding beyond what it carries."""
    if value is None:
        return None
    norm = value.normalize()
    if norm.as_tuple().exponent >= -2:  # type: ignore[operator]
        return str(value.quantize(Decimal("0.01")))
    return format(norm, "f")


class ItemCreate(BaseModel):
    """A rate typed by the estimator for this project only."""

    code: str = Field(..., min_length=1, max_length=100)
    description: str = Field(..., min_length=1, max_length=5000)
    unit: str = Field(default="", max_length=20)
    item_type: ItemType = "work"
    rate: FiniteDecimal = Decimal("0")
    currency: str = Field(default="", max_length=10)
    note: str = Field(default="", max_length=2000)


class ItemUpdate(BaseModel):
    """A partial edit of a project rate. The source it came from is never written."""

    code: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, min_length=1, max_length=5000)
    unit: str | None = Field(default=None, max_length=20)
    item_type: ItemType | None = None
    rate: FiniteDecimal | None = None
    currency: str | None = Field(default=None, max_length=10)
    note: str | None = Field(default=None, max_length=2000)


class ImportRequest(BaseModel):
    """Copy rows of the cost database or the resource catalogue into the project."""

    source_type: SourceType
    source_ids: list[UUID] = Field(..., min_length=1, max_length=500)


class SyncRequest(BaseModel):
    """Decide on moved source prices; no ids means every item whose source moved."""

    action: SyncAction
    item_ids: list[UUID] | None = Field(default=None, max_length=2000)


class ApplyRequest(BaseModel):
    """Price these bill lines from one project rate."""

    position_ids: list[UUID] = Field(..., min_length=1, max_length=500)


class ItemResponse(BaseModel):
    """A project rate with its provenance and where it stands against its source."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    code: str
    description: str
    unit: str
    item_type: str
    rate: Decimal
    currency: str
    note: str
    source_type: str
    source_id: str | None = None
    source_label: str = ""
    source_code: str = ""
    source_rate: Decimal | None = None
    source_currency: str = ""
    source_synced_at: datetime | None = None
    current_source_rate: Decimal | None = None
    status: str = "manual"
    deviation_percent: Decimal | None = None
    linked_positions: int = 0
    stale_positions: int = 0
    created_at: datetime
    updated_at: datetime
    warnings: list[dict] = Field(default_factory=list)

    @field_serializer("rate", "source_rate", "current_source_rate", when_used="json")
    def _ser_money(self, v: Decimal | None) -> str | None:
        return money_str(v)

    @field_serializer("deviation_percent", when_used="json")
    def _ser_pct(self, v: Decimal | None) -> str | None:
        return None if v is None else format(v, "f")


class CatalogueSummary(BaseModel):
    """Counts the page shows above the list."""

    total: int = 0
    in_sync: int = 0
    overridden: int = 0
    source_changed: int = 0
    source_missing: int = 0
    manual: int = 0
    linked_positions: int = 0
    stale_positions: int = 0


class ItemListResponse(BaseModel):
    """One page of a project catalogue."""

    items: list[ItemResponse]
    total: int
    offset: int
    limit: int
    summary: CatalogueSummary


class SourceHit(BaseModel):
    """A row of the cost database or resource catalogue that can be copied in."""

    source_type: str
    source_id: str
    code: str
    description: str
    unit: str
    rate: Decimal
    currency: str
    label: str
    already_added: bool = False

    @field_serializer("rate", when_used="json")
    def _ser_rate(self, v: Decimal) -> str | None:
        return money_str(v)


class SourceSearchResponse(BaseModel):
    """One page of source search results."""

    items: list[SourceHit]
    total: int
    offset: int
    limit: int


class PositionCandidate(BaseModel):
    """A bill line of the project that a rate can price."""

    id: str
    boq_id: str
    boq_name: str
    ordinal: str
    description: str
    unit: str
    quantity: str
    unit_rate: str
    linked_item_id: str | None = None


class CandidateListResponse(BaseModel):
    """One page of bill lines."""

    items: list[PositionCandidate]
    total: int
    offset: int
    limit: int


class ImportResult(BaseModel):
    """What a copy from a source did."""

    added: int
    skipped: int
    items: list[ItemResponse]


class SyncResult(BaseModel):
    """What a decision on moved source prices did."""

    updated: int
    skipped: int


class ApplyResult(BaseModel):
    """What pricing bill lines from a project rate did."""

    applied: int
    skipped: int
    position_ids: list[str] = Field(default_factory=list)


class Finding(BaseModel):
    """One failed rule."""

    rule_id: str
    severity: str
    message: str
    suggestion: str | None = None
    element_ref: str | None = None


class ValidationReportOut(BaseModel):
    """The ``project_catalogue`` rule set over one project's catalogue."""

    status: str
    error_count: int = 0
    warning_count: int = 0
    info_count: int = 0
    findings: list[Finding] = Field(default_factory=list)
