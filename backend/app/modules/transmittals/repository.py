"""Transmittals data access layer.

All database queries for transmittals live here.
No business logic — pure data access.
"""

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.transmittals.models import (
    Transmittal,
    TransmittalItem,
    TransmittalRecipient,
)


class TransmittalRepository:
    """Data access for Transmittal, TransmittalRecipient, TransmittalItem models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Transmittal CRUD ─────────────────────────────────────────────────

    async def get(self, transmittal_id: uuid.UUID) -> Transmittal | None:
        """Get transmittal by ID (with recipients and items eager-loaded)."""
        stmt = (
            select(Transmittal)
            .where(Transmittal.id == transmittal_id)
            .options(
                selectinload(Transmittal.recipients),
                selectinload(Transmittal.items),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_project(
        self,
        project_id: uuid.UUID,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Transmittal], int]:
        """List transmittals for a project with optional status filter.

        Returns (transmittals, total_count).
        """
        base = select(Transmittal).where(Transmittal.project_id == project_id)

        if status is not None:
            base = base.where(Transmittal.status == status)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(Transmittal.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        transmittals = list(result.scalars().all())

        return transmittals, total

    async def create(self, transmittal: Transmittal) -> Transmittal:
        """Insert a new transmittal."""
        self.session.add(transmittal)
        await self.session.flush()
        return transmittal

    async def update_fields(self, transmittal_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a transmittal."""
        stmt = update(Transmittal).where(Transmittal.id == transmittal_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def next_number(self, project_id: uuid.UUID) -> str:
        """Generate the next transmittal number for a project (TR-001, TR-002, ...).

        Uses MAX-based extraction to avoid collisions after deletions.
        """
        stmt = (
            select(func.max(Transmittal.transmittal_number))
            .where(Transmittal.project_id == project_id)
        )
        max_number = (await self.session.execute(stmt)).scalar_one()
        if max_number is None:
            return "TR-001"
        # Extract numeric part from e.g. "TR-007"
        try:
            numeric = int(max_number.split("-", 1)[1])
        except (IndexError, ValueError):
            numeric = 0
        return f"TR-{numeric + 1:03d}"

    # ── Recipient operations ─────────────────────────────────────────────

    async def get_recipient(self, recipient_id: uuid.UUID) -> TransmittalRecipient | None:
        """Get a recipient by ID."""
        return await self.session.get(TransmittalRecipient, recipient_id)

    async def add_recipient(self, recipient: TransmittalRecipient) -> TransmittalRecipient:
        """Add a recipient to a transmittal."""
        self.session.add(recipient)
        await self.session.flush()
        return recipient

    async def update_recipient(self, recipient_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a recipient."""
        stmt = (
            update(TransmittalRecipient)
            .where(TransmittalRecipient.id == recipient_id)
            .values(**fields)
        )
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete_recipients(self, transmittal_id: uuid.UUID) -> None:
        """Delete all recipients for a transmittal."""
        from sqlalchemy import delete

        stmt = delete(TransmittalRecipient).where(
            TransmittalRecipient.transmittal_id == transmittal_id
        )
        await self.session.execute(stmt)
        await self.session.flush()

    # ── Item operations ──────────────────────────────────────────────────

    async def add_item(self, item: TransmittalItem) -> TransmittalItem:
        """Add an item to a transmittal."""
        self.session.add(item)
        await self.session.flush()
        return item

    async def delete_items(self, transmittal_id: uuid.UUID) -> None:
        """Delete all items for a transmittal."""
        from sqlalchemy import delete

        stmt = delete(TransmittalItem).where(
            TransmittalItem.transmittal_id == transmittal_id
        )
        await self.session.execute(stmt)
        await self.session.flush()
