"""Customer offer request and response schemas.

Money is a decimal string on every field, in and out.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.offers.pricing import LINE_ROLES, MARKUP_PRESENTATIONS, TAX_MODES

TextKind = Literal["intro", "payment_terms", "validity", "conditions", "warranty", "closing", "legal_notice"]
Status = Literal["draft", "sent", "accepted", "declined", "expired", "superseded"]
_DECIMAL = r"^-?\d{1,15}(\.\d{1,6})?$"


class InstalmentIn(BaseModel):
    """A draft instalment shaped like a contract milestone."""

    code: str = Field(default="", max_length=40)
    name: str = Field(default="", max_length=200)
    kind: Literal["deposit", "progress", "final"] = "progress"
    percent: str | None = Field(default=None, pattern=_DECIMAL)
    value: str | None = Field(default=None, pattern=_DECIMAL)
    due: dict[str, Any] = Field(default_factory=lambda: {"type": "signing"})
    lag_days: int = Field(default=0, ge=0, le=3650)
    payment_terms_days: int | None = Field(default=None, ge=0, le=365)


class TextEntryIn(BaseModel):
    source: Literal["company", "project", "offer"] = "offer"
    body: str = Field(default="", max_length=8000)
    block_id: uuid.UUID | None = None


class OfferCreate(BaseModel):
    project_id: uuid.UUID
    boq_id: uuid.UUID
    contact_id: uuid.UUID | None = None
    locale: str | None = Field(default=None, max_length=10)


class OfferUpdate(BaseModel):
    """Every field optional: a PATCH changes what it names."""

    contact_id: uuid.UUID | None = None
    customer_kind: Literal["private", "business"] | None = None
    number: str | None = Field(default=None, min_length=1, max_length=60)
    issue_date: date | None = None
    validity_days: int | None = Field(default=None, ge=1, le=3650)
    valid_until: date | None = None
    payment_days: int | None = Field(default=None, ge=0, le=365)
    reference: str | None = Field(default=None, max_length=120)
    contact_person: dict[str, str] | None = None
    licence_number: str | None = Field(default=None, max_length=60)
    locale: str | None = Field(default=None, max_length=10)
    title: str | None = Field(default=None, max_length=120)
    tax_mode: str | None = None
    tax_rate: str | None = Field(default=None, pattern=r"^\d{1,3}(\.\d{1,4})?$")
    markup_presentation: str | None = None
    site_same_as_billing: bool | None = None
    options: dict[str, Any] | None = None
    texts: dict[str, TextEntryIn] | None = None
    instalments: list[InstalmentIn] | None = None
    retention_percent: str | None = Field(default=None, pattern=r"^\d{1,3}(\.\d{1,4})?$")
    advance_security: bool | None = None

    @field_validator("tax_mode")
    @classmethod
    def _mode(cls, v: str | None) -> str | None:
        if v is not None and v not in TAX_MODES:
            raise ValueError("unknown tax mode")
        return v

    @field_validator("markup_presentation")
    @classmethod
    def _presentation(cls, v: str | None) -> str | None:
        if v is not None and v not in MARKUP_PRESENTATIONS:
            raise ValueError("unknown markup presentation")
        return v


class OfferResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    boq_id: uuid.UUID | None
    group_id: uuid.UUID
    number: str
    revision: str
    status: Status
    contact_id: uuid.UUID | None
    customer_kind: str
    customer: dict[str, Any]
    site_address: dict[str, Any]
    site_same_as_billing: bool
    pack_key: str | None
    locale: str
    title: str
    currency: str
    tax_mode: str
    tax_rate: str
    tax_label: str
    issue_date: date
    validity_days: int | None
    valid_until: date | None
    payment_days: int | None
    reference: str
    contact_person: dict[str, Any]
    licence_number: str
    markup_presentation: str
    options: dict[str, Any]
    lines: list[dict[str, Any]]
    totals: dict[str, Any]
    estimate_net: str
    texts: dict[str, Any]
    instalments: list[dict[str, Any]]
    schedule: list[dict[str, Any]]
    retention_percent: str
    advance_security: bool
    sent_at: datetime | None
    decided_at: datetime | None
    accepted_options: list[str]
    contract_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    stale: bool = False
    editable: bool = True


class OfferSummary(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    boq_id: uuid.UUID | None
    number: str
    revision: str
    status: Status
    customer_name: str
    currency: str
    gross: str
    valid_until: date | None
    issue_date: date


class OffersListResponse(BaseModel):
    items: list[OfferSummary]
    total: int
    offset: int = 0
    limit: int = 50


class FindingOut(BaseModel):
    rule_id: str
    severity: Literal["error", "warning", "info"]
    message: str
    element_ref: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    section: Literal["customer", "details", "items", "schedule", "texts", "layout"]


class ValidationOut(BaseModel):
    findings: list[FindingOut]
    errors: int
    warnings: int
    can_send: bool
    first_error: str | None = None


class SendRequest(BaseModel):
    via: Literal["download", "email"] = "download"


class AcceptRequest(BaseModel):
    accepted_on: date | None = None
    optional_ordinals: list[str] = Field(default_factory=list)
    create_contract: bool = True


class AcceptResponse(BaseModel):
    offer: OfferResponse
    contract_id: uuid.UUID | None = None
    milestones: int = 0
    contract_blocked: str | None = None


class PreviewResponse(BaseModel):
    pdf_base64: str
    page_count: int
    filename: str


class ContextResponse(BaseModel):
    """Everything the page needs before an offer exists."""

    project_id: uuid.UUID
    boq_id: uuid.UUID
    pack: dict[str, Any]
    locale: str
    currency: str
    client_contact_id: uuid.UUID | None
    default_validity_days: int
    default_payment_days: int | None
    next_number: str
    document_languages: list[str]
    offers: list[OfferSummary]
    permissions: dict[str, bool] = Field(default_factory=dict)


class ScheduleTemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    rows: list[InstalmentIn]


class SettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    number_pattern: str
    validity_days: int | None
    payment_days: int | None
    markup_presentation: str
    schedule_templates: list[dict[str, Any]]
    default_schedule: str
    next_number: str = ""


class SettingsUpdate(BaseModel):
    number_pattern: str | None = Field(default=None, min_length=3, max_length=60)
    validity_days: int | None = Field(default=None, ge=1, le=3650)
    payment_days: int | None = Field(default=None, ge=0, le=365)
    markup_presentation: str | None = None
    schedule_templates: list[ScheduleTemplateIn] | None = None
    default_schedule: str | None = Field(default=None, max_length=40)

    @field_validator("number_pattern")
    @classmethod
    def _needs_sequence(cls, v: str | None) -> str | None:
        if v is not None and "{seq" not in v:
            raise ValueError("the pattern needs a {seq} part")
        return v

    @field_validator("markup_presentation")
    @classmethod
    def _presentation(cls, v: str | None) -> str | None:
        if v is not None and v not in MARKUP_PRESENTATIONS:
            raise ValueError("unknown markup presentation")
        return v


class TextBlockIn(BaseModel):
    kind: TextKind
    name: str = Field(default="", max_length=120)
    language: str = Field(default="en", max_length=10)
    body: str = Field(default="", max_length=8000)
    scope: Literal["company", "project"] = "company"
    project_id: uuid.UUID | None = None
    is_default: bool = False


class TextBlockOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    scope: str
    project_id: uuid.UUID | None
    kind: str
    name: str
    language: str
    body: str
    is_default: bool
    pack_key: str | None


class TextBlocksListResponse(BaseModel):
    items: list[TextBlockOut]
    total: int
    offset: int = 0
    limit: int = 200


class PositionRoleIn(BaseModel):
    role: str
    alternative_of: str | None = Field(default=None, max_length=50)
    by_others: bool | None = None

    @field_validator("role")
    @classmethod
    def _role(cls, v: str) -> str:
        if v not in LINE_ROLES:
            raise ValueError("unknown line role")
        return v


class NumberCheck(BaseModel):
    number: str
    taken: bool
