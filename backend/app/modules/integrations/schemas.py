"""‌⁠‍Integrations Pydantic schemas -- request/response models."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from app.core.url_safety import UnsafeUrlError, validate_external_url

# ---------------------------------------------------------------------------
# IntegrationConfig schemas (Teams, Slack, Telegram, etc.)
# ---------------------------------------------------------------------------

INTEGRATION_TYPES = ("teams", "slack", "telegram", "discord", "whatsapp", "email", "webhook")
IntegrationType = Literal["teams", "slack", "telegram", "discord", "whatsapp", "email", "webhook"]


# Secret-bearing keys inside ``IntegrationConfig.config`` that must NEVER
# be echoed back in a response payload — even to the user who owns the
# row. Two reasons: (1) browser-side leaks via XSS / screen sharing,
# (2) the secret is already stored in the DB so the read-back has zero
# legitimate use. Writes still flow through unchanged (Pydantic does not
# validate output-only redaction on input).
_SECRET_CONFIG_KEYS: frozenset[str] = frozenset(
    {
        "webhook_url",  # Teams / Slack / Discord — full URL is the bearer credential
        "bot_token",  # Telegram bot token (BotFather-issued)
        "access_token",  # WhatsApp / generic OAuth bearer
        "api_key",  # Generic third-party API key
        "api_token",  # Synonym
        "secret",  # Generic shared-secret
        "client_secret",  # OAuth2 client secret
        "smtp_password",  # Email connector password
        "password",  # Generic password field
        "phone_number_id",  # WhatsApp Cloud API tenant identifier (sensitive)
        "auth_token",  # Twilio-style
    }
)

_REDACTED_MARKER = "***REDACTED***"


def _redact_config(config: dict[str, Any] | None) -> dict[str, Any]:
    """Return a copy of *config* with every secret-bearing key redacted.

    Keys are matched case-insensitively. Non-secret keys (chat_id,
    smtp_host, smtp_port, channel, ...) are returned untouched so the
    UI can still display the connector destination.
    """
    if not config:
        return {}
    out: dict[str, Any] = {}
    for k, v in config.items():
        if k.lower() in _SECRET_CONFIG_KEYS:
            # Preserve a hint of the value's existence (e.g. "***REDACTED***")
            # so the UI can render a "configured" badge without leaking the
            # actual material.
            out[k] = _REDACTED_MARKER if v else None
        else:
            out[k] = v
    return out


def _validate_config_urls(
    config: dict[str, Any] | None,
    integration_type: str,
) -> dict[str, Any]:
    """Reject SSRF-bait URLs inside connector config blobs.

    The outbound dispatcher (``service._deliver``) already runs a
    DNS-resolving SSRF check before httpx.post, but that's the second
    line of defence. The first is rejecting the row at write time so a
    malicious config never makes it into the DB. Every connector type
    that carries a ``webhook_url`` field gets validated here.
    """
    if not isinstance(config, dict):
        return config or {}
    url = config.get("webhook_url")
    if url and integration_type in ("teams", "slack", "discord", "webhook"):
        try:
            validate_external_url(str(url))
        except UnsafeUrlError as exc:
            raise ValueError(
                f"webhook_url for {integration_type!r} is unsafe: {exc}",
            ) from exc
    return config


class IntegrationConfigCreate(BaseModel):
    """‌⁠‍Create a new integration config (Teams, Slack, Telegram, etc.)."""

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

    @field_validator("config")
    @classmethod
    def _check_config_urls(cls, v: dict[str, Any], info) -> dict[str, Any]:
        itype = info.data.get("integration_type", "")
        return _validate_config_urls(v, str(itype))


class IntegrationConfigUpdate(BaseModel):
    """‌⁠‍Partial update for an integration config."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    config: dict[str, Any] | None = None
    events: list[str] | None = None
    is_active: bool | None = None
    metadata: dict[str, Any] | None = None

    @field_validator("config")
    @classmethod
    def _check_config_urls(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        # On PATCH we don't know the integration_type without a DB hit, so
        # validate any webhook_url that's present regardless of type. False
        # positives here are acceptable — webhooks should always target
        # routable external hosts.
        if v is None or "webhook_url" not in v:
            return v
        try:
            validate_external_url(str(v["webhook_url"]))
        except UnsafeUrlError as exc:
            raise ValueError(f"webhook_url is unsafe: {exc}") from exc
        return v


class IntegrationConfigResponse(BaseModel):
    """Integration config returned from the API.

    The ``config`` field is auto-redacted on serialization so secrets
    (webhook URLs, bot tokens, API keys) never leak back to the caller —
    even to the owner of the row. The UI can rely on the
    ``***REDACTED***`` marker as proof the secret is configured without
    ever seeing the actual material.
    """

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

    @field_serializer("config")
    def _redact_config_secrets(self, v: dict[str, Any]) -> dict[str, Any]:
        return _redact_config(v)


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
    """Webhook endpoint returned from the API.

    The ``secret`` HMAC key is auto-redacted on serialization. The owner
    set the secret at create time; there is no legitimate workflow that
    reads it back (HMAC signing happens server-side inside
    ``service._sign_payload``). Echoing it back would only widen the
    blast radius of an XSS or shoulder-surf.
    """

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

    @field_serializer("secret")
    def _redact_secret(self, v: str | None) -> str | None:
        # Return the marker iff a secret was set, ``None`` otherwise — so
        # the UI can show "HMAC signing: enabled" without ever seeing the
        # key material.
        return _REDACTED_MARKER if v else None


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
