# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Guarantees​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ register Pydantic v2 schemas.

Money crosses the wire as a decimal string, dates as ``YYYY-MM-DD``. The ``Literal``
vocabularies mirror :mod:`app.modules.guarantees.logic` and a test pins them equal.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer


def _plain(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


Money = Annotated[Decimal, PlainSerializer(_plain, return_type=str, when_used="json")]
MoneyOpt = Annotated[Decimal | None, PlainSerializer(_plain, return_type=str | None, when_used="json")]

GuaranteeTypeLiteral = Literal[
    "bid_bond", "performance_bond", "advance_payment", "retention_bond", "warranty_bond", "parent_company"
]
StatusLiteral = Literal["draft", "requested", "issued", "extended", "reduced", "released", "called", "expired"]
DirectionLiteral = Literal["given", "received"]
DocumentKindLiteral = Literal["original", "amendment", "extension", "reduction", "release", "call", "other"]


class GuaranteeBase(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    guarantee_type: GuaranteeTypeLiteral
    direction: DirectionLiteral = "given"
    issuer_bank: str = Field(default="", max_length=255)
    bank_reference: str | None = Field(default=None, max_length=120)
    beneficiary: str = Field(default="", max_length=255)
    applicant: str = Field(default="", max_length=255)
    amount: Decimal = Field(default=Decimal("0"), ge=0)
    currency: str = Field(default="", max_length=3)
    percent_of_contract: Decimal | None = Field(default=None, ge=0, le=100)
    contract_value: Decimal | None = Field(default=None, ge=0)
    issue_date: date | None = None
    expiry_date: date | None = None
    auto_extend: bool = False
    extension_months: int | None = Field(default=None, ge=1, le=120)
    claim_period_days: int | None = Field(default=None, ge=0, le=3650)
    defects_period_months: int | None = Field(default=None, ge=0, le=240)
    advance_amount: Decimal | None = Field(default=None, ge=0)
    advance_recovery_pct: Decimal | None = Field(default=None, ge=0, le=100)
    replaces_cash_retention: bool = False
    commission_rate_pct: Decimal | None = Field(default=None, ge=0, le=100)
    form_code: str | None = Field(default=None, max_length=60)
    contract_id: UUID | None = None
    subcontractor_id: UUID | None = None
    tender_id: UUID | None = None
    bid_id: UUID | None = None
    facility_id: UUID | None = None
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class GuaranteeCreate(GuaranteeBase):
    """Create a guarantee; it starts in ``draft`` unless ``status`` says otherwise."""

    reference: str | None = Field(default=None, max_length=60)
    status: Literal["draft", "requested", "issued"] = "draft"


class GuaranteeUpdate(BaseModel):
    """Edit the descriptive fields. Status moves go through the transition endpoint."""

    model_config = ConfigDict(str_strip_whitespace=True)

    reference: str | None = Field(default=None, max_length=60)
    issuer_bank: str | None = Field(default=None, max_length=255)
    bank_reference: str | None = Field(default=None, max_length=120)
    beneficiary: str | None = Field(default=None, max_length=255)
    applicant: str | None = Field(default=None, max_length=255)
    amount: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=3)
    percent_of_contract: Decimal | None = Field(default=None, ge=0, le=100)
    contract_value: Decimal | None = Field(default=None, ge=0)
    issue_date: date | None = None
    expiry_date: date | None = None
    auto_extend: bool | None = None
    extension_months: int | None = Field(default=None, ge=1, le=120)
    claim_period_days: int | None = Field(default=None, ge=0, le=3650)
    defects_period_months: int | None = Field(default=None, ge=0, le=240)
    advance_amount: Decimal | None = Field(default=None, ge=0)
    advance_recovery_pct: Decimal | None = Field(default=None, ge=0, le=100)
    replaces_cash_retention: bool | None = None
    commission_rate_pct: Decimal | None = Field(default=None, ge=0, le=100)
    form_code: str | None = Field(default=None, max_length=60)
    contract_id: UUID | None = None
    subcontractor_id: UUID | None = None
    tender_id: UUID | None = None
    bid_id: UUID | None = None
    facility_id: UUID | None = None
    notes: str | None = None
    metadata: dict[str, Any] | None = None


class TransitionRequest(BaseModel):
    """Move a guarantee to a new status, optionally with a new expiry or amount."""

    status: StatusLiteral
    new_expiry_date: date | None = None
    new_amount: Decimal | None = Field(default=None, ge=0)
    note: str | None = Field(default=None, max_length=2000)


class AdvanceRecoveryRequest(BaseModel):
    """Advance recovered through one interim payment (reduces the advance guarantee)."""

    recovered_amount: Decimal = Field(gt=0)
    source: str | None = Field(default=None, max_length=60)
    source_id: str | None = Field(default=None, max_length=36)
    note: str | None = Field(default=None, max_length=2000)


class DocumentLinkRequest(BaseModel):
    document_id: UUID
    kind: DocumentKindLiteral = "original"
    title: str = Field(default="", max_length=255)


class GuaranteeDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: UUID
    kind: str
    title: str
    created_at: datetime


class GuaranteeEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    action: str
    from_status: str | None = None
    to_status: str | None = None
    amount_before: MoneyOpt = None
    amount_after: MoneyOpt = None
    changes: dict[str, Any] = Field(default_factory=dict)
    source: str | None = None
    source_id: str | None = None
    note: str | None = None
    actor_id: str | None = None
    created_at: datetime


class GuaranteeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    reference: str
    guarantee_type: str
    direction: str
    status: str
    issuer_bank: str
    bank_reference: str | None = None
    beneficiary: str
    applicant: str
    amount: Money
    original_amount: Money
    currency: str
    percent_of_contract: MoneyOpt = None
    contract_value: MoneyOpt = None
    issue_date: date | None = None
    expiry_date: date | None = None
    auto_extend: bool
    extension_months: int | None = None
    claim_period_days: int | None = None
    defects_period_months: int | None = None
    advance_amount: MoneyOpt = None
    advance_recovered: Money
    advance_recovery_pct: MoneyOpt = None
    replaces_cash_retention: bool
    commission_rate_pct: MoneyOpt = None
    form_code: str | None = None
    contract_id: UUID | None = None
    contract_security_id: UUID | None = None
    subcontractor_id: UUID | None = None
    tender_id: UUID | None = None
    bid_id: UUID | None = None
    facility_id: UUID | None = None
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    documents: list[GuaranteeDocumentResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    # Derived, never stored.
    days_to_expiry: int | None = None
    alert_band: int | None = None
    outstanding_advance: MoneyOpt = None


class GuaranteeDetailResponse(GuaranteeResponse):
    events: list[GuaranteeEventResponse] = Field(default_factory=list)
    findings: list[dict[str, Any]] = Field(default_factory=list)


class FacilityCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=120)
    bank_name: str = Field(min_length=1, max_length=255)
    currency: str = Field(min_length=3, max_length=3)
    limit_amount: Decimal = Field(ge=0)
    expiry_date: date | None = None
    legal_entity_id: UUID | None = None
    notes: str | None = None


class FacilityUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=120)
    bank_name: str | None = Field(default=None, min_length=1, max_length=255)
    limit_amount: Decimal | None = Field(default=None, ge=0)
    expiry_date: date | None = None
    notes: str | None = None


class FacilityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    bank_name: str
    currency: str
    limit_amount: Money
    expiry_date: date | None = None
    legal_entity_id: UUID | None = None
    notes: str | None = None


class AmountByKey(BaseModel):
    currency: str
    amount: Money
    bank: str | None = None
    guarantee_type: str | None = None


class CreditLineUse(BaseModel):
    facility_id: str
    bank_name: str
    currency: str
    limit_amount: Money
    used_amount: Money
    available_amount: Money
    utilisation_pct: MoneyOpt = None


class ExposureResponse(BaseModel):
    live_count: int
    totals: list[AmountByKey]
    by_bank: list[AmountByKey]
    by_type: list[AmountByKey]
    held: list[AmountByKey]
    credit_lines: list[CreditLineUse]
    expiring: list[GuaranteeResponse] = Field(default_factory=list)
    project_id: UUID | None = None


class PaymentGateResponse(BaseModel):
    """Whether a contract may receive its first interim payment."""

    contract_id: UUID
    allowed: bool
    reason: str | None = None
    performance_bond_id: UUID | None = None


class SummaryResponse(BaseModel):
    """Compact per-project figures for the dashboard widget and the portfolio view."""

    project_id: UUID
    live_count: int
    expiring_count: int
    expired_count: int
    totals: list[AmountByKey]
    next_expiry: date | None = None
