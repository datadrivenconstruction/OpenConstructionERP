# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""‌⁠‍Pydantic schemas for the compliance documents tracker."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ── Canonical enumerations (also enforced by the regex below) ──────────

DOC_TYPES: tuple[str, ...] = (
    "insurance_general_liability",
    "insurance_workers_comp",
    "insurance_auto",
    "insurance_umbrella",
    "permit_building",
    "permit_electrical",
    "permit_plumbing",
    "permit_other",
    "bond_payment",
    "bond_performance",
    "bond_bid",
    "certification_safety",
    "certification_other",
    "other",
)

STATUSES: tuple[str, ...] = (
    "active",
    "expiring_soon",
    "expired",
    "cancelled",
    "void",
)

_DOC_TYPE_PATTERN = "^(" + "|".join(DOC_TYPES) + ")$"
_STATUS_PATTERN = "^(" + "|".join(STATUSES) + ")$"
_DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"


# ── Create ─────────────────────────────────────────────────────────────


class ComplianceDocCreate(BaseModel):
    """‌⁠‍Body for ``POST /v1/compliance_docs/``."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    doc_type: str = Field(..., pattern=_DOC_TYPE_PATTERN)
    name: str = Field(..., min_length=1, max_length=255)
    issuer: str | None = Field(default=None, max_length=255)
    policy_number: str | None = Field(default=None, max_length=100)
    coverage_amount: Decimal | None = Field(default=None, ge=0)
    currency: str = Field(default="", max_length=3)
    effective_date: date
    expires_at: date
    notify_days_before: int = Field(default=30, ge=0, le=365)
    status: str | None = Field(
        default=None,
        pattern=_STATUS_PATTERN,
        description=(
            "Optional explicit status override. When omitted (the common "
            "case) the service derives it from the date window."
        ),
    )
    attachment_document_id: UUID | None = None
    notes: str = Field(default="", max_length=10000)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("currency", mode="after")
    @classmethod
    def _upper_currency(cls, v: str) -> str:
        # Normalise to upper-case so ``EUR`` / ``eur`` are equivalent
        # but allow empty (the project-default sentinel).
        return v.upper() if v else v


# ── Update ─────────────────────────────────────────────────────────────


class ComplianceDocUpdate(BaseModel):
    """‌⁠‍Body for ``PATCH /v1/compliance_docs/{id}``."""

    model_config = ConfigDict(str_strip_whitespace=True)

    doc_type: str | None = Field(default=None, pattern=_DOC_TYPE_PATTERN)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    issuer: str | None = Field(default=None, max_length=255)
    policy_number: str | None = Field(default=None, max_length=100)
    coverage_amount: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=3)
    effective_date: date | None = None
    expires_at: date | None = None
    notify_days_before: int | None = Field(default=None, ge=0, le=365)
    status: str | None = Field(default=None, pattern=_STATUS_PATTERN)
    attachment_document_id: UUID | None = None
    notes: str | None = Field(default=None, max_length=10000)
    metadata: dict[str, Any] | None = None

    @field_validator("currency", mode="after")
    @classmethod
    def _upper_currency(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return v.upper() if v else v


# ── Response ───────────────────────────────────────────────────────────


class ComplianceDocResponse(BaseModel):
    """Compliance doc returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    doc_type: str
    name: str
    issuer: str | None = None
    policy_number: str | None = None
    coverage_amount: Decimal | None = None
    currency: str = ""
    effective_date: date
    expires_at: date
    notify_days_before: int = 30
    status: str = "active"
    attachment_document_id: UUID | None = None
    notes: str = ""
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias="metadata_",
    )
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime

    # Computed convenience field
    days_until_expiry: int = Field(
        default=0,
        description=("Signed integer — negative when already expired, 0 on expiry day, positive when still valid."),
    )


__all__ = [
    "DOC_TYPES",
    "STATUSES",
    "ComplianceDocCreate",
    "ComplianceDocResponse",
    "ComplianceDocUpdate",
]
