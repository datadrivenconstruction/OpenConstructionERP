"""‌⁠‍Notification ORM models.

Tables:
    oe_notifications_notification — per-user in-app notifications
    oe_notification_preference     — per-user, per-event-type channel routing
    oe_notification_digest_queue   — queued payloads for hourly/daily digest
    oe_notification_webhook_target — admin-managed webhook endpoints (Epic B)
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class Notification(Base):
    """‌⁠‍In-app notification for a single user.

    Notifications use i18n keys (``title_key``, ``body_key``) so the frontend
    can render them in the user's locale.  ``body_context`` carries interpolation
    variables for the translation template.
    """

    __tablename__ = "oe_notifications_notification"
    __table_args__ = (
        Index("ix_notification_user_read", "user_id", "is_read"),
        Index("ix_notification_user_created", "user_id", "created_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    notification_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )
    entity_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    title_key: Mapped[str] = mapped_column(String(255), nullable=False)
    body_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    body_context: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    action_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0", index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        status = "read" if self.is_read else "unread"
        return f"<Notification {self.notification_type} [{status}] for user={self.user_id}>"


class NotificationPreference(Base):
    """‌⁠‍Per-user, per-event-type, per-channel notification routing.

    Looked up by :func:`NotificationService.enqueue_or_dispatch` to decide
    whether to dispatch an event to the in-app sink immediately, route it
    through email/webhook, or queue it for the hourly/daily digest.
    """

    __tablename__ = "oe_notification_preference"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "event_type",
            "channel",
            name="uq_oe_notification_preference_user_event_channel",
        ),
        Index("ix_oe_notification_preference_user_id", "user_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="1",
    )
    digest: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="realtime",
        server_default="realtime",
    )

    def __repr__(self) -> str:
        return (
            f"<NotificationPreference user={self.user_id} "
            f"event={self.event_type} channel={self.channel} "
            f"enabled={self.enabled} digest={self.digest}>"
        )


class NotificationDigestQueue(Base):
    """‌⁠‍Queued notification payload waiting for the next digest flush.

    ``scheduled_for`` is set when the row is created — ``now() + interval``
    where the interval depends on the user's chosen digest cadence
    (``hourly`` → +1h, ``daily`` → next 09:00 local UTC).  The flusher
    picks up every row with ``scheduled_for <= now AND sent_at IS NULL``,
    groups by ``(user_id, channel)``, sends one combined notification per
    group, and marks the rows as sent.
    """

    __tablename__ = "oe_notification_digest_queue"
    __table_args__ = (
        Index(
            "ix_oe_notification_digest_queue_scheduled_for_sent_at",
            "scheduled_for",
            "sent_at",
        ),
        Index("ix_oe_notification_digest_queue_user_id", "user_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    scheduled_for: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    def __repr__(self) -> str:
        sent = "sent" if self.sent_at else "pending"
        return f"<NotificationDigestQueue user={self.user_id} event={self.event_type} channel={self.channel} [{sent}]>"


class WebhookTarget(Base):
    """‌⁠‍Admin-managed webhook endpoint that consumes ``notifications.dispatch.webhook``.

    Each row is one outbound POST destination.  When the notification
    dispatcher fires a ``webhook`` channel, every active target whose
    ``event_filter`` matches the event type receives the payload as
    JSON.  ``secret`` is optional; when set it is included as a
    HMAC-SHA256 signature in the ``X-OE-Signature`` header so
    downstream services can verify authenticity.

    Idempotency: the dispatcher uses a per-event UUID4 idempotency key
    that downstream consumers can dedupe on.  ``failure_count`` /
    ``last_status`` track the most recent delivery so the Admin UI can
    surface broken endpoints without trawling logs.

    NOT scoped to ``user_id`` — webhooks are tenant-global plumbing,
    not per-user channels.  RBAC at the router edge restricts CRUD to
    admins.
    """

    __tablename__ = "oe_notification_webhook_target"
    __table_args__ = (Index("ix_oe_notification_webhook_target_active", "active"),)

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    # Comma-separated list of event-type patterns this target should
    # receive.  ``*`` is wildcard.  Stored as a string (not JSON array)
    # so SQLite indexes can lean on it for substring searches when the
    # list grows.
    event_filter: Mapped[str] = mapped_column(
        String(1024),
        nullable=False,
        default="*",
        server_default="*",
    )
    secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
    active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="1",
    )
    last_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    failure_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )

    def __repr__(self) -> str:
        return f"<WebhookTarget {self.name!r} url={self.url[:40]}... active={self.active}>"
