# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Leasing request and response schemas. Money travels as decimal strings."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

Frequency = Literal["monthly", "quarterly", "semiannual", "annual"]
EscalationKind = Literal["none", "fixed", "index"]
LeaseStatus = Literal["draft", "active", "notice", "ended"]
UnitKind = Literal["plot", "asset", "unit"]


def _s(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


class LeaseCreate(BaseModel):
    """A new lease, created as a draft."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: uuid.UUID
    code: str = Field(..., min_length=1, max_length=50)
    unit_kind: UnitKind = "plot"
    unit_ref: str = Field(..., min_length=1, max_length=64)
    unit_label: str = Field(default="", max_length=255)
    tenant_contact_id: str = Field(..., min_length=1, max_length=36)
    landlord_legal_entity_id: uuid.UUID | None = None
    start_date: date
    end_date: date
    rent_amount: Decimal = Field(..., ge=0, max_digits=18, decimal_places=2)
    currency: str = Field(..., pattern=r"^[A-Z]{3}$")
    frequency: Frequency = "monthly"
    deposit: Decimal = Field(default=Decimal("0"), max_digits=18, decimal_places=2)
    escalation_kind: EscalationKind = "none"
    escalation_rate: Decimal | None = Field(default=None, ge=-100, le=100, max_digits=9, decimal_places=4)
    escalation_index: str | None = Field(default=None, max_length=100)
    escalation_every_months: int = Field(default=12, ge=1, le=120)
    tax_code: str | None = Field(default=None, max_length=30)
    tax_rate: Decimal = Field(default=Decimal("0"), ge=0, le=100, max_digits=7, decimal_places=4)
    payment_terms_days: int = Field(default=0, ge=0, le=365)
    break_date: date | None = None
    ext_refs: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = Field(default=None, max_length=5000)


class LeaseUpdate(BaseModel):
    """Partial update; money and dates only change while the lease is a draft."""

    model_config = ConfigDict(str_strip_whitespace=True)

    code: str | None = Field(default=None, min_length=1, max_length=50)
    unit_kind: UnitKind | None = None
    unit_ref: str | None = Field(default=None, min_length=1, max_length=64)
    unit_label: str | None = Field(default=None, max_length=255)
    tenant_contact_id: str | None = Field(default=None, min_length=1, max_length=36)
    landlord_legal_entity_id: uuid.UUID | None = None
    start_date: date | None = None
    end_date: date | None = None
    rent_amount: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    frequency: Frequency | None = None
    deposit: Decimal | None = Field(default=None, max_digits=18, decimal_places=2)
    escalation_kind: EscalationKind | None = None
    escalation_rate: Decimal | None = Field(default=None, ge=-100, le=100, max_digits=9, decimal_places=4)
    escalation_index: str | None = Field(default=None, max_length=100)
    escalation_every_months: int | None = Field(default=None, ge=1, le=120)
    tax_code: str | None = Field(default=None, max_length=30)
    tax_rate: Decimal | None = Field(default=None, ge=0, le=100, max_digits=7, decimal_places=4)
    payment_terms_days: int | None = Field(default=None, ge=0, le=365)
    break_date: date | None = None
    ext_refs: dict[str, Any] | None = None
    notes: str | None = Field(default=None, max_length=5000)


class LeaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    code: str
    unit_kind: str
    unit_ref: str
    unit_label: str
    tenant_contact_id: str
    landlord_legal_entity_id: uuid.UUID | None
    start_date: date
    end_date: date
    term_months: int
    rent_amount: Decimal
    currency: str
    frequency: str
    deposit: Decimal
    escalation_kind: str
    escalation_rate: Decimal | None
    escalation_index: str | None
    escalation_every_months: int
    tax_code: str | None
    tax_rate: Decimal
    payment_terms_days: int
    status: str
    break_date: date | None
    notice_date: date | None
    ended_on: date | None
    renewed_from_id: uuid.UUID | None
    document_ids: list[str] = Field(default_factory=list)
    ext_refs: dict[str, Any] = Field(default_factory=dict)
    notes: str | None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_serializer("rent_amount", "deposit", "escalation_rate", "tax_rate")
    def _ser(self, value: Decimal | None) -> str | None:
        return _s(value)


class LeaseListResponse(BaseModel):
    items: list[LeaseResponse]
    total: int


class ScheduleLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    lease_id: uuid.UUID
    seq: int
    period_start: date
    period_end: date
    due_date: date
    amount: Decimal
    tax_code: str | None
    tax_amount: Decimal
    review_number: int
    invoice_id: uuid.UUID | None

    @field_serializer("amount", "tax_amount")
    def _ser(self, value: Decimal) -> str | None:
        return _s(value)


class ScheduleResponse(BaseModel):
    lease_id: uuid.UUID
    currency: str
    total: str
    items: list[ScheduleLineResponse]


class ScheduleRunRequest(BaseModel):
    project_id: uuid.UUID
    as_of: date | None = None
    lease_id: uuid.UUID | None = None


class ScheduleRunResponse(BaseModel):
    as_of: date
    invoices_created: int
    invoice_ids: list[str]
    skipped: int


class EventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    lease_id: uuid.UUID
    kind: str
    event_date: date
    payload: dict[str, Any]
    actor_id: str | None
    created_at: datetime | None = None


class ActivateRequest(BaseModel):
    on: date | None = None


class TerminateRequest(BaseModel):
    """Give notice (``effective`` in the future) or end the lease now."""

    effective: date
    notice_given_on: date | None = None
    reason: str | None = Field(default=None, max_length=1000)


class RenewRequest(BaseModel):
    """A renewal is a new draft lease that follows on from this one."""

    end_date: date
    rent_amount: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    code: str | None = Field(default=None, max_length=50)


class ReviewRequest(BaseModel):
    """Record the rate of one rent review, e.g. the index movement."""

    review_number: int = Field(..., ge=1, le=200)
    rate: Decimal = Field(..., ge=-100, le=100, max_digits=9, decimal_places=4)
    event_date: date | None = None
    note: str | None = Field(default=None, max_length=1000)


class DocumentLinkRequest(BaseModel):
    document_id: uuid.UUID


class LeaseDocument(BaseModel):
    id: str
    name: str
    category: str


class LeaseDetailResponse(BaseModel):
    lease: LeaseResponse
    events: list[EventResponse]
    documents: list[LeaseDocument]


class RentRollRow(BaseModel):
    lease_id: str
    code: str
    unit_kind: str
    unit_ref: str
    unit_label: str
    tenant_contact_id: str
    tenant_name: str = ""
    status: str
    start_date: date
    end_date: date
    currency: str
    frequency: str
    current_rent: str
    annual_rent: str
    deposit: str
    next_due_date: date | None
    break_date: date | None


class RentRollResponse(BaseModel):
    as_of: date
    items: list[RentRollRow]
    totals: dict[str, str]


class ArrearsRow(BaseModel):
    lease_id: str
    code: str
    unit_label: str
    tenant_contact_id: str
    tenant_name: str = ""
    currency: str
    invoice_id: str
    invoice_number: str
    due_date: str | None
    days_past_due: int
    bucket: str
    total: str
    paid: str
    due: str


class ArrearsResponse(BaseModel):
    as_of: date
    items: list[ArrearsRow]
    totals: dict[str, dict[str, str]]


class ValidationIssue(BaseModel):
    rule_id: str
    severity: str
    message: str
    element_ref: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ValidationResponse(BaseModel):
    status: str
    checked: int
    results: list[ValidationIssue]
