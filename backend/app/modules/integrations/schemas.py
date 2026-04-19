"""Integrations Pydantic schemas -- request/response models."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.url_safety import UnsafeUrlError, validate_external_url

# ---------------------------------------------------------------------------
# IntegrationConfig schemas (Teams, Slack, Telegram, etc.)
# ---------------------------------------------------------------------------

INTEGRATION_TYPES = ("teams", "slack", "telegram", "discord", "whatsapp", "email", "webhook")
IntegrationType = Literal["teams", "slack", "telegram", "discord", "whatsapp", "email", "webhook"]


class IntegrationConfigCreate(BaseModel):
    """Create a new integration config (Teams, Slack, Telegram, etc.)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID | None = None
    integration_type: IntegrationType
    name: str = Field(..., min_length=1, max_length=255)
    config: dict[str, Any] = Field(
        ...,
        description=(
            "Connector-specific config. "
            "teams: {webhook_url}; slack: {webhook_url}; "
            "telegram: {bot_token, chat_id}; email: {smtp_host, smtp_port, ...}"
        ),
    )
    events: list[str] = Field(
        default=["*"],
        description="Event types to forward. ['*'] means all events.",
    )
    is_active: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class IntegrationConfigUpdate(BaseModel):
    """Partial update for an integration config."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    config: dict[str, Any] | None = None
    events: list[str] | None = None
    is_active: bool | None = None
    metadata: dict[str, Any] | None = None


class IntegrationConfigResponse(BaseModel):
    """Integration config returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    user_id: UUID
    project_id: UUID | None = None
    integration_type: str
    name: str
    config: dict[str, Any] = Field(default_factory=dict)
    events: list[str] = Field(default_factory=lambda: ["*"])
    is_active: bool = True
    last_triggered_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class IntegrationConfigListResponse(BaseModel):
    """Paginated list of integration configs."""

    items: list[IntegrationConfigResponse]
    total: int


class TestNotificationResponse(BaseModel):
    """Result of a test notification dispatch."""

    success: bool
    message: str


# ---------------------------------------------------------------------------
# Webhook schemas
# ---------------------------------------------------------------------------


def _validate_webhook_url(value: str) -> str:
    """Shared webhook-URL validator. Rejects non-http(s) schemes, literal
    private IPs and cloud-metadata hosts before the row ever hits the DB."""
    try:
        return validate_external_url(value)
    except UnsafeUrlError as exc:
        raise ValueError(str(exc)) from exc


class WebhookCreate(BaseModel):
    """Create a new webhook endpoint."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID | None = None
    name: str = Field(..., min_length=1, max_length=255)
    url: str = Field(..., min_length=1, max_length=1000)
    secret: str | None = Field(default=None, max_length=255)
    events: list[str] = Field(
        ...,
        min_length=1,
        description="Event types to subscribe, e.g. ['rfi.created', 'task.assigned']",
    )
    is_active: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("url")
    @classmethod
    def _check_url(cls, v: str) -> str:
        return _validate_webhook_url(v)


class WebhookUpdate(BaseModel):
    """Partial update for a webhook endpoint."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    url: str | None = Field(default=None, min_length=1, max_length=1000)
    secret: str | None = Field(default=None, max_length=255)
    events: list[str] | None = None
    is_active: bool | None = None
    metadata: dict[str, Any] | None = None

    @field_validator("url")
    @classmethod
    def _check_url(cls, v: str | None) -> str | None:
        return _validate_webhook_url(v) if v is not None else v


class WebhookResponse(BaseModel):
    """Webhook endpoint returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    user_id: UUID
    project_id: UUID | None = None
    name: str
    url: str
    secret: str | None = None
    events: list[str] = Field(default_factory=list)
    is_active: bool = True
    last_triggered_at: str | None = None
    last_status_code: int | None = None
    failure_count: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class DeliveryResponse(BaseModel):
    """Webhook delivery log entry returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    webhook_id: UUID
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    status_code: int | None = None
    response_body: str | None = None
    duration_ms: int | None = None
    created_at: datetime
