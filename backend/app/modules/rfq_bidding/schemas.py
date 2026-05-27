"""‌⁠‍RFQ Bidding Pydantic schemas — request/response models."""

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Reject NUL / control-character payloads that crash downstream text
# processing / XML export (Part 5 BUG-148/149).
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Permissive ISO-4217-shape gate: 3 letters, upper-case. We don't ship a
# full 180-code allow-list here (would belong in app/core/money.py); the
# goal is to stop free-form garbage like "BOGUS_CURRENCY" or "$" landing
# in the price column. Same shape rule the BOQ and procurement modules
# enforce in practice today (compared with .upper() everywhere).
_CURRENCY_CODE_RE = re.compile(r"^[A-Z]{3}$")


def _reject_unsafe_string(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    if _CONTROL_CHAR_RE.search(value):
        raise ValueError(f"{field} contains control characters")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field} must not be blank")
    return cleaned


def _validate_currency_code(value: str | None) -> str | None:
    """Normalise + shape-validate an ISO-4217 currency code."""
    if value is None:
        return None
    cleaned = value.strip().upper()
    if not cleaned:
        raise ValueError("currency_code must not be blank")
    if not _CURRENCY_CODE_RE.match(cleaned):
        raise ValueError(f"currency_code must be a 3-letter ISO-4217 code, got {value!r}")
    return cleaned


def _validate_money_amount(value: str | None, field: str) -> str | None:
    """Validate ``value`` is a non-negative finite decimal string.

    The bid_amount column is ``String`` (not numeric) for legacy reasons,
    but we must NEVER store unparseable junk like ``"abc"`` or
    scientific notation in a money field — that would crash totals,
    PDF exports and downstream FX rollups (see #111). We store the
    normalised canonical form (no thousands separators, no sci-notation).
    """
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned:
        raise ValueError(f"{field} must not be blank")
    try:
        d = Decimal(cleaned)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be a valid decimal number, got {value!r}") from exc
    if not d.is_finite():
        raise ValueError(f"{field} must be finite, got {value!r}")
    if d < 0:
        raise ValueError(f"{field} must be >= 0, got {value!r}")
    # Cap fractional precision at 6 places — enough for FX-converted amounts
    # but rejects pathological inputs like "1.0000000000000000000001".
    sign, _digits, exponent = d.as_tuple()
    if isinstance(exponent, int) and exponent < -6:
        raise ValueError(f"{field} has too many decimal places (max 6), got {value!r}")
    return format(d, "f")


# ── RFQ ─────────────────────────────────────────────────────────────────────


class RFQCreate(BaseModel):
    """‌⁠‍Create a new RFQ."""

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

    @field_validator("currency_code")
    @classmethod
    def _normalise_currency(cls, v: str | None) -> str | None:
        return _validate_currency_code(v)


class RFQUpdate(BaseModel):
    """‌⁠‍Partial update for an RFQ."""

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

    @field_validator("currency_code")
    @classmethod
    def _normalise_currency(cls, v: str | None) -> str | None:
        return _validate_currency_code(v)


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

    @field_validator("notes")
    @classmethod
    def _sanitize_strings(cls, v: str | None) -> str | None:
        # Allow blank notes (None); only reject control chars if present.
        if v is None:
            return None
        if _CONTROL_CHAR_RE.search(v):
            raise ValueError("notes contains control characters")
        return v

    @field_validator("bid_amount")
    @classmethod
    def _validate_bid_amount(cls, v: str) -> str:
        result = _validate_money_amount(v, "bid_amount")
        # bid_amount is required, never None — assert for type-checker.
        assert result is not None
        return result

    @field_validator("currency_code")
    @classmethod
    def _normalise_currency(cls, v: str) -> str:
        result = _validate_currency_code(v)
        assert result is not None
        return result

    @field_validator("technical_score", "commercial_score")
    @classmethod
    def _validate_scores(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        try:
            score = Decimal(v.strip())
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"score must be numeric, got {v!r}") from exc
        if score < 0 or score > 100:
            raise ValueError(f"score must be between 0 and 100, got {v!r}")
        return format(score, "f")


class BidEvaluation(BaseModel):
    """Score a bid (technical + commercial)."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    technical_score: str | None = Field(default=None, max_length=10)
    commercial_score: str | None = Field(default=None, max_length=10)
    notes: str | None = Field(default=None, max_length=10_000)

    @field_validator("technical_score", "commercial_score")
    @classmethod
    def _validate_scores(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        try:
            score = Decimal(v.strip())
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"score must be numeric, got {v!r}") from exc
        if score < 0 or score > 100:
            raise ValueError(f"score must be between 0 and 100, got {v!r}")
        return format(score, "f")


class BidListResponse(BaseModel):
    """Paginated list of bids."""

    items: list[RFQBidResponse]
    total: int
