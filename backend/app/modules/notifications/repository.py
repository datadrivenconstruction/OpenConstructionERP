"""Notification data access layer.

All database queries for notifications live here.
No business logic — pure data access.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.models import Notification


class NotificationRepository:
    """Data access for Notification models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_user(
        self,
        user_id: uuid.UUID,
        *,
        is_read: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Notification], int]:
        """List notifications for a user with optional read-status filter.

        Returns (items, total_count).
        """
        base = select(Notification).where(Notification.user_id == user_id)
        if is_read is not None:
            base = base.where(Notification.is_read == is_read)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(Notification.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def count_unread(self, user_id: uuid.UUID) -> int:
        """Count unread notifications for a user."""
        stmt = (
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user_id, Notification.is_read == False)  # noqa: E712
        )
        return (await self.session.execute(stmt)).scalar_one()

    async def get_by_id(self, notification_id: uuid.UUID) -> Notification | None:
        """Get a single notification by ID."""
        return await self.session.get(Notification, notification_id)

    async def mark_read(self, notification_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        """Mark a single notification as read. Returns True if updated."""
        now = datetime.now(UTC)
        stmt = (
            update(Notification)
            .where(
                Notification.id == notification_id,
                Notification.user_id == user_id,
                Notification.is_read == False,  # noqa: E712
            )
            .values(is_read=True, read_at=now)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount > 0  # type: ignore[union-attr]

    async def mark_all_read(self, user_id: uuid.UUID) -> int:
        """Mark all unread notifications as read for a user. Returns count updated."""
        now = datetime.now(UTC)
        stmt = (
            update(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.is_read == False,  # noqa: E712
            )
            .values(is_read=True, read_at=now)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount  # type: ignore[union-attr]

    async def create(self, notification: Notification) -> Notification:
        """Insert a new notification."""
        self.session.add(notification)
        await self.session.flush()
        return notification

    async def delete_by_id(self, notification_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        """Delete a single notification belonging to a user. Returns True if deleted."""
        stmt = delete(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == user_id,
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount > 0  # type: ignore[union-attr]

    async def delete_old(self, days: int = 90) -> int:
        """Delete notifications older than ``days``. Returns count deleted."""
        cutoff = datetime.now(UTC) - timedelta(days=days)
        stmt = delete(Notification).where(Notification.created_at < cutoff)
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount  # type: ignore[union-attr]
