# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Bid outcome ledger request and response schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.decimal_types import Decimal18_2, FiniteDecimal

Outcome = Literal["pending", "won", "lost", "withdrawn", "no_decision"]
LostReason = Literal["price", "scope", "schedule", "relationship", "capacity", "other"]


def _upper(value: str | None) -> str | None:
    return value.strip().upper() if value is not None else None


class BidOutcomeCreate(BaseModel):
    """Record a submitted bid."""

    title: str = Field(min_length=1, max_length=255)
    client_name: str = Field(default="", max_length=255)
    trade: str = Field(default="", max_length=100)
    project_id: uuid.UUID | None = None
    tender_id: uuid.UUID | None = None
    submitted_on: date | None = None
    outcome: Outcome = "pending"
    currency: str = Field(default="", max_length=10)
    our_price: Decimal18_2 = Field(ge=0)
    winning_price: Decimal18_2 | None = Field(default=None, gt=0)
    second_price: Decimal18_2 | None = Field(default=None, gt=0)
    competitor_count: int | None = Field(default=None, ge=0, le=500)
    lost_reason: LostReason | None = None
    notes: str = ""

    _currency_upper = field_validator("currency")(_upper)


class BidOutcomeUpdate(BaseModel):
    """Patch a ledger entry; only the sent fields change."""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    client_name: str | None = Field(default=None, max_length=255)
    trade: str | None = Field(default=None, max_length=100)
    project_id: uuid.UUID | None = None
    tender_id: uuid.UUID | None = None
    submitted_on: date | None = None
    outcome: Outcome | None = None
    currency: str | None = Field(default=None, max_length=10)
    our_price: Decimal18_2 | None = Field(default=None, ge=0)
    winning_price: Decimal18_2 | None = Field(default=None, gt=0)
    second_price: Decimal18_2 | None = Field(default=None, gt=0)
    competitor_count: int | None = Field(default=None, ge=0, le=500)
    lost_reason: LostReason | None = None
    notes: str | None = None
    version: int | None = None

    _currency_upper = field_validator("currency")(_upper)


class ValidationFinding(BaseModel):
    """One validation warning on an entry."""

    rule_id: str
    severity: str
    message: str
    suggestion: str | None = None


class BidOutcomeResponse(BaseModel):
    """A ledger entry with its derived price gap."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    client_name: str
    trade: str
    project_id: uuid.UUID | None
    tender_id: uuid.UUID | None
    submitted_on: date | None
    outcome: str
    currency: str
    our_price: Decimal
    winning_price: Decimal | None
    second_price: Decimal | None
    competitor_count: int | None
    lost_reason: str | None
    notes: str
    version: int = 1
    size_band: str = ""
    left_on_table: Decimal | None = None
    left_on_table_pct: Decimal | None = None
    gap_to_winner: Decimal | None = None
    gap_to_winner_pct: Decimal | None = None
    created_at: datetime
    updated_at: datetime
    warnings: list[ValidationFinding] = Field(default_factory=list)


class BidOutcomeListResponse(BaseModel):
    items: list[BidOutcomeResponse]
    total: int
    offset: int = 0
    limit: int = 500


class GroupStat(BaseModel):
    """Hit rate of one client, trade or size band."""

    key: str
    submitted: int
    won: int
    lost: int
    hit_rate_pct: FiniteDecimal | None
    won_value: FiniteDecimal


class LedgerSummary(BaseModel):
    """Headline numbers and hit rate by client, trade and size, in one currency."""

    currency: str
    currencies: list[str]
    submitted: int
    won: int
    lost: int
    open: int
    hit_rate_pct: Decimal | None
    won_value: Decimal
    left_on_table: Decimal
    left_on_table_wins: int
    avg_gap_to_winner_pct: Decimal | None
    avg_competitors: Decimal | None
    by_client: list[GroupStat]
    by_trade: list[GroupStat]
    by_size: list[GroupStat]
