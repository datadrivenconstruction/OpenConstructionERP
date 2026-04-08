"""Contacts Pydantic schemas — request/response models."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ── Create / Update ──────────────────────────────────────────────────────


class ContactCreate(BaseModel):
    """Create a new contact."""

    model_config = ConfigDict(str_strip_whitespace=True)

    contact_type: str = Field(
        ...,
        pattern=r"^(client|subcontractor|supplier|consultant|internal)$",
        examples=["subcontractor"],
    )
    is_platform_user: bool = False
    user_id: UUID | None = None

    first_name: str | None = Field(default=None, max_length=255, examples=["Max"])
    last_name: str | None = Field(default=None, max_length=255, examples=["Mustermann"])
    company_name: str | None = Field(
        default=None, max_length=255, examples=["Acme Construction GmbH"]
    )
    legal_name: str | None = Field(default=None, max_length=255)
    vat_number: str | None = Field(default=None, max_length=50, examples=["DE123456789"])

    country_code: str | None = Field(default=None, max_length=2, examples=["DE"])
    address: dict[str, Any] | None = None

    primary_email: str | None = Field(
        default=None, max_length=255, examples=["info@acme-construction.de"]
    )
    primary_phone: str | None = Field(
        default=None, max_length=50, examples=["+49 170 1234567"]
    )
    website: str | None = Field(default=None, max_length=500)

    @field_validator("primary_email")
    @classmethod
    def validate_email_format(cls, v: str | None) -> str | None:
        """Validate email has a basic valid format."""
        if v is not None:
            import re

            if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v):
                raise ValueError(f"Invalid email format: {v}")
        return v

    certifications: list[Any] = Field(default_factory=list)
    insurance: list[Any] = Field(default_factory=list)
    prequalification_status: str | None = Field(
        default=None,
        pattern=r"^(pending|approved|rejected|expired)$",
    )
    qualified_until: str | None = Field(default=None, max_length=20)

    payment_terms_days: str | None = Field(default=None, max_length=10)
    currency_code: str | None = Field(default=None, max_length=10)

    name_translations: dict[str, Any] | None = None
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContactUpdate(BaseModel):
    """Partial update for a contact."""

    model_config = ConfigDict(str_strip_whitespace=True)

    contact_type: str | None = Field(
        default=None,
        pattern=r"^(client|subcontractor|supplier|consultant|internal)$",
    )
    is_platform_user: bool | None = None
    user_id: UUID | None = None

    first_name: str | None = Field(default=None, max_length=255)
    last_name: str | None = Field(default=None, max_length=255)
    company_name: str | None = Field(default=None, max_length=255)
    legal_name: str | None = Field(default=None, max_length=255)
    vat_number: str | None = Field(default=None, max_length=50)

    country_code: str | None = Field(default=None, max_length=2)
    address: dict[str, Any] | None = None

    primary_email: str | None = Field(default=None, max_length=255)
    primary_phone: str | None = Field(default=None, max_length=50)
    website: str | None = Field(default=None, max_length=500)

    @field_validator("primary_email")
    @classmethod
    def validate_email_format(cls, v: str | None) -> str | None:
        """Validate email has a basic valid format."""
        if v is not None:
            import re

            if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v):
                raise ValueError(f"Invalid email format: {v}")
        return v

    certifications: list[Any] | None = None
    insurance: list[Any] | None = None
    prequalification_status: str | None = Field(
        default=None,
        pattern=r"^(pending|approved|rejected|expired)$",
    )
    qualified_until: str | None = Field(default=None, max_length=20)

    payment_terms_days: str | None = Field(default=None, max_length=10)
    currency_code: str | None = Field(default=None, max_length=10)

    name_translations: dict[str, Any] | None = None
    notes: str | None = None
    metadata: dict[str, Any] | None = None


# ── Response ─────────────────────────────────────────────────────────────


class ContactResponse(BaseModel):
    """Contact returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    contact_type: str
    is_platform_user: bool = False
    user_id: UUID | None = None

    first_name: str | None = None
    last_name: str | None = None
    company_name: str | None = None
    legal_name: str | None = None
    vat_number: str | None = None

    country_code: str | None = None
    address: dict[str, Any] | None = None

    primary_email: str | None = None
    primary_phone: str | None = None
    website: str | None = None

    certifications: list[Any] = Field(default_factory=list)
    insurance: list[Any] = Field(default_factory=list)
    prequalification_status: str | None = None
    qualified_until: str | None = None

    payment_terms_days: str | None = None
    currency_code: str | None = None

    name_translations: dict[str, Any] | None = None
    notes: str | None = None
    is_active: bool = True
    created_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")

    created_at: datetime
    updated_at: datetime


class ContactListResponse(BaseModel):
    """Paginated list of contacts."""

    items: list[ContactResponse]
    total: int
    offset: int
    limit: int


# ── Stats ────────────────────────────────────────────────────────────────


class ContactStatsResponse(BaseModel):
    """Aggregate statistics for contacts."""

    total: int = 0
    by_type: dict[str, int] = Field(default_factory=dict)
    by_country_top10: dict[str, int] = Field(default_factory=dict)
    with_expiring_prequalification: int = 0
