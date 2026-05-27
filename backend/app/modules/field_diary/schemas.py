# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Pydantic v2 schemas for the Field Diary module."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ── Constants ─────────────────────────────────────────────────────────────

DIARY_STATUSES = ("draft", "submitted", "approved")
ACTIVITY_TYPES = ("work", "delay", "inspection", "visit", "incident")
MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024  # 25 MB

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_E164_PHONE = re.compile(r"^\+?[1-9]\d{6,14}$")

# ``metadata_`` is the ORM column name (the trailing underscore avoids
# colliding with SQLAlchemy's class-level ``Base.metadata`` registry).
# The wire field name stays plain ``metadata``; ``populate_by_name=True``
# lets us accept either ``metadata`` (from JSON) or ``metadata_`` (from
# the ORM via ``from_attributes``).
_RESPONSE_CONFIG = ConfigDict(from_attributes=True, populate_by_name=True)


# ── Diary entry ───────────────────────────────────────────────────────────


class DiaryEntryCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    project_id: uuid.UUID
    entry_date: str = Field(..., description="ISO YYYY-MM-DD")
    weather: str | None = Field(default=None, max_length=64)
    temperature_c: Decimal | None = None
    headcount: int = Field(default=0, ge=0, le=10_000)
    notes_md: str | None = Field(default=None, max_length=20_000)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("entry_date")
    @classmethod
    def _validate_date(cls, v: str) -> str:
        if not _ISO_DATE.match(v):
            raise ValueError("entry_date must be ISO YYYY-MM-DD")
        return v


class DiaryEntryUpdate(BaseModel):
    weather: str | None = Field(default=None, max_length=64)
    temperature_c: Decimal | None = None
    headcount: int | None = Field(default=None, ge=0, le=10_000)
    notes_md: str | None = Field(default=None, max_length=20_000)
    metadata: dict[str, Any] | None = None


class DiaryEntryResponse(BaseModel):
    model_config = _RESPONSE_CONFIG

    id: uuid.UUID
    project_id: uuid.UUID
    author_id: uuid.UUID
    entry_date: str
    weather: str | None = None
    temperature_c: Decimal | None = None
    headcount: int = 0
    notes_md: str | None = None
    status: str
    submitted_at: datetime | None = None
    approved_at: datetime | None = None
    approved_by: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
    # Read from the ORM column ``metadata_`` via alias; serialise out as
    # ``metadata`` for API consumers (matches the create / update wire
    # name).
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        alias="metadata_",
    )


# ── Diary activity ────────────────────────────────────────────────────────


class DiaryActivityCreate(BaseModel):
    activity_type: Literal["work", "delay", "inspection", "visit", "incident"]
    description: str | None = Field(default=None, max_length=10_000)
    hours: Decimal | None = Field(default=None, ge=0, le=24)
    location: str | None = Field(default=None, max_length=255)
    started_at: datetime | None = None
    ended_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DiaryActivityResponse(BaseModel):
    model_config = _RESPONSE_CONFIG

    id: uuid.UUID
    entry_id: uuid.UUID
    activity_type: str
    description: str | None = None
    hours: Decimal | None = None
    location: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        alias="metadata_",
    )
    created_at: datetime
    updated_at: datetime


# ── Diary attachment ──────────────────────────────────────────────────────


class DiaryAttachmentResponse(BaseModel):
    model_config = _RESPONSE_CONFIG

    id: uuid.UUID
    entry_id: uuid.UUID
    filename: str
    mime_type: str
    size_bytes: int
    storage_key: str
    uploaded_by: uuid.UUID | None = None
    created_at: datetime


# ── Field module grant ────────────────────────────────────────────────────


class FieldModuleGrantCreate(BaseModel):
    user_id: uuid.UUID
    project_id: uuid.UUID
    module_key: str = Field(default="field_diary", max_length=64)
    expires_at: datetime | None = None


class FieldModuleGrantResponse(BaseModel):
    model_config = _RESPONSE_CONFIG

    id: uuid.UUID
    user_id: uuid.UUID
    project_id: uuid.UUID
    module_key: str
    granted_by: uuid.UUID | None = None
    granted_at: datetime
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


# ── Magic-link auth ───────────────────────────────────────────────────────


class FieldMagicLinkRequest(BaseModel):
    phone: str = Field(..., description="E.164 phone number")
    project_id: uuid.UUID
    module_key: str = Field(default="field_diary", max_length=64)

    @field_validator("phone")
    @classmethod
    def _validate_phone(cls, v: str) -> str:
        cleaned = v.strip().replace(" ", "").replace("-", "")
        if not _E164_PHONE.match(cleaned):
            raise ValueError("phone must be E.164 format (e.g. +491701234567)")
        return cleaned


class FieldMagicLinkRequestResponse(BaseModel):
    """Always 202 — does not reveal whether the phone is provisioned.

    In dev / test the plaintext link + PIN are returned so the caller can
    drive the consume flow without an SMS provider; in production these
    fields are ``None`` and the SMS provider has fanned them out.
    """

    accepted: bool = True
    # Populated only when settings.app_debug is True (dev / test).
    dev_token: str | None = None
    dev_pin: str | None = None
    expires_at: datetime | None = None


class FieldMagicLinkConsume(BaseModel):
    token: str = Field(..., min_length=8, max_length=128)
    pin: str = Field(..., pattern=r"^\d{6}$")


class FieldSessionResponse(BaseModel):
    session_token: str
    expires_at: datetime
    project_id: uuid.UUID
    user_id: uuid.UUID
    module_key: str


__all__ = [
    "ACTIVITY_TYPES",
    "DIARY_STATUSES",
    "MAX_ATTACHMENT_BYTES",
    "DiaryActivityCreate",
    "DiaryActivityResponse",
    "DiaryAttachmentResponse",
    "DiaryEntryCreate",
    "DiaryEntryResponse",
    "DiaryEntryUpdate",
    "FieldMagicLinkConsume",
    "FieldMagicLinkRequest",
    "FieldMagicLinkRequestResponse",
    "FieldModuleGrantCreate",
    "FieldModuleGrantResponse",
    "FieldSessionResponse",
]
