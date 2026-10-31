# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Bid day request and response schemas. Money travels as decimal strings."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

RowKind = Literal["subcontract", "material", "other"]
Channel = Literal["portal", "phone", "email", "other"]
ExclusionStatus = Literal["open", "plugged", "included"]


def _money(v: Any) -> str:
    try:
        d = Decimal(str(v).strip())
    except Exception as exc:
        raise ValueError("not a number") from exc
    if not d.is_finite():
        raise ValueError("not a number")
    return f"{d:f}"


class _Rev(BaseModel):
    """``rev`` is the revision the client edited; a stale one answers 409."""

    rev: int | None = None


class ExclusionIn(BaseModel):
    id: str | None = Field(default=None, max_length=40)
    text: str = Field(default="", max_length=500)
    status: ExclusionStatus = "open"
    plug_amount: str = "0"

    @field_validator("plug_amount", mode="before")
    @classmethod
    def _check_plug_amount(cls, v: Any) -> str:
        return _money(v)


class QuoteCreate(BaseModel):
    vendor: str = Field(min_length=1, max_length=255)
    amount: str
    currency: str | None = Field(default=None, max_length=10)
    channel: Channel = "phone"
    received_at: datetime | None = None
    note: str = Field(default="", max_length=4000)
    exclusions: list[ExclusionIn] = Field(default_factory=list)

    @field_validator("amount", mode="before")
    @classmethod
    def _check_amount(cls, v: Any) -> str:
        return _money(v)


class QuoteUpdate(_Rev):
    vendor: str | None = Field(default=None, max_length=255)
    amount: str | None = None
    currency: str | None = Field(default=None, max_length=10)
    received_at: datetime | None = None
    note: str | None = Field(default=None, max_length=4000)
    exclusions: list[ExclusionIn] | None = None

    @field_validator("amount", mode="before")
    @classmethod
    def _amount(cls, v: Any) -> str | None:
        return None if v is None else _money(v)


class RowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=500)
    kind: RowKind = "subcontract"
    plug_amount: str = "0"

    @field_validator("plug_amount", mode="before")
    @classmethod
    def _check_plug_amount(cls, v: Any) -> str:
        return _money(v)


class RowUpdate(_Rev):
    name: str | None = Field(default=None, max_length=500)
    kind: RowKind | None = None
    plug_amount: str | None = None

    @field_validator("plug_amount", mode="before")
    @classmethod
    def _plug(cls, v: Any) -> str | None:
        return None if v is None else _money(v)


class ChoiceUpdate(_Rev):
    quote_id: uuid.UUID | None = None


class MarkupUpdate(_Rev):
    overhead_pct: str | None = None
    risk_pct: str | None = None
    profit_pct: str | None = None
    stale_days: int | None = Field(default=None, ge=1, le=365)
    deviation_pct_limit: str | None = None

    @field_validator("overhead_pct", "risk_pct", "profit_pct", "deviation_pct_limit", mode="before")
    @classmethod
    def _pct(cls, v: Any) -> str | None:
        if v is None:
            return None
        out = _money(v)
        if not Decimal("-100") <= Decimal(out) <= Decimal("1000"):
            raise ValueError("percentage out of range")
        return out


class FreezeRequest(BaseModel):
    note: str = Field(default="", max_length=4000)


class PushRequest(BaseModel):
    dry_run: bool = True


class ExclusionOut(BaseModel):
    id: str
    text: str
    status: str
    plug_amount: str


class QuoteOut(BaseModel):
    id: uuid.UUID
    source: str
    channel: str
    vendor: str
    amount: str
    source_amount: str | None
    currency: str
    fx_rate: str
    received_at: datetime | None
    note: str
    exclusions: list[ExclusionOut]
    as_quoted: str
    adjusted: str
    open_exclusions: int
    is_chosen: bool
    rev: int


class SuggestionOut(BaseModel):
    quote_id: str
    vendor: str
    adjusted: str
    confidence: float
    reasons: list[str]
    gap_pct: float
    open_exclusions: int
    is_chosen: bool


class RowOut(BaseModel):
    id: uuid.UUID
    bid_package_id: uuid.UUID | None
    name: str
    kind: str
    plug_amount: str
    chosen_quote_id: uuid.UUID | None
    value: str
    delta_vs_plug: str
    suggestion: SuggestionOut | None
    quotes: list[QuoteOut]
    rev: int


class TotalsOut(BaseModel):
    direct: str
    overhead: str
    risk: str
    profit: str
    markup: str
    bid_total: str
    estimate_direct: str
    estimate_total: str
    vs_estimate: str
    last_snapshot_total: str | None
    delta_vs_snapshot: str | None


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    user_name: str
    kind: str
    message: str
    delta: str
    total_after: str
    params: dict[str, Any]


class FindingOut(BaseModel):
    rule_id: str
    severity: str
    message: str
    element_ref: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class SnapshotSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    submitted_by_name: str
    currency: str
    bid_total: str
    note: str
    content_sha256: str
    pushed_at: datetime | None


class SnapshotOut(SnapshotSummaryOut):
    payload: dict[str, Any]


class BoardOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    tender_id: uuid.UUID
    tender_name: str
    deadline: str | None
    currency: str
    status: str
    version: int
    markup_rev: int
    overhead_pct: str
    risk_pct: str
    profit_pct: str
    stale_days: int
    deviation_pct_limit: str
    totals: TotalsOut
    rows: list[RowOut]
    events: list[EventOut]
    findings: list[FindingOut]
    snapshots: list[SnapshotSummaryOut]


class VersionOut(BaseModel):
    version: int
    status: str


class PushLine(BaseModel):
    row: str
    position_id: str
    ordinal: str
    description: str
    quantity: str
    old_total: str
    new_total: str
    new_unit_rate: str


class PushOut(BaseModel):
    applied: bool
    lines: list[PushLine]
    skipped: list[str]
