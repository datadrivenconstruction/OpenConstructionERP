# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Request and response schemas for legal entities and branches.

Codes are normalised here (trimmed, upper-cased) and checked for shape in
:mod:`app.modules.legal_entities.validators`, so the API and the service apply
one set of rules.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _upper(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip().upper()
    return cleaned or None


class EntityAddress(BaseModel):
    """A registered address; the country is the entity's own."""

    line1: str = Field(default="", max_length=200)
    line2: str = Field(default="", max_length=200)
    postcode: str = Field(default="", max_length=20)
    city: str = Field(default="", max_length=100)


class EntityBank(BaseModel):
    """The bank account a company prints on its documents."""

    holder: str = Field(default="", max_length=200)
    iban: str = Field(default="", max_length=64)
    bic: str = Field(default="", max_length=20)
    bank_name: str = Field(default="", max_length=200)


class TaxIdValue(BaseModel):
    """One tax identifier, e.g. ``{"scheme": "vat", "value": "DE123456789"}``."""

    scheme: str = Field(..., min_length=1, max_length=32)
    value: str = Field(default="", max_length=100)


class _CodesMixin(BaseModel):
    @field_validator("country_code", "subdivision_code", check_fields=False, mode="after")
    @classmethod
    def _norm_geo(cls, v: str | None) -> str | None:
        return _upper(v)


class LegalEntityCreate(_CodesMixin):
    code: str = Field(..., min_length=1, max_length=32)
    name: str = Field(..., min_length=1, max_length=255)
    country_code: str = Field(..., min_length=2, max_length=2)
    subdivision_code: str | None = Field(default=None, max_length=6)
    functional_currency: str = Field(..., min_length=3, max_length=3)
    registration_number: str | None = Field(default=None, max_length=100)
    tax_id: str | None = Field(default=None, max_length=100)
    legal_name: str | None = Field(default=None, max_length=255)
    address: EntityAddress | None = None
    tax_ids: list[TaxIdValue] = Field(default_factory=list, max_length=10)
    invoice_prefix: str | None = Field(default=None, max_length=32)
    default_signatory: str | None = Field(default=None, max_length=255)
    bank: EntityBank | None = None
    is_default: bool = False
    is_active: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("functional_currency", mode="after")
    @classmethod
    def _norm_currency(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("code", "name", mode="after")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


class LegalEntityUpdate(_CodesMixin):
    code: str | None = Field(default=None, min_length=1, max_length=32)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    subdivision_code: str | None = Field(default=None, max_length=6)
    functional_currency: str | None = Field(default=None, min_length=3, max_length=3)
    registration_number: str | None = Field(default=None, max_length=100)
    tax_id: str | None = Field(default=None, max_length=100)
    legal_name: str | None = Field(default=None, max_length=255)
    address: EntityAddress | None = None
    tax_ids: list[TaxIdValue] | None = Field(default=None, max_length=10)
    invoice_prefix: str | None = Field(default=None, max_length=32)
    default_signatory: str | None = Field(default=None, max_length=255)
    bank: EntityBank | None = None
    is_default: bool | None = None
    is_active: bool | None = None
    metadata: dict[str, Any] | None = None

    @field_validator("functional_currency", mode="after")
    @classmethod
    def _norm_currency(cls, v: str | None) -> str | None:
        return _upper(v)


class BranchCreate(_CodesMixin):
    code: str = Field(..., min_length=1, max_length=32)
    name: str = Field(..., min_length=1, max_length=255)
    #: Defaults to the entity's country when left out.
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    subdivision_code: str | None = Field(default=None, max_length=6)
    address: EntityAddress | None = None
    is_active: bool = True


class BranchUpdate(_CodesMixin):
    code: str | None = Field(default=None, min_length=1, max_length=32)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    subdivision_code: str | None = Field(default=None, max_length=6)
    address: EntityAddress | None = None
    is_active: bool | None = None


class IssueResponse(BaseModel):
    rule_id: str
    severity: str
    field: str
    message: str


class BranchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    legal_entity_id: UUID
    code: str
    name: str
    country_code: str
    subdivision_code: str | None
    address: dict[str, Any] | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    #: Warnings the write produced, e.g. a branch abroad. Empty on reads.
    warnings: list[IssueResponse] = Field(default_factory=list)


class LegalEntityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    code: str
    name: str
    country_code: str
    subdivision_code: str | None
    functional_currency: str
    registration_number: str | None
    tax_id: str | None
    legal_name: str | None = None
    address: dict[str, Any] | None = None
    tax_ids: list[dict[str, Any]] = Field(default_factory=list)
    invoice_prefix: str | None = None
    default_signatory: str | None = None
    bank: dict[str, Any] | None = None
    is_default: bool
    is_active: bool
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")
    branches: list[BranchResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    #: The identifier the table shows: the country's first scheme that has a value.
    primary_tax_id: str = ""
    project_count: int = 0
    member_count: int = 0
    #: Whether the entity has its own e-invoice seller details or uses the group defaults.
    has_own_einvoice_settings: bool = False
    warnings: list[IssueResponse] = Field(default_factory=list)

    @field_validator("tax_ids", mode="before")
    @classmethod
    def _none_list(cls, v: Any) -> Any:
        return v or []


class LegalEntityListResponse(BaseModel):
    items: list[LegalEntityResponse]
    total: int


class ProjectEntityAssign(BaseModel):
    """Name the entity that owns a project; null clears it back to the default."""

    legal_entity_id: UUID | None = None
    #: The site of that entity the project runs from; must belong to it.
    legal_entity_branch_id: UUID | None = None


class ProjectEntityResponse(BaseModel):
    """The entity a project's documents belong to, and why.

    ``source`` is ``assigned`` when the project names the entity, ``default``
    when it names none and the default entity answers, and ``none`` when there
    is neither, so a caller never mistakes the fallback for a choice.
    """

    project_id: UUID
    legal_entity: LegalEntityResponse | None
    source: Literal["assigned", "default", "none"]
    legal_entity_branch_id: UUID | None = None
    #: Outgoing invoices past draft on the project; moving it to another company leaves them behind.
    issued_invoice_count: int = 0
    warnings: list[IssueResponse] = Field(default_factory=list)


class TaxSchemeResponse(BaseModel):
    scheme: str
    pattern: str | None
    example: str
    mandatory_on_invoice: bool
    legal_reference: str = ""


class TaxSchemesResponse(BaseModel):
    country_code: str
    schemes: list[TaxSchemeResponse]


class MemberCreate(BaseModel):
    user_id: UUID
    role: Literal["viewer", "member", "admin"] = "member"


class MemberUpdate(BaseModel):
    role: Literal["viewer", "member", "admin"]


class MemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    legal_entity_id: UUID
    user_id: UUID
    role: str
    email: str = ""
    full_name: str = ""


class MemberListResponse(BaseModel):
    items: list[MemberResponse]
    #: Whether any entity of the install has a member yet; the first one changes what people see.
    any_members: bool


class SellerResponse(BaseModel):
    """The seller block a project's documents print, and where it came from."""

    project_id: UUID
    source: Literal["entity_settings", "entity", "default", "company_profile", "none"]
    legal_entity_id: UUID | None = None
    legal_entity_code: str | None = None
    seller: dict[str, Any]
    complete: bool
    missing: list[str]
    issues: list[IssueResponse] = Field(default_factory=list)


class UiStateResponse(BaseModel):
    """What the screens need to decide whether to show company pickers at all."""

    active_entity_count: int
    multi_company: bool
    my_entity_ids: list[UUID]
    default_entity_id: UUID | None
