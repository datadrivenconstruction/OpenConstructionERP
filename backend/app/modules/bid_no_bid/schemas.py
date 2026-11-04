# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Bid / no-bid request and response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.bid_no_bid.logic import CRITERIA, MAX_RATING, MIN_RATING


class ScorecardUpdate(BaseModel):
    """Partial update; only the sent keys change. ``version`` guards against a stale edit."""

    weights: dict[str, int] | None = None
    scores: dict[str, int | None] | None = None
    notes: dict[str, str] | None = None
    threshold: int | None = Field(default=None, ge=1, le=100)
    opportunity_id: uuid.UUID | None = None
    clear_opportunity: bool = False
    version: int | None = None

    @field_validator("weights")
    @classmethod
    def _weights(cls, v: dict[str, int] | None) -> dict[str, int] | None:
        if v is None:
            return v
        if set(v) - set(CRITERIA) or any(not 0 <= n <= 100 for n in v.values()):
            raise ValueError("weights are 0-100 for client, capacity, risk, margin, competition")
        return v

    @field_validator("scores")
    @classmethod
    def _scores(cls, v: dict[str, int | None] | None) -> dict[str, int | None] | None:
        if v is None:
            return v
        if set(v) - set(CRITERIA) or any(n is not None and not MIN_RATING <= n <= MAX_RATING for n in v.values()):
            raise ValueError("ratings are 1-5 for client, capacity, risk, margin, competition")
        return v

    @field_validator("notes")
    @classmethod
    def _notes(cls, v: dict[str, str] | None) -> dict[str, str] | None:
        if v is None:
            return v
        if set(v) - set(CRITERIA) or any(len(n) > 500 for n in v.values()):
            raise ValueError("notes are up to 500 characters per criterion")
        return v


class DecideRequest(BaseModel):
    decision: Literal["bid", "no_bid"]
    reason: str = Field(default="", max_length=2000)
    version: int | None = None


class OutcomeRequest(BaseModel):
    outcome: Literal["", "won", "lost", "withdrawn"]
    note: str = Field(default="", max_length=2000)
    version: int | None = None


class FindingOut(BaseModel):
    rule_id: str
    severity: str
    message: str
    element_ref: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_name: str
    kind: str
    message: str
    params: dict[str, Any]
    created_at: datetime


class ScorecardOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    tender_id: uuid.UUID
    tender_name: str
    opportunity_id: uuid.UUID | None
    weights: dict[str, int]
    scores: dict[str, int | None]
    notes: dict[str, str]
    threshold: int
    score: str | None
    recommendation: str
    decision: str
    decision_reason: str
    decided_by_name: str
    decided_at: datetime | None
    outcome: str
    outcome_note: str
    version: int
    findings: list[FindingOut]
    events: list[EventOut]


class LedgerRow(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    tender_id: uuid.UUID
    tender_name: str
    score: str | None
    threshold: int
    recommendation: str
    decision: str
    decision_reason: str
    decided_at: datetime | None
    outcome: str
    outcome_source: str


class LedgerOut(BaseModel):
    summary: dict[str, Any]
    rows: list[LedgerRow]
