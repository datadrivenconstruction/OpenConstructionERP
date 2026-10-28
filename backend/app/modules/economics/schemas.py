# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Request schemas of the economics API.

Money, rates and percentages arrive as decimal strings (or integers) and never
as floats; ``Decimal`` fields reject a JSON float outright so ``0.1`` cannot
become ``0.1000000000000000055``. Responses are plain views whose money is a
positional decimal string, built by the service.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

FlowKind = Literal["investment", "revenue", "operating_cost", "residual"]
FlowMode = Literal["total", "per_year"]
FlowSource = Literal["manual", "cost_frame"]
SourceKind = Literal["equity", "shareholder_loan", "bank_loan", "bond", "grant", "subsidy", "sale_proceeds", "other"]
TrancheStatus = Literal["planned", "drawn", "cancelled"]


def _no_float(value: Any) -> Any:
    if isinstance(value, float):
        raise ValueError("send decimals as strings")
    return value


#: A decimal that refuses a JSON float.
Dec = Annotated[Decimal, BeforeValidator(_no_float)]
#: A non-negative money amount.
Money = Annotated[Decimal, BeforeValidator(_no_float), Field(ge=0, max_digits=18, decimal_places=4)]
Rate = Annotated[Decimal, BeforeValidator(_no_float), Field(ge=-100, le=1000, max_digits=9, decimal_places=4)]


class _In(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class PlanPatch(_In):
    discount_rate_pct: Rate | None = None
    horizon_years: int | None = Field(default=None, ge=1, le=100)
    markup_allowance: Money | None = None
    boq_id: uuid.UUID | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    classification_standard: str | None = Field(default=None, min_length=1, max_length=50)
    clear_boq: bool = False


class FlowLineIn(_In):
    kind: FlowKind
    label: str = Field(default="", max_length=255)
    mode: FlowMode | None = None
    source: FlowSource = "manual"
    amount: Money = Decimal("0")
    year_from: int = Field(default=0, ge=0, le=100)
    year_to: int | None = Field(default=None, ge=0, le=100)
    escalation_pct: Rate = Decimal("0")
    notes: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def _cost_frame_is_an_investment(self) -> FlowLineIn:
        if self.source == "cost_frame" and self.kind != "investment":
            raise ValueError("only an investment line can be read from the cost frame")
        return self


class FlowLinePatch(_In):
    label: str | None = Field(default=None, max_length=255)
    mode: FlowMode | None = None
    source: FlowSource | None = None
    amount: Money | None = None
    year_from: int | None = Field(default=None, ge=0, le=100)
    year_to: int | None = Field(default=None, ge=0, le=100)
    escalation_pct: Rate | None = None
    notes: str | None = Field(default=None, max_length=2000)


class FrameLineIn(_In):
    code: str = Field(min_length=1, max_length=80)
    title: str = Field(default="", max_length=255)
    amount: Money = Decimal("0")
    basis: str = Field(default="", max_length=2000)


class FrameLinePatch(_In):
    title: str | None = Field(default=None, max_length=255)
    amount: Money | None = None
    basis: str | None = Field(default=None, max_length=2000)


class FrameGenerateIn(_In):
    """Derive frame lines from the codes the bill uses, at ``depth`` significant digits or segments."""

    depth: int = Field(default=1, ge=1, le=6)
    # What the new lines get as budget: nothing, or the bill's own amount for the code.
    amounts: Literal["zero", "estimate"] = "estimate"
    replace: bool = False


class SourceIn(_In):
    kind: SourceKind
    name: str = Field(default="", max_length=255)
    amount: Money = Decimal("0")
    interest_rate_pct: Rate | None = None
    funding_application_id: uuid.UUID | None = None
    notes: str = Field(default="", max_length=2000)


class SourcePatch(_In):
    kind: SourceKind | None = None
    name: str | None = Field(default=None, max_length=255)
    amount: Money | None = None
    interest_rate_pct: Rate | None = None
    funding_application_id: uuid.UUID | None = None
    clear_funding_application: bool = False
    notes: str | None = Field(default=None, max_length=2000)


class TrancheIn(_In):
    due_on: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    amount: Money
    condition: str = Field(default="", max_length=2000)


class TranchePatch(_In):
    due_on: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    amount: Money | None = None
    status: TrancheStatus | None = None
    condition: str | None = Field(default=None, max_length=2000)
    drawn_on: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class ProposeIn(_In):
    rationale: str = Field(default="", max_length=4000)


class ReopenIn(_In):
    reason: str = Field(default="", max_length=2000)


SecurityKind = Literal["performance", "warranty", "advance_payment", "bid", "other"]
SecurityStatus = Literal["requested", "in_place", "released", "expired"]
InsuranceKind = Literal["builders_all_risk", "liability", "professional_indemnity", "other"]
InsuranceStatus = Literal["requested", "in_place", "expired"]
VatTreatment = Literal["standard", "reverse_charge", "exempt", "mixed", "other"]
ProcessArea = Literal["receivables", "payables", "administration"]
ProcessStatus = Literal["open", "set_up"]
_DAY = r"^\d{4}-\d{2}-\d{2}$"


class SecurityIn(_In):
    kind: SecurityKind
    description: str = Field(default="", max_length=255)
    amount: Money = Decimal("0")
    issuer: str = Field(default="", max_length=255)
    beneficiary: str = Field(default="", max_length=255)
    reference: str = Field(default="", max_length=120)
    valid_from: str | None = Field(default=None, pattern=_DAY)
    valid_until: str | None = Field(default=None, pattern=_DAY)
    status: SecurityStatus = "requested"
    notes: str = Field(default="", max_length=2000)


class SecurityPatch(_In):
    kind: SecurityKind | None = None
    description: str | None = Field(default=None, max_length=255)
    amount: Money | None = None
    issuer: str | None = Field(default=None, max_length=255)
    beneficiary: str | None = Field(default=None, max_length=255)
    reference: str | None = Field(default=None, max_length=120)
    valid_from: str | None = Field(default=None, pattern=_DAY)
    valid_until: str | None = Field(default=None, pattern=_DAY)
    status: SecurityStatus | None = None
    notes: str | None = Field(default=None, max_length=2000)


class InsuranceIn(_In):
    kind: InsuranceKind
    insurer: str = Field(default="", max_length=255)
    policy_number: str = Field(default="", max_length=120)
    sum_insured: Money = Decimal("0")
    deductible: Money = Decimal("0")
    period_from: str | None = Field(default=None, pattern=_DAY)
    period_to: str | None = Field(default=None, pattern=_DAY)
    status: InsuranceStatus = "requested"
    notes: str = Field(default="", max_length=2000)


class InsurancePatch(_In):
    kind: InsuranceKind | None = None
    insurer: str | None = Field(default=None, max_length=255)
    policy_number: str | None = Field(default=None, max_length=120)
    sum_insured: Money | None = None
    deductible: Money | None = None
    period_from: str | None = Field(default=None, pattern=_DAY)
    period_to: str | None = Field(default=None, pattern=_DAY)
    status: InsuranceStatus | None = None
    notes: str | None = Field(default=None, max_length=2000)


class TaxIn(_In):
    """The tax treatment; ``confirm`` stamps the caller and the moment as the confirmation."""

    vat_treatment: VatTreatment = "standard"
    input_tax_deduction: bool | None = None
    notes: str = Field(default="", max_length=2000)
    confirm: bool = False


class ProcessIn(_In):
    description: str = Field(default="", max_length=2000)
    owner: str = Field(default="", max_length=255)
    status: ProcessStatus = "open"
    set_up_on: str | None = Field(default=None, pattern=_DAY)
    notes: str = Field(default="", max_length=2000)
