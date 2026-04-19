"""RFQ Bidding Pydantic schemas — request/response models."""

import re
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Reject NUL / control-character payloads that crash downstream text
# processing / XML export (Part 5 BUG-148/149).
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _reject_unsafe_string(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    if _CONTROL_CHAR_RE.search(value):
        raise ValueError(f"{field} contains control characters")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field} must not be blank")
    return cleaned

# ── RFQ ─────────────────────────────────────────────────────────────────────


class RFQCreate(BaseModel):
    """Create a new RFQ."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    project_id: UUID
    rfq_number: str | None = Field(default=None, min_length=1, max_length=50)
    title: str = Field(..., min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=10_000)
    scope_of_work: str | None = Field(default=None, max_length=50_000)
    submission_deadline: str | None = Field(default=None, max_length=20)
    currency_code: str = Field(default="EUR", max_length=10)
    status: str = Field(default="draft", max_length=50)
    issued_to_contacts: list[str] = Field(default_factory=list, max_length=500)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("rfq_number", "title", "description", "scope_of_work")
    @classmethod
    def _sanitize_strings(cls, v: str | None) -> str | None:
        return _reject_unsafe_string(v, "value")


class RFQUpdate(BaseModel):
    """Partial update for an RFQ."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=10_000)
    scope_of_work: str | None = Field(default=None, max_length=50_000)
    submission_deadline: str | None = Field(default=None, max_length=20)
    currency_code: str | None = Field(default=None, max_length=10)
    status: str | None = Field(default=None, max_length=50)
    issued_to_contacts: list[str] | None = Field(default=None, max_length=500)
    metadata: dict[str, Any] | None = None

    @field_validator("title", "description", "scope_of_work")
    @classmethod
    def _sanitize_strings(cls, v: str | None) -> str | None:
        return _reject_unsafe_string(v, "value")


class RFQBidResponse(BaseModel):
    """RFQ bid returned from the API (nested in RFQ response)."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    rfq_id: UUID
    bidder_contact_id: str
    bid_amount: str
    currency_code: str = "EUR"
    submitted_at: str | None = None
    validity_days: int = 30
    technical_score: str | None = None
    commercial_score: str | None = None
    notes: str | None = None
    is_awarded: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class RFQResponse(BaseModel):
    """RFQ returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    rfq_number: str
    title: str
    description: str | None = None
    scope_of_work: str | None = None
    submission_deadline: str | None = None
    currency_code: str = "EUR"
    status: str = "draft"
    issued_to_contacts: list[str] = Field(default_factory=list)
    created_by: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    bids: list[RFQBidResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class RFQListResponse(BaseModel):
    """Paginated list of RFQs."""

    items: list[RFQResponse]
    total: int
    offset: int
    limit: int


# ── Bid ─────────────────────────────────────────────────────────────────────


class BidCreate(BaseModel):
    """Submit a bid against an RFQ."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    rfq_id: UUID
    bidder_contact_id: str = Field(..., max_length=36)
    bid_amount: str = Field(..., max_length=50)
    currency_code: str = Field(default="EUR", max_length=10)
    submitted_at: str | None = Field(default=None, max_length=20)
    validity_days: int = Field(default=30, ge=0, le=3_650)
    technical_score: str | None = Field(default=None, max_length=10)
    commercial_score: str | None = Field(default=None, max_length=10)
    notes: str | None = Field(default=None, max_length=10_000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BidEvaluation(BaseModel):
    """Score a bid (technical + commercial)."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    technical_score: str | None = Field(default=None, max_length=10)
    commercial_score: str | None = Field(default=None, max_length=10)
    notes: str | None = Field(default=None, max_length=10_000)


class BidListResponse(BaseModel):
    """Paginated list of bids."""

    items: list[RFQBidResponse]
    total: int
