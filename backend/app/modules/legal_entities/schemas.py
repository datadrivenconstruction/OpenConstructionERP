# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Request and response schemas for legal entities and branches.

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
    is_active: bool = True


class BranchUpdate(_CodesMixin):
    code: str | None = Field(default=None, min_length=1, max_length=32)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    subdivision_code: str | None = Field(default=None, max_length=6)
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
    is_default: bool
    is_active: bool
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")
    branches: list[BranchResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class LegalEntityListResponse(BaseModel):
    items: list[LegalEntityResponse]
    total: int


class ProjectEntityAssign(BaseModel):
    """Name the entity that owns a project; null clears it back to the default."""

    legal_entity_id: UUID | None = None


class ProjectEntityResponse(BaseModel):
    """The entity a project's documents belong to, and why.

    ``source`` is ``assigned`` when the project names the entity, ``default``
    when it names none and the default entity answers, and ``none`` when there
    is neither, so a caller never mistakes the fallback for a choice.
    """

    project_id: UUID
    legal_entity: LegalEntityResponse | None
    source: Literal["assigned", "default", "none"]
