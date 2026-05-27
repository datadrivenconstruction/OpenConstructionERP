"""‌⁠‍Notification Pydantic schemas — request/response models.

The response schema renders English fallback strings server-side so the
bell always has readable text even when the frontend i18n layer hasn't
loaded the matching key (or doesn't have one). The two fallback fields
(``title_default``, ``body_default``) are computed via
:func:`app.modules.notifications.templates.render` from the stored
``title_key`` / ``body_key`` and the JSON ``body_context``.

``icon_category`` is also computed server-side so the frontend's
icon palette (success / error / warning / info / import / validation /
system) doesn't need to know about every backend ``notification_type``
the platform might emit (or that a third-party module added).
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.notifications.templates import (
    icon_category_for,
)
from app.modules.notifications.templates import (
    render as render_template,
)

# ── Backward-compat key aliases ──────────────────────────────────────────
#
# Some events were emitted with an older naming convention where the
# title_key and body_key were the SAME string (e.g. both
# ``notifications.rfi.assigned``). The active code now writes
# ``.title`` / ``.body`` suffixes, but rows already in the DB still
# have the old keys — without aliasing, those notifications would
# render as the raw key string in the bell.
#
# Resolution: at serialise time, if the stored key has no template
# entry and there's a ``.title`` / ``.body`` suffixed sibling, treat
# it as that sibling.

_LEGACY_TITLE_ALIASES: dict[str, str] = {
    "notifications.rfi.assigned": "notifications.rfi.assigned.title",
    "notifications.rfi.responded": "notifications.rfi.responded.title",
    "notifications.risk.assigned": "notifications.risk.assigned.title",
    "notifications.submittal.submitted": "notifications.submittal.submitted.title",
    "notifications.submittal.approved": "notifications.submittal.approved.title",
    "notifications.submittal.rejected": "notifications.submittal.rejected.title",
    "notifications.submittal.revise_resubmit": "notifications.submittal.revise_resubmit.title",
    "notifications.transmittal.issued": "notifications.transmittal.issued.title",
    "notifications.transmittal.acknowledged": "notifications.transmittal.acknowledged.title",
    "notifications.transmittal.responded": "notifications.transmittal.responded.title",
}

_LEGACY_BODY_ALIASES: dict[str, str] = {
    "notifications.rfi.assigned": "notifications.rfi.assigned.body",
    "notifications.rfi.responded": "notifications.rfi.responded.body",
    "notifications.risk.assigned": "notifications.risk.assigned.body",
    "notifications.submittal.submitted": "notifications.submittal.submitted.body",
    "notifications.submittal.approved": "notifications.submittal.approved.body",
    "notifications.submittal.rejected": "notifications.submittal.rejected.body",
    "notifications.submittal.revise_resubmit": "notifications.submittal.revise_resubmit.body",
    "notifications.transmittal.issued": "notifications.transmittal.issued.body",
    "notifications.transmittal.acknowledged": "notifications.transmittal.acknowledged.body",
    "notifications.transmittal.responded": "notifications.transmittal.responded.body",
}


def _resolve_title_key(stored: str) -> str:
    return _LEGACY_TITLE_ALIASES.get(stored, stored)


def _resolve_body_key(stored: str | None) -> str | None:
    if stored is None:
        return None
    return _LEGACY_BODY_ALIASES.get(stored, stored)


class NotificationResponse(BaseModel):
    """Single notification returned from the API.

    Wire the bell off ``title_default`` + ``body_default`` for guaranteed
    readability, and use ``title_key`` / ``body_key`` + ``body_context``
    for proper localisation when the locale file has the keys.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    user_id: UUID
    notification_type: str
    entity_type: str | None = None
    entity_id: str | None = None
    title_key: str
    title_default: str = ""
    body_key: str | None = None
    body_default: str = ""
    body_context: dict[str, Any] = Field(default_factory=dict)
    action_url: str | None = None
    icon_category: str = "info"
    is_read: bool = False
    read_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def _populate_defaults(self) -> "NotificationResponse":
        """Render server-side English fallbacks + map icon category.

        Runs after attribute hydration so the stored keys + context are
        already on the model. Idempotent — re-running it produces the
        same output, so it's safe inside FastAPI's response_model
        revalidation cycle.
        """
        ctx = self.body_context or {}
        # Resolve legacy aliases (DB rows from before .title/.body split)
        # so the renderer hits the right template.
        resolved_title_key = _resolve_title_key(self.title_key)
        resolved_body_key = _resolve_body_key(self.body_key)

        if not self.title_default:
            object.__setattr__(
                self,
                "title_default",
                render_template(resolved_title_key, ctx),
            )
        if not self.body_default and resolved_body_key:
            object.__setattr__(
                self,
                "body_default",
                render_template(resolved_body_key, ctx),
            )
        # Always compute icon_category — the stored notification_type is
        # the source of truth and the model never persists icon_category.
        object.__setattr__(
            self,
            "icon_category",
            icon_category_for(self.notification_type),
        )
        # Surface the canonical key to the frontend so the i18n call
        # uses the new convention even for legacy rows.
        if resolved_title_key != self.title_key:
            object.__setattr__(self, "title_key", resolved_title_key)
        if resolved_body_key != self.body_key:
            object.__setattr__(self, "body_key", resolved_body_key)
        return self


class NotificationListResponse(BaseModel):
    """‌⁠‍Paginated notification list."""

    items: list[NotificationResponse]
    total: int
    unread_count: int


class MarkReadRequest(BaseModel):
    """Request body for marking notifications as read."""

    model_config = ConfigDict(str_strip_whitespace=True)

    notification_ids: list[UUID] = Field(
        default_factory=list,
        description="Optional list of IDs to mark as read. Empty = mark all.",
    )


# ── Preferences + digest (Wave 3 / T9) ───────────────────────────────────


class PreferenceRequest(BaseModel):
    """Upsert payload for ``POST /v1/notifications/preferences/``.

    A pref is a per-user, per-(event_type, channel) decision: whether the
    user wants this kind of event on this channel at all, and if so, on
    what cadence (immediate vs hourly vs daily digest).
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    event_type: str = Field(
        min_length=1,
        max_length=80,
        description="Event-bus dot-notation key, e.g. 'boq.position.created'.",
    )
    channel: str = Field(
        pattern=r"^(email|inapp|webhook|none)$",
        description="Delivery channel.",
    )
    enabled: bool = Field(default=True)
    digest: str = Field(
        default="realtime",
        pattern=r"^(realtime|hourly|daily)$",
        description="Realtime fires immediately; hourly/daily queue for batch.",
    )


class PreferenceResponse(BaseModel):
    """Single notification preference row."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    event_type: str
    channel: str
    enabled: bool
    digest: str
    created_at: datetime
    updated_at: datetime


class EventTypeCatalogEntry(BaseModel):
    """One entry in the known-event-types catalogue.

    Surfaced to the frontend so the Preferences tab can render the matrix
    of event-type × channel cells without hardcoding the list there.
    """

    event_type: str
    module: str
    description: str


# ── Webhook target CRUD (Epic B / B8) ─────────────────────────────────────


class WebhookTargetCreate(BaseModel):
    """Payload to register a new webhook target."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=8, max_length=2048, pattern=r"^https?://.+")
    event_filter: str = Field(
        default="*",
        max_length=1024,
        description=(
            "Comma-separated list of event-type patterns. "
            "Use ``*`` for wildcard, ``boq.*`` for prefix, exact event "
            "type otherwise."
        ),
    )
    secret: str | None = Field(default=None, max_length=255)
    active: bool = True


class WebhookTargetUpdate(BaseModel):
    """Partial-update payload for an existing webhook target."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=120)
    url: str | None = Field(
        default=None,
        min_length=8,
        max_length=2048,
        pattern=r"^https?://.+",
    )
    event_filter: str | None = Field(default=None, max_length=1024)
    secret: str | None = Field(default=None, max_length=255)
    active: bool | None = None


class WebhookTargetResponse(BaseModel):
    """Single webhook target row returned to the Admin UI."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    url: str
    event_filter: str
    # The plaintext secret is intentionally NEVER serialised back to
    # the client.  We expose a boolean so the UI can show "secret set"
    # without ever leaking the value.
    has_secret: bool = False
    active: bool
    last_status: int | None = None
    last_attempt_at: datetime | None = None
    failure_count: int = 0
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def _populate_has_secret(self) -> "WebhookTargetResponse":
        """``has_secret`` is computed by the router (where the ORM row
        is still in scope).  This validator is a no-op safety net so
        the model is internally consistent if anyone constructs the
        response directly.
        """
        return self
