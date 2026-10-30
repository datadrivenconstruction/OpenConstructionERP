# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Service charges request and response schemas. Money travels as decimal strings."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

Money = Annotated[Decimal, PlainSerializer(lambda v: format(v, "f"), return_type=str)]
KeyMethod = Literal["area", "permille", "equal", "custom"]
Frequency = Literal["annual", "semiannual", "quarterly", "monthly"]


# ── Associations ─────────────────────────────────────────────────────────


class AssociationCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: uuid.UUID
    name: str = Field(..., min_length=1, max_length=255)
    legal_entity_id: uuid.UUID | None = None
    registration: dict[str, Any] = Field(default_factory=dict)
    currency: str = Field(..., pattern=r"^[A-Z]{3}$")
    fiscal_year_start_month: int = Field(default=1, ge=1, le=12)
    notes: str | None = Field(default=None, max_length=5000)


class AssociationUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    legal_entity_id: uuid.UUID | None = None
    registration: dict[str, Any] | None = None
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    fiscal_year_start_month: int | None = Field(default=None, ge=1, le=12)
    notes: str | None = Field(default=None, max_length=5000)


class AssociationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    legal_entity_id: uuid.UUID | None = None
    registration: dict[str, Any] = Field(default_factory=dict)
    currency: str
    fiscal_year_start_month: int
    notes: str | None = None
    created_at: datetime | None = None


class AssociationListResponse(BaseModel):
    items: list[AssociationResponse]
    total: int


# ── Keys ─────────────────────────────────────────────────────────────────


class KeyLineIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    unit_ref: str = Field(..., min_length=1, max_length=64)
    unit_label: str = Field(default="", max_length=255)
    share: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=6)
    payer_contact_id: str | None = Field(default=None, max_length=36)


class KeyCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=120)
    method: KeyMethod = "permille"
    lines: list[KeyLineIn] = Field(..., min_length=1, max_length=5000)


class KeyUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=120)
    method: KeyMethod | None = None
    lines: list[KeyLineIn] | None = Field(default=None, min_length=1, max_length=5000)


class KeyLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    unit_ref: str
    unit_label: str
    share: Money
    payer_contact_id: str | None = None


class KeyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    association_id: uuid.UUID
    name: str
    method: str
    lines: list[KeyLineResponse]


# ── Budgets ──────────────────────────────────────────────────────────────


class BudgetLineIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    category: str = Field(..., min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    amount: Decimal = Field(..., ge=0, max_digits=18, decimal_places=2)
    key_id: uuid.UUID


class BudgetLineUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    category: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    amount: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    key_id: uuid.UUID | None = None


class BudgetCreate(BaseModel):
    year: int = Field(..., ge=1900, le=2200)
    demand_frequency: Frequency = "quarterly"
    default_key_id: uuid.UUID | None = None
    notes: str | None = Field(default=None, max_length=5000)
    lines: list[BudgetLineIn] = Field(default_factory=list, max_length=500)


class BudgetUpdate(BaseModel):
    demand_frequency: Frequency | None = None
    default_key_id: uuid.UUID | None = None
    notes: str | None = Field(default=None, max_length=5000)


class BudgetLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    category: str
    description: str
    amount: Money
    key_id: uuid.UUID


class BudgetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    association_id: uuid.UUID
    year: int
    status: str
    demand_frequency: str
    default_key_id: uuid.UUID | None = None
    approved_at: datetime | None = None
    approved_by: str | None = None
    notes: str | None = None
    lines: list[BudgetLineResponse]
    total: Money = Decimal("0")


class UnitChargeResponse(BaseModel):
    unit_ref: str
    yearly: Money
    per_period: list[Money]


class BudgetUnitsResponse(BaseModel):
    budget_id: uuid.UUID
    currency: str
    periods: int
    units: list[UnitChargeResponse]


# ── Demands ──────────────────────────────────────────────────────────────


class DemandRunRequest(BaseModel):
    budget_id: uuid.UUID
    period: int = Field(..., ge=1, le=12)
    issue_date: date | None = None
    payment_terms_days: int = Field(default=30, ge=0, le=365)


class DemandResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    budget_id: uuid.UUID
    unit_ref: str
    period: int
    issue_date: date
    amount: Money
    currency: str
    payer_contact_id: str | None = None
    invoice_id: uuid.UUID | None = None


class DemandRunResponse(BaseModel):
    period: int
    created: int
    skipped: int
    invoice_ids: list[str]


# ── Reconciliation ───────────────────────────────────────────────────────


class ReconciliationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    budget_id: uuid.UUID
    status: str
    actual_by_category: dict[str, str]
    unit_balances: list[dict[str, Any]]
    unallocated: dict[str, str]
    sources: list[dict[str, Any]]
    total_actual: Money
    total_demanded: Money
    posted_invoice_ids: list[str]
    posted_credit_ids: list[str]
    posted_at: datetime | None = None


class ValidationResponse(BaseModel):
    status: str
    checked: int
    results: list[dict[str, Any]]
