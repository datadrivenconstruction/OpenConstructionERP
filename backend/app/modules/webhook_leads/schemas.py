"""Webhook Leads Pydantic schemas — request/response models."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# Auth methods supported on a webhook source.
_AUTH_PATTERN = r"^(api_key|hmac|jwt)$"

# CRM Lead fields a mapping rule is allowed to target. Kept in lock-step
# with ``app.modules.crm.schemas.LeadCreate`` so a mapping can never write
# an attribute the CRM lead-create path does not accept.
ALLOWED_TARGET_FIELDS: frozenset[str] = frozenset(
    {
        "contact_name",
        "contact_email",
        "contact_phone",
        "source",
        "qualification_notes",
    }
)

# Pure string transforms a mapping rule may name.
ALLOWED_TRANSFORMS: frozenset[str] = frozenset({"lower", "upper", "strip", "str", "title"})


# ── WebhookSource ─────────────────────────────────────────────────────────


class WebhookSourceCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9-_]*$")
    auth_method: str = Field(default="api_key", pattern=_AUTH_PATTERN)
    project_id: str | None = Field(default=None, max_length=36)
    ip_allowlist: list[str] = Field(default_factory=list)
    is_active: bool = True
    rate_limit_per_min: int = Field(default=60, ge=1, le=10000)
    default_lead_source: str = Field(default="web", pattern=r"^(web|referral|event|cold_outreach|inbound)$")


class WebhookSourceUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, max_length=255)
    auth_method: str | None = Field(default=None, pattern=_AUTH_PATTERN)
    project_id: str | None = Field(default=None, max_length=36)
    ip_allowlist: list[str] | None = None
    is_active: bool | None = None
    rate_limit_per_min: int | None = Field(default=None, ge=1, le=10000)
    default_lead_source: str | None = Field(default=None, pattern=r"^(web|referral|event|cold_outreach|inbound)$")


class WebhookSourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    auth_method: str
    project_id: str | None
    ip_allowlist: list[str]
    is_active: bool
    rate_limit_per_min: int
    default_lead_source: str
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime


class WebhookSourceCreatedResponse(WebhookSourceResponse):
    """Returned only by POST /sources/ and the secret-rotation endpoint.

    Carries the plaintext ``secret`` exactly once — it is never readable
    again after this response (only the SHA-256 hash is persisted).
    """

    secret: str
    ingestion_url: str


class SecretRotateResponse(BaseModel):
    id: UUID
    secret: str
    ingestion_url: str


# ── PayloadMapping ────────────────────────────────────────────────────────


class PayloadMappingCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    target_field: str = Field(..., min_length=1, max_length=64)
    source_path: str = Field(..., min_length=1, max_length=255)
    transform: str | None = Field(default=None, max_length=32)
    required: bool = False


class PayloadMappingUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    target_field: str | None = Field(default=None, max_length=64)
    source_path: str | None = Field(default=None, max_length=255)
    transform: str | None = Field(default=None, max_length=32)
    required: bool | None = None


class PayloadMappingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_id: UUID
    target_field: str
    source_path: str
    transform: str | None
    required: bool
    created_at: datetime
    updated_at: datetime


# ── WebhookLog ────────────────────────────────────────────────────────────


class WebhookLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_id: UUID | None
    source_slug: str
    received_at: str | None
    remote_ip: str
    status: str
    http_status: int
    payload: dict
    error_message: str
    created_lead_id: UUID | None
    created_at: datetime


# ── Ingestion result ──────────────────────────────────────────────────────


class IngestionResponse(BaseModel):
    """Body returned to the calling external system on success."""

    status: str = "accepted"
    lead_id: UUID
    log_id: UUID
