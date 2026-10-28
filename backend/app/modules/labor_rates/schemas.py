# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Labor rate Pydantic schemas - request/response models.

Every monetary value follows the platform money contract: it is accepted as a
``Decimal`` and emitted in JSON as a plain decimal string so large amounts
round-trip without float precision loss. The on-cost ``value`` is also emitted
as a decimal string - it is a percentage when the component kind is
``percentage`` and a currency amount when it is ``fixed``.
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer

OnCostKind = Literal["percentage", "fixed"]


def _serialise_decimal(value: Decimal | None) -> str | None:
    """Serialise a ``Decimal`` to a plain decimal string (money contract)."""
    if value is None:
        return None
    if not isinstance(value, Decimal):
        try:
            value = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return "0"
    if not value.is_finite():
        return "0"
    return format(value, "f")


# ── Compute request ──────────────────────────────────────────────────────────


class OnCostIn(BaseModel):
    """One on-cost component in a compute request or a template payload."""

    model_config = ConfigDict(str_strip_whitespace=True)

    label: str = Field(..., min_length=1, max_length=255)
    kind: OnCostKind = "percentage"
    value: Decimal = Decimal("0")

    @field_serializer("value", when_used="json")
    def _ser_value(self, v: Decimal) -> str | None:
        return _serialise_decimal(v)


class CrewMemberIn(BaseModel):
    """One trade line in a compute request or a crew payload."""

    model_config = ConfigDict(str_strip_whitespace=True)

    trade: str = Field(..., min_length=1, max_length=120)
    count: int = Field(default=1, ge=0, le=100_000)
    all_in_rate: Decimal = Decimal("0")

    @field_serializer("all_in_rate", when_used="json")
    def _ser_rate(self, v: Decimal) -> str | None:
        return _serialise_decimal(v)


class ComputeRequest(BaseModel):
    """Stateless request to build an all-in rate and (optionally) a crew blend."""

    model_config = ConfigDict(str_strip_whitespace=True)

    base_wage: Decimal = Decimal("0")
    currency: str = Field(default="", max_length=3)
    components: list[OnCostIn] = Field(default_factory=list)
    crew: list[CrewMemberIn] = Field(default_factory=list)

    @field_serializer("base_wage", when_used="json")
    def _ser_base(self, v: Decimal) -> str | None:
        return _serialise_decimal(v)


# ── Compute response ─────────────────────────────────────────────────────────


class OnCostLineOut(BaseModel):
    """One evaluated on-cost row in the build-up breakdown."""

    label: str
    kind: OnCostKind
    value: Decimal = Decimal("0")
    amount: Decimal = Decimal("0")
    subtotal: Decimal = Decimal("0")

    @field_serializer("value", "amount", "subtotal", when_used="json")
    def _ser(self, v: Decimal) -> str | None:
        return _serialise_decimal(v)


class CrewMemberLineOut(BaseModel):
    """One evaluated crew member row."""

    trade: str
    count: int = 0
    all_in_rate: Decimal = Decimal("0")
    line_cost: Decimal = Decimal("0")

    @field_serializer("all_in_rate", "line_cost", when_used="json")
    def _ser(self, v: Decimal) -> str | None:
        return _serialise_decimal(v)


class CrewBreakdown(BaseModel):
    """The blended crew rate result."""

    currency: str = ""
    headcount: int = 0
    total_cost_per_hour: Decimal = Decimal("0")
    blended_hourly_rate: Decimal = Decimal("0")
    members: list[CrewMemberLineOut] = Field(default_factory=list)

    @field_serializer("total_cost_per_hour", "blended_hourly_rate", when_used="json")
    def _ser(self, v: Decimal) -> str | None:
        return _serialise_decimal(v)


class RateBreakdown(BaseModel):
    """The full all-in rate build-up, optionally with a crew blend."""

    base_wage: Decimal = Decimal("0")
    currency: str = ""
    percentage_total: Decimal = Decimal("0")
    fixed_total: Decimal = Decimal("0")
    all_in_rate: Decimal = Decimal("0")
    lines: list[OnCostLineOut] = Field(default_factory=list)
    crew: CrewBreakdown | None = None

    @field_serializer("base_wage", "percentage_total", "fixed_total", "all_in_rate", when_used="json")
    def _ser(self, v: Decimal) -> str | None:
        return _serialise_decimal(v)


# ── Template CRUD ────────────────────────────────────────────────────────────


class TemplateCreate(BaseModel):
    """Create a labor rate template with its on-cost components.

    ``base_wage`` is required and must be positive. It used to default to zero
    with no constraint, and a template saved that way built up to an all-in rate
    of ``0.00`` - which is not ``None``, so every consumer read it as a priced
    rate and charged nothing for the labour hours while flagging nothing.
    Percentage on-costs cannot rescue such a template either, because they are a
    share of the base wage and a share of zero is zero.

    The field is required rather than defaulted-and-constrained because Pydantic
    does not validate defaults: ``Field(default=Decimal("0"), gt=0)`` still lets
    an omitted field through as zero, which is the very payload that reported
    the defect.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=255)
    base_wage: Decimal = Field(..., gt=0)
    currency: str = Field(default="", max_length=3)
    description: str = Field(default="", max_length=2000)
    components: list[OnCostIn] = Field(default_factory=list)

    @field_serializer("base_wage", when_used="json")
    def _ser_base(self, v: Decimal) -> str | None:
        return _serialise_decimal(v)


class TemplateUpdate(BaseModel):
    """Partial update for a template.

    When ``components`` is provided the whole component list is replaced; when
    omitted the existing components are left untouched.

    ``base_wage`` carries the same positive constraint as on create, so a
    template cannot be corrected down into the silent zero that create refuses.
    Omitting it still leaves the stored wage untouched.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    base_wage: Decimal | None = Field(default=None, gt=0)
    currency: str | None = Field(default=None, max_length=3)
    description: str | None = Field(default=None, max_length=2000)
    components: list[OnCostIn] | None = None

    @field_serializer("base_wage", when_used="json")
    def _ser_base(self, v: Decimal | None) -> str | None:
        return _serialise_decimal(v)


class OnCostOut(BaseModel):
    """A persisted on-cost component returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    template_id: UUID
    label: str
    kind: OnCostKind
    value: Decimal = Decimal("0")
    sort_order: int = 0

    @field_serializer("value", when_used="json")
    def _ser_value(self, v: Decimal) -> str | None:
        return _serialise_decimal(v)


class TemplateResponse(BaseModel):
    """A labor rate template with its components and computed all-in rate."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    owner_id: UUID | None = None
    name: str
    base_wage: Decimal = Decimal("0")
    currency: str = ""
    description: str = ""
    components: list[OnCostOut] = Field(default_factory=list)
    # Convenience: the fully loaded rate computed from base_wage + components,
    # so a list view can show the headline number without a compute round-trip.
    all_in_rate: Decimal = Decimal("0")
    created_at: datetime
    updated_at: datetime

    @field_serializer("base_wage", "all_in_rate", when_used="json")
    def _ser(self, v: Decimal) -> str | None:
        return _serialise_decimal(v)


# ── Crew persistence ─────────────────────────────────────────────────────────


class CrewSaveRequest(BaseModel):
    """Create or replace the members of a crew.

    When ``crew_id`` is omitted a new crew id is generated. Saving replaces the
    full member list for the crew id.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    crew_id: UUID | None = None
    currency: str = Field(default="", max_length=3)
    members: list[CrewMemberIn] = Field(default_factory=list)


class CrewMemberOut(BaseModel):
    """A persisted crew member returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    crew_id: UUID
    trade: str
    count: int = 0
    all_in_rate: Decimal = Decimal("0")
    currency: str = ""
    sort_order: int = 0
    created_at: datetime
    updated_at: datetime

    @field_serializer("all_in_rate", when_used="json")
    def _ser_rate(self, v: Decimal) -> str | None:
        return _serialise_decimal(v)


class CrewResponse(BaseModel):
    """A saved crew: its members plus the blended rate breakdown."""

    crew_id: UUID
    currency: str = ""
    headcount: int = 0
    total_cost_per_hour: Decimal = Decimal("0")
    blended_hourly_rate: Decimal = Decimal("0")
    members: list[CrewMemberOut] = Field(default_factory=list)

    @field_serializer("total_cost_per_hour", "blended_hourly_rate", when_used="json")
    def _ser(self, v: Decimal) -> str | None:
        return _serialise_decimal(v)


# ── Publish a template's rate as a cost item ─────────────────────────────────


class PublishTemplateRequest(BaseModel):
    """Body for publishing a template's all-in rate as a labor cost item.

    Every field is optional: with an empty body the template's own currency is
    used and a global (region-less) cost item is produced. The response is the
    created (or updated, on a re-publish) cost item itself.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    region: str | None = Field(
        default=None,
        max_length=50,
        description="Region tag for the published cost item; blank = global.",
    )
    catalog_id: UUID | None = Field(
        default=None,
        description="Owning cost catalog id; the item inherits its currency when no currency is given.",
    )
    currency: str | None = Field(
        default=None,
        max_length=3,
        description="ISO 4217 currency override; defaults to the template currency.",
    )
