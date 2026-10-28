# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Transmittals data access layer.

All database queries for transmittals live here.
No business logic - pure data access.
"""

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy.orm.util import identity_key
from sqlalchemy.sql.elements import ClauseElement

from app.core.orm_write import apply_update
from app.modules.transmittals.logic import (
    DEFAULT_NUMBER_PAD,
    DEFAULT_NUMBER_PREFIX,
    highest_in_sequence,
    next_transmittal_number,
)
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
        instance = self.session.identity_map.get(identity_key(Transmittal, transmittal_id))
        if instance is None:
            return
        computed = [name for name, value in fields.items() if isinstance(value, ClauseElement)]
        for name, value in fields.items():
            if name not in computed:
                set_committed_value(instance, name, value)
        if computed:
            self.session.expire(instance, computed)

    async def next_number(
        self,
        project_id: uuid.UUID,
        *,
        prefix: str = DEFAULT_NUMBER_PREFIX,
        pad: int = DEFAULT_NUMBER_PAD,
    ) -> str:
        """Generate the next transmittal number for a project (TR-001, TR-002, ...).

        Reads the highest existing number (MAX-based so gaps left by deleted
        drafts do not cause collisions) and hands it to the pure
        ``next_transmittal_number`` helper, which increments the trailing
        counter. ``prefix`` and ``pad`` let a project follow its own
        document-control convention.
        """
        stmt = select(Transmittal.transmittal_number).where(Transmittal.project_id == project_id)
        numbers = list((await self.session.execute(stmt)).scalars())
        return next_transmittal_number(highest_in_sequence(numbers, prefix), prefix=prefix, pad=pad)

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
        await apply_update(self.session, TransmittalRecipient, recipient_id, **fields)

    async def delete_recipients(self, transmittal_id: uuid.UUID) -> None:
        """Delete all recipients for a transmittal."""
        from sqlalchemy import delete

        stmt = delete(TransmittalRecipient).where(TransmittalRecipient.transmittal_id == transmittal_id)
        await self.session.execute(stmt)
        await self.session.flush()

    async def delete_recipient(self, transmittal_id: uuid.UUID, recipient_id: uuid.UUID) -> int:
        """Delete a single recipient, scoped to its transmittal.

        Returns the number of rows deleted (0 when the recipient does not exist
        or belongs to another transmittal) so the service can answer 404.
        """
        from sqlalchemy import delete

        stmt = delete(TransmittalRecipient).where(
            TransmittalRecipient.id == recipient_id,
            TransmittalRecipient.transmittal_id == transmittal_id,
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount or 0

    # ── Item operations ──────────────────────────────────────────────────

    async def add_item(self, item: TransmittalItem) -> TransmittalItem:
        """Add an item to a transmittal."""
        self.session.add(item)
        await self.session.flush()
        return item

    async def delete_items(self, transmittal_id: uuid.UUID) -> None:
        """Delete all items for a transmittal."""
        from sqlalchemy import delete

        stmt = delete(TransmittalItem).where(TransmittalItem.transmittal_id == transmittal_id)
        await self.session.execute(stmt)
        await self.session.flush()

    async def delete(self, transmittal_id: uuid.UUID) -> None:
        """Delete a transmittal and its children (recipients + items)."""
        from sqlalchemy import delete

        await self.delete_recipients(transmittal_id)
        await self.delete_items(transmittal_id)
        stmt = delete(Transmittal).where(Transmittal.id == transmittal_id)
        await self.session.execute(stmt)
        await self.session.flush()
