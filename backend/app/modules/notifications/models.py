"""Notification ORM models.

Tables:
    oe_notifications_notification — per-user in-app notifications
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class Notification(Base):
    """In-app notification for a single user.

    Notifications use i18n keys (``title_key``, ``body_key``) so the frontend
    can render them in the user's locale.  ``body_context`` carries interpolation
    variables for the translation template.
    """

    __tablename__ = "oe_notifications_notification"

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
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
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
