# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""‌⁠‍Customer & Partner Portal ORM models.

Tables:
    oe_portal_user                   — external portal accounts (clients,
                                       investors, consultants, subcontractors,
                                       suppliers, building users). Distinct
                                       from ``oe_users_user`` — these accounts
                                       NEVER receive internal-system access.
    oe_portal_access_rule            — per-resource RLS grants
                                       (project / contract / document / ticket /
                                       subcontract / payment_application / po /
                                       bid_package / ...).
    oe_portal_session                — active session tokens (stored as
                                       sha256 hex only, never plaintext).
    oe_portal_magic_link             — one-time magic links for login /
                                       document_signature / payment_submission.
    oe_portal_notification           — in-portal feed entry.
    oe_portal_document_access_log    — append-only audit log of
                                       document view/download/sign events.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class PortalUser(Base):
    """‌⁠‍An external portal account — client / investor / consultant / sub / etc."""

    __tablename__ = "oe_portal_user"

    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
    )
    full_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="",
        server_default="",
    )
    portal_role: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
    )
    language: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default="en",
        server_default="en",
    )
    timezone: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="UTC",
        server_default="UTC",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="invited",
        server_default="invited",
        index=True,
    )
    invited_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    # Reserved for future password-based fallback. Magic-link is primary.
    password_hash: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    failed_login_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    # Email opt-in for transactional + actionable notifications. In-portal
    # feed is always on; this gate controls only outbound email.
    notification_email_opt_in: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="1",
    )

    def __repr__(self) -> str:  # pragma: no cover — debug only
        return f"<PortalUser {self.email} ({self.portal_role}/{self.status})>"


class PortalAccessRule(Base):
    """‌⁠‍Per-resource access grant for a portal user (row-level security)."""

    __tablename__ = "oe_portal_access_rule"

    portal_user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_portal_user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    permission: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="view",
        server_default="view",
    )
    granted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    # FK kept loose — granted_by may be from internal users, foreign-key not
    # strictly enforced to keep this module installable without a circular
    # dependency on users.
    granted_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        Index(
            "ix_oe_portal_access_rule_resource",
            "portal_user_id",
            "resource_type",
            "resource_id",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<PortalAccessRule {self.portal_user_id} {self.resource_type}:{self.resource_id} {self.permission}>"


class PortalSession(Base):
    """A live portal session keyed by sha256-hashed token."""

    __tablename__ = "oe_portal_session"

    portal_user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_portal_user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    session_token_hash: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        unique=True,
        index=True,
    )
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<PortalSession user={self.portal_user_id} "
            f"expires={self.expires_at} revoked={self.revoked_at is not None}>"
        )


class PortalMagicLink(Base):
    """One-time magic link (sha256-hashed token).

    Purposes:
        - login                — open a portal session
        - document_signature   — open a one-shot signature view
        - payment_submission   — open a one-shot payment-app submission flow
    """

    __tablename__ = "oe_portal_magic_link"

    portal_user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_portal_user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        unique=True,
        index=True,
    )
    purpose: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="login",
        server_default="login",
    )
    redirect_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<PortalMagicLink user={self.portal_user_id} "
            f"purpose={self.purpose} consumed={self.consumed_at is not None}>"
        )


class PortalNotification(Base):
    """A portal-side notification feed entry."""

    __tablename__ = "oe_portal_notification"

    portal_user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_portal_user.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="general",
        server_default="general",
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    body: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
    )
    link_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    __table_args__ = (
        Index(
            "ix_oe_portal_notification_user_read",
            "portal_user_id",
            "read_at",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<PortalNotification {self.kind} user={self.portal_user_id} read={self.read_at is not None}>"


class PortalDocumentAccessLog(Base):
    """Append-only audit log of portal document accesses (view/download/sign)."""

    __tablename__ = "oe_portal_document_access_log"

    portal_user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_portal_user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_type: Mapped[str] = mapped_column(String(64), nullable=False)
    document_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    action: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="view",
        server_default="view",
    )
    occurred_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<PortalDocAccessLog user={self.portal_user_id} {self.document_type}:{self.document_id} {self.action}>"


__all__ = [
    "PortalUser",
    "PortalAccessRule",
    "PortalSession",
    "PortalMagicLink",
    "PortalNotification",
    "PortalDocumentAccessLog",
]
