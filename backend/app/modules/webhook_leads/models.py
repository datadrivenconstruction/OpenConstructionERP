"""Webhook Leads ORM models.

Tables:
    oe_webhook_leads_source   — a configured external webhook source
    oe_webhook_leads_log      — one row per ingestion attempt (audit)
    oe_webhook_leads_mapping  — payload-path → CRM-lead-field mapping rules

Notes:
    * ``project_id`` is a plain ``String(36)`` GUID with NO SQLAlchemy
      ForeignKey — mirrors the CRM convention so unit fixtures that never
      load the Projects module don't trip ``NoReferencedTableError``.
    * Secrets are stored *hashed* (SHA-256) — the plaintext is shown to
      the operator exactly once at creation/rotation time and never
      persisted in clear.
    * ``WebhookLog.payload`` is size-capped by the service layer before
      it ever reaches this model (see ``service.MAX_LOGGED_PAYLOAD``).
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class WebhookSource(Base):
    """A configured external system allowed to POST inbound leads."""

    __tablename__ = "oe_webhook_leads_source"

    # Optional delivery-project scope. Plain GUID, no DB FK (see header).
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    # api_key | hmac | jwt
    auth_method: Mapped[str] = mapped_column(String(16), nullable=False, default="api_key", server_default="api_key")
    # SHA-256 hex digest of the shared secret / api key — never the plaintext.
    secret_hash: Mapped[str] = mapped_column(String(128), nullable=False, default="", server_default="")
    # JSON array of allowed client IPs / CIDR-less exact strings. Empty = any.
    ip_allowlist: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1", index=True)
    rate_limit_per_min: Mapped[int] = mapped_column(Integer, nullable=False, default=60, server_default="60")
    # Default CRM lead source label applied when a mapping does not set it.
    default_lead_source: Mapped[str] = mapped_column(String(32), nullable=False, default="web", server_default="web")
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)

    def __repr__(self) -> str:
        return f"<WebhookSource {self.slug} ({self.auth_method})>"


class PayloadMapping(Base):
    """A single field-mapping rule for a webhook source.

    Maps an arbitrary dotted JSON path in the incoming payload onto a
    target CRM Lead field. ``transform`` optionally names a pure string
    transform (``lower``, ``upper``, ``strip``, ``str``).
    """

    __tablename__ = "oe_webhook_leads_mapping"

    source_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_webhook_leads_source.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # CRM Lead field this rule fills (contact_name, contact_email, ...).
    target_field: Mapped[str] = mapped_column(String(64), nullable=False)
    # Dotted JSON path into the incoming payload, e.g. "data.contact.email"
    # or "items.0.name" (numeric segments index into lists).
    source_path: Mapped[str] = mapped_column(String(255), nullable=False)
    transform: Mapped[str | None] = mapped_column(String(32), nullable=True)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")

    def __repr__(self) -> str:
        return f"<PayloadMapping {self.source_path} → {self.target_field}>"


class WebhookLog(Base):
    """An immutable audit record of one inbound webhook attempt."""

    __tablename__ = "oe_webhook_leads_log"

    source_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_webhook_leads_source.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Slug as supplied on the URL — kept even when the source is unknown so
    # probes against non-existent slugs are still auditable.
    source_slug: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="", index=True)
    received_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    remote_ip: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    # accepted | rejected | error
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="rejected",
        server_default="rejected",
        index=True,
    )
    http_status: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # Size-capped raw payload snapshot (service truncates before persist).
    payload: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    created_lead_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)

    def __repr__(self) -> str:
        return f"<WebhookLog {self.source_slug} {self.status} {self.http_status}>"
