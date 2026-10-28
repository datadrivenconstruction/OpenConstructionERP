# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pydantic schemas for the allowances & contingency register API.

Money contract (matches cvr/schemas.py): every monetary value is a
:class:`decimal.Decimal` in Python and on the database (``NUMERIC(18, 4)``), and
is emitted on the wire as a plain decimal *string* through :data:`DecimalMoney`
so a large held amount round-trips without JSON's float bridge silently rounding
it. Inputs accept any JSON number or numeric string - Pydantic promotes them to
``Decimal`` and ``ge=0`` rejects a negative. Money is never a float.
"""

from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

# Money fields are exchanged as strings on the wire (mirrors the DecimalMoney
# alias in cvr/schemas.py) so a precision-critical value never rides through a
# JSON float. The Decimal is quantized to 2dp before it reaches here, so
# ``str(v)`` is already the canonical amount.
DecimalMoney = Annotated[
    Decimal,
    PlainSerializer(lambda v: str(v) if v is not None else None, return_type=str),
]

# provisional_sum | pc_sum | contingency - the three kinds an estimate carries.
_ALLOWANCE_TYPE_PATTERN = r"^(provisional_sum|pc_sum|contingency)$"


# ── Allowance ──────────────────────────────────────────────────────────────


class AllowanceCreate(BaseModel):
    """Create an allowance within a project's register."""

    model_config = ConfigDict(str_strip_whitespace=True)

    label: str = Field(default="", max_length=255)
    allowance_type: str = Field(
        default="provisional_sum",
        pattern=_ALLOWANCE_TYPE_PATTERN,
        examples=["provisional_sum", "pc_sum", "contingency"],
    )
    held_amount: DecimalMoney = Field(default=Decimal("0"), ge=0)
    currency: str = Field(default="", max_length=3, examples=["USD", "EUR", "GBP"])
    notes: str | None = Field(default=None, max_length=5000)


class AllowanceUpdate(BaseModel):
    """Partial update for an allowance."""

    model_config = ConfigDict(str_strip_whitespace=True)

    label: str | None = Field(default=None, max_length=255)
    allowance_type: str | None = Field(default=None, pattern=_ALLOWANCE_TYPE_PATTERN)
    held_amount: DecimalMoney | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=3)
    notes: str | None = Field(default=None, max_length=5000)


class AllowanceResponse(BaseModel):
    """An allowance returned from the API, with its derived drawn / remaining.

    ``held_amount`` is what the register carries; ``drawn`` is the sum of the
    allowance's drawdowns; ``remaining`` is ``held - drawn`` (which MAY be
    negative). ``overdrawn`` flags that advisory over-draw condition, and
    ``drawdown_count`` is how many drawdowns back the figures. All money is a
    Decimal-as-string.
    """

    id: UUID
    project_id: UUID
    label: str = ""
    allowance_type: str = "provisional_sum"
    held_amount: DecimalMoney = Decimal("0")
    currency: str = ""
    notes: str | None = None
    drawn: DecimalMoney = Decimal("0")
    remaining: DecimalMoney = Decimal("0")
    overdrawn: bool = False
    drawdown_count: int = 0
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime


# ── Drawdown ───────────────────────────────────────────────────────────────


class DrawdownCreate(BaseModel):
    """Record an amount drawn against an allowance."""

    model_config = ConfigDict(str_strip_whitespace=True)

    amount: DecimalMoney = Field(default=Decimal("0"), ge=0)
    note: str | None = Field(default=None, max_length=2000)


class DrawdownResponse(BaseModel):
    """A single drawdown returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    allowance_id: UUID
    amount: DecimalMoney = Decimal("0")
    note: str | None = None
    created_by: str | None = None
    created_at: datetime


# ── Register summary ───────────────────────────────────────────────────────


class TypeRollupOut(BaseModel):
    """Held / drawn / remaining for one allowance type in one currency."""

    allowance_type: str
    held: DecimalMoney = Decimal("0")
    drawn: DecimalMoney = Decimal("0")
    remaining: DecimalMoney = Decimal("0")
    count: int = 0
    overdrawn: bool = False


class CurrencyRollupOut(BaseModel):
    """The register's held / drawn / remaining position in one currency.

    ``remaining`` is the figure the estimate carries forward for this currency.
    ``by_type`` breaks the same totals down by allowance type.
    """

    currency: str = ""
    held: DecimalMoney = Decimal("0")
    drawn: DecimalMoney = Decimal("0")
    remaining: DecimalMoney = Decimal("0")
    count: int = 0
    overdrawn: bool = False
    by_type: list[TypeRollupOut] = Field(default_factory=list)


class AllowanceRegisterSummary(BaseModel):
    """The composed allowances register for a project (money never blended).

    ``by_currency`` holds one :class:`CurrencyRollupOut` per currency, ordered by
    descending held then code. ``primary_currency`` is the currency carrying the
    most held (``""`` when the register is empty). ``allowance_count`` is the
    total number of allowances across every currency.
    """

    project_id: UUID
    by_currency: list[CurrencyRollupOut] = Field(default_factory=list)
    primary_currency: str = ""
    allowance_count: int = 0
