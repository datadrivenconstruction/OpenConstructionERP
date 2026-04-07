"""Notification service — business logic for in-app notifications.

Stateless service layer.  Wraps the repository and provides convenience
helpers like ``notify_users`` for bulk delivery.
"""

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.models import Notification
from app.modules.notifications.repository import NotificationRepository

logger = logging.getLogger(__name__)


class NotificationService:
    """Business logic for notification operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = NotificationRepository(session)

    # ── Create ──────────────────────────────────────────────────────────────

    async def create(
        self,
        user_id: uuid.UUID | str,
        notification_type: str,
        title_key: str,
        *,
        entity_type: str | None = None,
        entity_id: str | None = None,
        body_key: str | None = None,
        body_context: dict[str, Any] | None = None,
        action_url: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Notification:
        """Create a single notification for one user."""
        uid = uuid.UUID(str(user_id)) if not isinstance(user_id, uuid.UUID) else user_id
        notification = Notification(
            user_id=uid,
            notification_type=notification_type,
            entity_type=entity_type,
            entity_id=entity_id,
            title_key=title_key,
            body_key=body_key,
            body_context=body_context or {},
            action_url=action_url,
            metadata_=metadata or {},
        )
        notification = await self.repo.create(notification)
        logger.info(
            "Notification created: type=%s user=%s title_key=%s",
            notification_type,
            uid,
            title_key,
        )
        return notification

    async def notify_users(
        self,
        user_ids: list[uuid.UUID | str],
        notification_type: str,
        title_key: str,
        *,
        entity_type: str | None = None,
        entity_id: str | None = None,
        body_key: str | None = None,
        body_context: dict[str, Any] | None = None,
        action_url: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> list[Notification]:
        """Create the same notification for multiple recipients."""
        notifications: list[Notification] = []
        for uid in user_ids:
            n = await self.create(
                user_id=uid,
                notification_type=notification_type,
                title_key=title_key,
                entity_type=entity_type,
                entity_id=entity_id,
                body_key=body_key,
                body_context=body_context,
                action_url=action_url,
                metadata=metadata,
            )
            notifications.append(n)
        logger.info(
            "Bulk notifications sent: type=%s count=%d title_key=%s",
            notification_type,
            len(notifications),
            title_key,
        )
        return notifications

    # ── Read ────────────────────────────────────────────────────────────────

    async def list_for_user(
        self,
        user_id: uuid.UUID | str,
        *,
        is_read: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Notification], int]:
        """List notifications for a user."""
        uid = uuid.UUID(str(user_id)) if not isinstance(user_id, uuid.UUID) else user_id
        return await self.repo.list_for_user(uid, is_read=is_read, limit=limit, offset=offset)

    async def count_unread(self, user_id: uuid.UUID | str) -> int:
        """Count unread notifications for a user."""
        uid = uuid.UUID(str(user_id)) if not isinstance(user_id, uuid.UUID) else user_id
        return await self.repo.count_unread(uid)

    # ── Mark read ───────────────────────────────────────────────────────────

    async def mark_read(self, notification_id: uuid.UUID, user_id: uuid.UUID | str) -> bool:
        """Mark a single notification as read."""
        uid = uuid.UUID(str(user_id)) if not isinstance(user_id, uuid.UUID) else user_id
        return await self.repo.mark_read(notification_id, uid)

    async def mark_all_read(self, user_id: uuid.UUID | str) -> int:
        """Mark all notifications as read for a user."""
        uid = uuid.UUID(str(user_id)) if not isinstance(user_id, uuid.UUID) else user_id
        count = await self.repo.mark_all_read(uid)
        logger.info("Marked %d notifications as read for user=%s", count, uid)
        return count

    # ── Delete ──────────────────────────────────────────────────────────────

    async def delete(self, notification_id: uuid.UUID, user_id: uuid.UUID | str) -> bool:
        """Delete a single notification."""
        uid = uuid.UUID(str(user_id)) if not isinstance(user_id, uuid.UUID) else user_id
        return await self.repo.delete_by_id(notification_id, uid)

    async def delete_old(self, days: int = 90) -> int:
        """Cleanup: delete notifications older than ``days``."""
        count = await self.repo.delete_old(days)
        if count:
            logger.info("Cleaned up %d old notifications (older than %d days)", count, days)
        return count
