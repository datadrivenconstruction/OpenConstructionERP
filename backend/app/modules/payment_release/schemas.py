# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Payment release request and response schemas.

Money travels as decimal strings in both directions, never as floats.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.contracts.retention import CANONICAL_RELEASE_EVENTS, canonical_release_event
from app.modules.payment_release.release_math import DISCOUNT_SCOPES, INVOICE_KINDS, INVOICE_MODES, RETENTION_BASES

Money = str
Percent = Annotated[Decimal, Field(ge=0, le=100, max_digits=5, decimal_places=2)]
Amount = Annotated[Decimal, Field(ge=0, max_digits=18, decimal_places=2)]

InvoiceMode = Literal["incremental", "cumulative"]
InvoiceKind = Literal["interim", "final", "daywork", "credit_note"]
RetentionBasis = Literal["net", "gross"]
DiscountScope = Literal["interim", "final", "both"]
RetentionKind = Literal["interim", "warranty"]
#: How a contract enforces the certificates its pack makes a condition of payment (rule V19).
ReleaseCertificatesEnforcement = Literal["pack", "block", "warn", "off"]

assert set(InvoiceMode.__args__) == set(INVOICE_MODES)  # type: ignore[attr-defined]
assert set(InvoiceKind.__args__) == set(INVOICE_KINDS)  # type: ignore[attr-defined]
assert set(RetentionBasis.__args__) == set(RETENTION_BASES)  # type: ignore[attr-defined]
assert set(DiscountScope.__args__) == set(DISCOUNT_SCOPES)  # type: ignore[attr-defined]


def _release_event(value: str) -> str:
    event = canonical_release_event(value)
    if event not in CANONICAL_RELEASE_EVENTS:
        raise ValueError(f"unknown release event, use one of {', '.join(CANONICAL_RELEASE_EVENTS)}")
    return event


#: A completion event in the contracts vocabulary; aliases (practical completion, handover) are accepted.
ReleaseEventName = Annotated[str, AfterValidator(_release_event)]


def _finite(value: Decimal | None) -> Decimal | None:
    if value is not None and not value.is_finite():
        raise ValueError("must be a finite number")
    return value


# ── Payment terms ────────────────────────────────────────────────────────


class PaymentTermsBody(BaseModel):
    """A contract's payment terms. The optional features stay off until switched on."""

    model_config = ConfigDict(extra="forbid")

    invoice_mode: InvoiceMode = "incremental"
    # Interim retention lives on the contract (``Contract.retention_percent``); edited here, written there.
    retention_percent: Percent = Decimal("0")
    retention_release_event: ReleaseEventName = "substantial_completion"
    retention_basis: RetentionBasis = "net"
    warranty_enabled: bool = False
    warranty_percent: Percent = Decimal("0")
    warranty_release_event: ReleaseEventName = "defects_period_end"
    warranty_period_months: int | None = Field(default=None, ge=0, le=240)
    discount_enabled: bool = False
    discount_percent: Percent = Decimal("0")
    discount_days: int = Field(default=0, ge=0, le=365)
    discount_applies_to: DiscountScope = "both"
    rounding_enabled: bool = False
    rounding_step: Amount = Decimal("0")
    interim_due_days: int | None = Field(default=None, ge=0, le=365)
    final_due_days: int | None = Field(default=None, ge=0, le=365)
    # Not sent: the contract keeps what it had. Stored in the terms' metadata, no column.
    release_certificates_enforcement: ReleaseCertificatesEnforcement | None = None

    _finite_values = field_validator("retention_percent", "warranty_percent", "discount_percent", "rounding_step")(
        _finite
    )

    @model_validator(mode="after")
    def _switched_on_features_are_complete(self) -> PaymentTermsBody:
        if self.warranty_enabled and self.warranty_percent <= 0:
            raise ValueError("warranty_percent: set a rate above zero, or switch warranty retention off")
        if self.discount_enabled and (self.discount_percent <= 0 or self.discount_days <= 0):
            raise ValueError("discount: set a rate and a number of days, or switch the discount off")
        if self.rounding_enabled and self.rounding_step <= 0:
            raise ValueError("rounding_step: set a step above zero, or switch rounding off")
        return self


class PaymentTermsResponse(BaseModel):
    """The terms in force, and whether anyone has set them (else they are the defaults)."""

    contract_id: str
    terms_set: bool
    currency: str
    invoice_mode: InvoiceMode
    retention_percent: Decimal
    retention_release_event: str
    retention_basis: RetentionBasis
    warranty_enabled: bool
    warranty_percent: Decimal
    warranty_release_event: str
    warranty_period_months: int | None
    discount_enabled: bool
    discount_percent: Decimal
    discount_days: int
    discount_applies_to: DiscountScope
    rounding_enabled: bool
    rounding_step: Decimal
    interim_due_days: int | None
    final_due_days: int | None
    release_certificates_enforcement: ReleaseCertificatesEnforcement = "pack"


# ── Invoice in the release view ──────────────────────────────────────────


class InvoiceReleaseUpdate(BaseModel):
    """What a controller sets on one invoice before its release. Fields left out keep their value."""

    model_config = ConfigDict(extra="forbid")

    kind: InvoiceKind | None = None
    contract_id: str | None = None
    net_deduction: Amount | None = None
    net_deduction_note: str | None = Field(default=None, max_length=500)
    gross_deduction: Amount | None = None
    gross_deduction_note: str | None = Field(default=None, max_length=500)

    _finite_values = field_validator("net_deduction", "gross_deduction")(_finite)


class ReleaseFigures(BaseModel):
    """Every step of one release as decimal strings (see :class:`release_math.Release`)."""

    model_config = ConfigDict(extra="allow")


class LedgerInvoice(BaseModel):
    invoice_id: str
    number: str
    invoice_date: str | None
    finance_status: str
    kind: InvoiceKind
    kind_set: bool
    contract_source: str | None
    release_status: Literal["open", "released"]
    released_at: str | None
    net_deduction_note: str
    gross_deduction_note: str
    figures: dict[str, Any]
    computed: dict[str, Any]
    differs: bool
    counted: bool
    progress_pct: str | None
    paid: Money
    paid_cash: Money
    discount_taken: Money
    open_amount: Money


class LedgerTotals(BaseModel):
    contract_value: Money
    invoiced: Money
    invoiced_pct: str | None
    released: Money
    payable: Money
    paid: Money
    open_amount: Money
    retention_held: Money
    retention_posted: Money


class LedgerContract(BaseModel):
    contract_id: str
    code: str
    title: str
    status: str
    invoice_mode: InvoiceMode
    terms_set: bool
    original_value: Money
    changes: Money
    current_value: Money
    changes_pct: str | None
    measured: Money
    measured_pct: str | None
    has_measurement: bool
    invoices: list[LedgerInvoice]
    totals: LedgerTotals


class LooseInvoice(BaseModel):
    invoice_id: str
    number: str
    invoice_date: str | None
    finance_status: str
    net: Money
    gross: Money
    paid: Money
    purchase_order_id: str | None


class ProjectLedger(BaseModel):
    project_id: str
    currency: str
    contracts: list[LedgerContract]
    other_invoices: list[LooseInvoice]
    totals: LedgerTotals


# ── Retention register ───────────────────────────────────────────────────


class RetentionPostingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retention_kind: RetentionKind = "interim"
    event: ReleaseEventName
    event_on: date | None = None
    amount: Annotated[Decimal, Field(gt=0, max_digits=18, decimal_places=2)]
    posted_on: date
    document_ref: str | None = Field(default=None, max_length=255)
    note: str | None = Field(default=None, max_length=4000)

    _finite_values = field_validator("amount")(_finite)


class RetentionPostingResponse(BaseModel):
    id: str
    contract_id: str
    retention_kind: str
    event: str
    event_on: str | None
    amount: Money
    posted_on: str
    status: str
    document_ref: str
    note: str


class RetentionContract(BaseModel):
    contract_id: str
    code: str
    title: str
    status: str
    retention_percent: str
    retention_release_event: str
    warranty_enabled: bool
    warranty_percent: str
    warranty_release_event: str
    warranty_period_months: int | None
    withheld: Money
    posted: Money
    held: Money
    postings: list[RetentionPostingResponse]


class RetentionRegister(BaseModel):
    project_id: str
    currency: str
    contracts: list[RetentionContract]
    held: Money
    posted: Money


# ── Findings ─────────────────────────────────────────────────────────────


class ReleaseFinding(BaseModel):
    rule_id: str
    rule_number: str
    severity: str
    message: str
    suggestion: str | None = None
    element_ref: str | None = None
    problem: str | None = None


class ReleaseFindings(BaseModel):
    project_id: str
    findings: list[ReleaseFinding]
    errors: int
    warnings: int


class InvoiceReleaseState(BaseModel):
    """Where one invoice stands in the release view after a change."""

    invoice_id: str
    contract_id: str | None
    kind: str
    status: str
    release_amount: Money | None
    payable_amount: Money | None
