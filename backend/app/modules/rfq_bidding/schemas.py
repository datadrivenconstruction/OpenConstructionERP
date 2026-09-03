# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""RFQ Bidding Pydantic schemas - request/response models.

Money on the wire is a Decimal-as-string, both ways: an amount arrives as a
string or a number and is validated into :class:`~decimal.Decimal`, and every
response serialises it back to a string so no client ever sees a float.
"""

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from app.modules.rfq_bidding.constants import (
    ADJUSTMENT_KINDS,
    ADJUSTMENT_SOURCES,
    EVALUATION_METHODS,
)

# Reject NUL / control-character payloads that crash downstream text
# processing / XML export (Part 5 BUG-148/149).
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Permissive ISO-4217-shape gate: 3 letters, upper-case. We don't ship a
# full 180-code allow-list here (would belong in app/core/money.py); the
# goal is to stop free-form garbage like "BOGUS_CURRENCY" or "$" landing
# in the price column. Same shape rule the BOQ and procurement modules
# enforce in practice today (compared with .upper() everywhere).
_CURRENCY_CODE_RE = re.compile(r"^[A-Z]{3}$")

# Upper bound for money fields - far above any realistic bid yet within
# Decimal's precision so a future aggregate / quantize over a stored bid_amount
# can never raise InvalidOperation. Mirrors changeorders/schemas.py:_MONEY_MAX.
_MONEY_MAX = Decimal("1e15")


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
    scientific notation in a money field - that would crash totals,
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
    if d >= _MONEY_MAX:
        raise ValueError(f"{field} is outside the supported range, got {value!r}")
    # Cap fractional precision at 6 places - enough for FX-converted amounts
    # but rejects pathological inputs like "1.0000000000000000000001".
    sign, _digits, exponent = d.as_tuple()
    if isinstance(exponent, int) and exponent < -6:
        raise ValueError(f"{field} has too many decimal places (max 6), got {value!r}")
    return format(d, "f")


def _validate_decimal(
    value: Any,
    field: str,
    *,
    allow_negative: bool = False,
    max_places: int = 4,
    maximum: Decimal = _MONEY_MAX,
) -> Decimal:
    """Validate and normalise a decimal quantity, rate or factor.

    Args:
        value: The incoming value: a string, an int or a Decimal.
        field: Field name, used in the error message.
        allow_negative: Whether a negative value is meaningful here. An
            adjustment may be a discount; a quantity may not.
        max_places: Fractional places the storage column can hold. More than
            that would be silently rounded on write.
        maximum: Absolute upper bound.

    Returns:
        The parsed :class:`~decimal.Decimal`.

    Raises:
        ValueError: When the value is not a finite decimal inside the bounds.
    """
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, AttributeError) as exc:
        raise ValueError(f"{field} must be a valid decimal number, got {value!r}") from exc
    if not parsed.is_finite():
        raise ValueError(f"{field} must be finite, got {value!r}")
    if not allow_negative and parsed < 0:
        raise ValueError(f"{field} must be >= 0, got {value!r}")
    if abs(parsed) >= maximum:
        raise ValueError(f"{field} is outside the supported range, got {value!r}")
    _sign, _digits, exponent = parsed.as_tuple()
    if isinstance(exponent, int) and exponent < -max_places:
        raise ValueError(f"{field} has too many decimal places (max {max_places}), got {value!r}")
    return parsed


def _serialise_decimal(value: Decimal | None) -> str | None:
    """Render a Decimal for JSON: a plain string, never an exponent."""
    return None if value is None else format(value, "f")


def _validate_evaluation_method(value: str) -> str:
    """Check the ranking method is one the comparison actually implements."""
    cleaned = str(value or "").strip().lower()
    if cleaned not in EVALUATION_METHODS:
        raise ValueError(f"evaluation_method must be one of {sorted(EVALUATION_METHODS)}, got {value!r}")
    return cleaned


def _validate_weight(value: Any) -> Decimal:
    """Check the technical weight is a percentage between 0 and 100."""
    weight = _validate_decimal(value, "technical_weight", max_places=2, maximum=Decimal("1000"))
    if weight > 100:
        raise ValueError(f"technical_weight must be between 0 and 100, got {value!r}")
    return weight


def _validate_reason(value: str | None, field: str) -> str:
    """A decision that has to be justified needs words, not a blank string."""
    cleaned = _reject_unsafe_string(value, field)
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
    evaluation_method: str = Field(default="lowest_price", max_length=30)
    technical_weight: Decimal = Field(default=Decimal("0"))
    require_full_scope: bool = True
    lines: list["RFQLineCreate"] = Field(default_factory=list, max_length=2_000)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("rfq_number", "title", "description", "scope_of_work")
    @classmethod
    def _sanitize_strings(cls, v: str | None) -> str | None:
        return _reject_unsafe_string(v, "value")

    @field_validator("currency_code")
    @classmethod
    def _normalise_currency(cls, v: str | None) -> str | None:
        return _validate_currency_code(v)

    @field_validator("evaluation_method")
    @classmethod
    def _check_method(cls, v: str) -> str:
        return _validate_evaluation_method(v)

    @field_validator("technical_weight", mode="before")
    @classmethod
    def _check_weight(cls, v: Any) -> Decimal:
        return _validate_weight(v)


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
    evaluation_method: str | None = Field(default=None, max_length=30)
    technical_weight: Decimal | None = None
    require_full_scope: bool | None = None
    metadata: dict[str, Any] | None = None

    @field_validator("title", "description", "scope_of_work")
    @classmethod
    def _sanitize_strings(cls, v: str | None) -> str | None:
        return _reject_unsafe_string(v, "value")

    @field_validator("currency_code")
    @classmethod
    def _normalise_currency(cls, v: str | None) -> str | None:
        return _validate_currency_code(v)

    @field_validator("evaluation_method")
    @classmethod
    def _check_method(cls, v: str | None) -> str | None:
        return None if v is None else _validate_evaluation_method(v)

    @field_validator("technical_weight", mode="before")
    @classmethod
    def _check_weight(cls, v: Any) -> Decimal | None:
        return None if v is None else _validate_weight(v)


class RFQLineCreate(BaseModel):
    """One line of the scope suppliers are asked to price."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    line_no: int | None = Field(default=None, ge=1, le=1_000_000)
    code: str | None = Field(default=None, max_length=50)
    description: str = Field(..., min_length=1, max_length=5_000)
    unit: str = Field(..., min_length=1, max_length=20)
    quantity: Decimal = Field(default=Decimal("0"))
    is_optional: bool = False
    cost_line_id: UUID | None = None
    notes: str | None = Field(default=None, max_length=5_000)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("code", "description", "unit", "notes")
    @classmethod
    def _sanitize_strings(cls, v: str | None) -> str | None:
        return _reject_unsafe_string(v, "value")

    @field_validator("quantity", mode="before")
    @classmethod
    def _check_quantity(cls, v: Any) -> Decimal:
        return _validate_decimal(v, "quantity")


class RFQLineUpdate(BaseModel):
    """Partial update for one scope line."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    line_no: int | None = Field(default=None, ge=1, le=1_000_000)
    code: str | None = Field(default=None, max_length=50)
    description: str | None = Field(default=None, min_length=1, max_length=5_000)
    unit: str | None = Field(default=None, min_length=1, max_length=20)
    quantity: Decimal | None = None
    is_optional: bool | None = None
    cost_line_id: UUID | None = None
    notes: str | None = Field(default=None, max_length=5_000)
    metadata: dict[str, Any] | None = None

    @field_validator("code", "description", "unit", "notes")
    @classmethod
    def _sanitize_strings(cls, v: str | None) -> str | None:
        return _reject_unsafe_string(v, "value")

    @field_validator("quantity", mode="before")
    @classmethod
    def _check_quantity(cls, v: Any) -> Decimal | None:
        return None if v is None else _validate_decimal(v, "quantity")


class RFQLineResponse(BaseModel):
    """A scope line returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    rfq_id: UUID
    line_no: int
    code: str | None = None
    description: str
    unit: str
    quantity: Decimal = Decimal("0")
    is_optional: bool = False
    cost_line_id: UUID | None = None
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime

    @field_serializer("quantity", when_used="json")
    def _ser_quantity(self, v: Decimal) -> str | None:
        return _serialise_decimal(v)


class BidLineCreate(BaseModel):
    """A supplier's price for one line of the scope.

    ``amount`` may be omitted, in which case it is taken as
    ``quantity * unit_rate``. Leaving it to the client to send a total that
    disagrees with its own factors is how a comparison ends up ranking a number
    nobody can reproduce.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    rfq_line_id: UUID | None = None
    description: str | None = Field(default=None, max_length=5_000)
    unit: str = Field(default="", max_length=20)
    quantity: Decimal = Field(default=Decimal("0"))
    unit_rate: Decimal = Field(default=Decimal("0"))
    amount: Decimal | None = None
    unit_conversion_factor: Decimal | None = None
    is_excluded: bool = False
    notes: str | None = Field(default=None, max_length=5_000)

    @field_validator("description", "notes")
    @classmethod
    def _sanitize_strings(cls, v: str | None) -> str | None:
        return _reject_unsafe_string(v, "value")

    @field_validator("quantity", "unit_rate", mode="before")
    @classmethod
    def _check_quantity(cls, v: Any) -> Decimal:
        return _validate_decimal(v, "quantity")

    @field_validator("amount", mode="before")
    @classmethod
    def _check_amount(cls, v: Any) -> Decimal | None:
        return None if v is None else _validate_decimal(v, "amount", max_places=2)

    @field_validator("unit_conversion_factor", mode="before")
    @classmethod
    def _check_factor(cls, v: Any) -> Decimal | None:
        if v is None:
            return None
        factor = _validate_decimal(v, "unit_conversion_factor", max_places=6)
        if factor <= 0:
            raise ValueError(f"unit_conversion_factor must be > 0, got {v!r}")
        return factor


class BidLineResponse(BaseModel):
    """A supplier's priced line returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    bid_id: UUID
    rfq_line_id: UUID | None = None
    description: str | None = None
    unit: str = ""
    quantity: Decimal = Decimal("0")
    unit_rate: Decimal = Decimal("0")
    amount: Decimal = Decimal("0")
    unit_conversion_factor: Decimal | None = None
    is_excluded: bool = False
    notes: str | None = None
    created_at: datetime
    updated_at: datetime

    @field_serializer("quantity", "unit_rate", "amount", "unit_conversion_factor", when_used="json")
    def _ser_decimals(self, v: Decimal | None) -> str | None:
        return _serialise_decimal(v)


class BidAdjustmentCreate(BaseModel):
    """An inclusion or exclusion that moves a quote's comparable total."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    kind: str = Field(..., max_length=40)
    description: str | None = Field(default=None, max_length=5_000)
    amount: Decimal = Field(default=Decimal("0"))
    currency_code: str | None = Field(default=None, max_length=10)
    included_in_bid: bool = False
    source: str = Field(default="bidder", max_length=20)

    @field_validator("description")
    @classmethod
    def _sanitize_strings(cls, v: str | None) -> str | None:
        return _reject_unsafe_string(v, "value")

    @field_validator("kind")
    @classmethod
    def _check_kind(cls, v: str) -> str:
        cleaned = str(v or "").strip().lower()
        if cleaned not in ADJUSTMENT_KINDS:
            raise ValueError(f"kind must be one of {sorted(ADJUSTMENT_KINDS)}, got {v!r}")
        return cleaned

    @field_validator("source")
    @classmethod
    def _check_source(cls, v: str) -> str:
        cleaned = str(v or "").strip().lower()
        if cleaned not in ADJUSTMENT_SOURCES:
            raise ValueError(f"source must be one of {sorted(ADJUSTMENT_SOURCES)}, got {v!r}")
        return cleaned

    @field_validator("amount", mode="before")
    @classmethod
    def _check_amount(cls, v: Any) -> Decimal:
        # Signed on purpose: a discount lowers the comparable total.
        return _validate_decimal(v, "amount", allow_negative=True, max_places=2)

    @field_validator("currency_code")
    @classmethod
    def _normalise_currency(cls, v: str | None) -> str | None:
        return _validate_currency_code(v)


class BidAdjustmentResponse(BaseModel):
    """An adjustment returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    bid_id: UUID
    kind: str
    description: str | None = None
    amount: Decimal = Decimal("0")
    currency_code: str = "EUR"
    included_in_bid: bool = False
    source: str = "bidder"
    created_at: datetime
    updated_at: datetime

    @field_serializer("amount", when_used="json")
    def _ser_amount(self, v: Decimal) -> str | None:
        return _serialise_decimal(v)


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
    status: str = "received"
    is_late: bool = False
    admitted_by: UUID | None = None
    admitted_at: str | None = None
    admission_reason: str | None = None
    late_reason: str | None = None
    disqualified_reason: str | None = None
    withdrawn_at: str | None = None
    withdrawn_reason: str | None = None
    exchange_rate: Decimal | None = None
    exchange_rate_date: str | None = None
    exchange_rate_source: str | None = None
    lines: list[BidLineResponse] = Field(default_factory=list)
    adjustments: list[BidAdjustmentResponse] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime

    @field_serializer("exchange_rate", when_used="json")
    def _ser_rate(self, v: Decimal | None) -> str | None:
        return _serialise_decimal(v)


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
    evaluation_method: str = "lowest_price"
    technical_weight: Decimal = Decimal("0")
    require_full_scope: bool = True
    created_by: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    lines: list[RFQLineResponse] = Field(default_factory=list)
    bids: list[RFQBidResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    @field_serializer("technical_weight", when_used="json")
    def _ser_weight(self, v: Decimal) -> str | None:
        return _serialise_decimal(v)


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
    # The rate this quote is to be compared at, in units of the RFQ currency
    # per one unit of the quote's currency. Required only when the currencies
    # differ; the comparison never invents one.
    exchange_rate: Decimal | None = None
    exchange_rate_date: str | None = Field(default=None, max_length=20)
    exchange_rate_source: str | None = Field(default=None, max_length=60)
    # Supplied when the buyer records a quote that arrived after the deadline.
    # Recording it is not admitting it: the quote lands with status ``late`` and
    # stays out of the ranking until somebody admits it explicitly.
    late_reason: str | None = Field(default=None, max_length=5_000)
    lines: list[BidLineCreate] = Field(default_factory=list, max_length=2_000)
    adjustments: list[BidAdjustmentCreate] = Field(default_factory=list, max_length=200)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("exchange_rate", mode="before")
    @classmethod
    def _check_rate(cls, v: Any) -> Decimal | None:
        if v is None:
            return None
        rate = _validate_decimal(v, "exchange_rate", max_places=8)
        if rate <= 0:
            raise ValueError(f"exchange_rate must be > 0, got {v!r}")
        return rate

    @field_validator("late_reason", "exchange_rate_source", "exchange_rate_date")
    @classmethod
    def _sanitize_optional(cls, v: str | None) -> str | None:
        return _reject_unsafe_string(v, "value")

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
        # bid_amount is required, never None - assert for type-checker.
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
    offset: int
    limit: int


class RFQLineListResponse(BaseModel):
    """The scope lines of one RFQ, in line order."""

    items: list[RFQLineResponse]
    total: int


# ── Decisions that need a reason on the record ──────────────────────────────


class BidDecision(BaseModel):
    """A decision taken about one quote, with the reason it was taken.

    Withdrawing, disqualifying and admitting a late quote all change which
    offers the ranking is allowed to consider, so each one carries words
    somebody signed their name to rather than a bare status flip.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    reason: str = Field(..., min_length=1, max_length=5_000)

    @field_validator("reason")
    @classmethod
    def _check_reason(cls, v: str) -> str:
        return _validate_reason(v, "reason")


class BidAwardRequest(BaseModel):
    """Context recorded with an award.

    ``reason`` is REQUIRED by the service (400 without one) - it is the
    justification on the file. ``gate_override_reason`` is demanded only
    when awarding below the tiered quote rule; ``po_number`` rides onto the
    award record and the confirmation correspondence.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    reason: str | None = Field(default=None, max_length=5_000)
    gate_override_reason: str | None = Field(default=None, max_length=2_000)
    po_number: str | None = Field(default=None, max_length=60)

    @field_validator("reason")
    @classmethod
    def _sanitize_reason(cls, v: str | None) -> str | None:
        return _reject_unsafe_string(v, "reason")

    @field_validator("gate_override_reason")
    @classmethod
    def _sanitize_override(cls, v: str | None) -> str | None:
        return _reject_unsafe_string(v, "gate_override_reason")

    @field_validator("po_number")
    @classmethod
    def _sanitize_po(cls, v: str | None) -> str | None:
        return _reject_unsafe_string(v, "po_number")


# ── Comparison ──────────────────────────────────────────────────────────────


class QuoteComparisonResponse(BaseModel):
    """One quote restated on the RFQ's basis.

    Amounts are Decimal-as-strings in the RFQ's currency. ``normalised_amount``
    is ``null`` for a quote that could not be brought onto the basis; the
    ``reasons`` list then says why, and that quote carries no rank.
    """

    bid_id: str
    bidder_contact_id: str
    status: str
    is_late: bool
    admitted: bool
    currency_code: str
    headline_amount: str | None = None
    exchange_rate: str | None = None
    converted_amount: str | None = None
    adjustments_applied: str
    adjustments_included: int
    normalised_amount: str | None = None
    lines_required: int
    lines_covered: int
    coverage: str
    uncovered_lines: list[str] = Field(default_factory=list)
    excluded_lines: list[str] = Field(default_factory=list)
    extra_lines: int
    line_total: str | None = None
    technical_score: str | None = None
    price_score: str | None = None
    total_score: str | None = None
    comparable: bool
    reasons: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    rank: int | None = None


class ComparisonResponse(BaseModel):
    """The ranked field of quotes for one RFQ, plus what could not be ranked."""

    rfq_id: UUID
    rfq_number: str
    basis_currency: str
    method: str
    technical_weight: str
    require_full_scope: bool
    as_of: str | None = None
    lines_required: int
    recommended_bid_id: str | None = None
    ranked: list[QuoteComparisonResponse] = Field(default_factory=list)
    excluded: list[QuoteComparisonResponse] = Field(default_factory=list)
    #: The tiered quote rule as it stands for this package: value, required
    #: count, quoted count, pass/fail. The SAME status the award enforces,
    #: so the compare panel can never read green on a package the award
    #: would refuse.
    quote_gate: dict | None = None


# ── Award record ────────────────────────────────────────────────────────────


class RFQAwardResponse(BaseModel):
    """Why one quote won, as recorded at the moment it did."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    rfq_id: UUID
    bid_id: UUID
    awarded_by: UUID | None = None
    awarded_at: str
    method: str = "lowest_price"
    reason: str | None = None
    recommended_bid_id: UUID | None = None
    is_override: bool = False
    awarded_amount: Decimal = Decimal("0")
    awarded_currency: str = "EUR"
    basis: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    @field_serializer("awarded_amount", when_used="json")
    def _ser_amount(self, v: Decimal) -> str | None:
        return _serialise_decimal(v)
