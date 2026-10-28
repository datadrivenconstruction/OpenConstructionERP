# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Closeout data access layer.

Async SQLAlchemy. Project scoping is enforced at the service / router layer
(every package is unique per project); this layer is pure CRUD.
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.closeout.models import CloseoutBinding, CloseoutPackage, CloseoutSlot


class CloseoutRepository:
    """Data access for closeout package / slot / binding rows."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Package ──────────────────────────────────────────────────────────

    async def get_package(self, package_id: uuid.UUID) -> CloseoutPackage | None:
        """Return a package by id, or None."""
        return await self.session.get(CloseoutPackage, package_id)

    async def get_package_for_project(self, project_id: uuid.UUID) -> CloseoutPackage | None:
        """Return the (single) package for a project, or None."""
        stmt = select(CloseoutPackage).where(CloseoutPackage.project_id == project_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def create_package(self, package: CloseoutPackage) -> CloseoutPackage:
        """Insert a new package."""
        self.session.add(package)
        await self.session.flush()
        return package

    # ── Slots ────────────────────────────────────────────────────────────

    async def list_slots(self, package_id: uuid.UUID) -> list[CloseoutSlot]:
        """Return slots for a package ordered by ``ordinal`` then key."""
        stmt = (
            select(CloseoutSlot)
            .where(CloseoutSlot.package_id == package_id)
            .order_by(CloseoutSlot.ordinal, CloseoutSlot.slot_key)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_slot(self, slot_id: uuid.UUID) -> CloseoutSlot | None:
        """Return a slot by id, or None."""
        return await self.session.get(CloseoutSlot, slot_id)

    async def add_slot(self, slot: CloseoutSlot) -> CloseoutSlot:
        """Insert a new slot."""
        self.session.add(slot)
        await self.session.flush()
        return slot

    async def delete_slot(self, slot_id: uuid.UUID) -> None:
        """Delete a slot (its bindings cascade)."""
        slot = await self.get_slot(slot_id)
        if slot is not None:
            await self.session.delete(slot)
            await self.session.flush()

    # ── Bindings ─────────────────────────────────────────────────────────

    async def get_binding_for_slot(self, slot_id: uuid.UUID) -> CloseoutBinding | None:
        """Return the binding for a slot, or None.

        A slot holds at most one active binding; if multiples exist (legacy /
        test data) the most recent wins.
        """
        stmt = (
            select(CloseoutBinding)
            .where(CloseoutBinding.slot_id == slot_id)
            .order_by(CloseoutBinding.created_at.desc())
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def list_bindings_for_package(self, package_id: uuid.UUID) -> dict[uuid.UUID, CloseoutBinding]:
        """Return a ``{slot_id -> binding}`` map for every slot in a package."""
        slot_ids_stmt = select(CloseoutSlot.id).where(CloseoutSlot.package_id == package_id)
        slot_ids = list((await self.session.execute(slot_ids_stmt)).scalars().all())
        if not slot_ids:
            return {}
        stmt = (
            select(CloseoutBinding)
            .where(CloseoutBinding.slot_id.in_(slot_ids))
            .order_by(CloseoutBinding.created_at.asc())
        )
        rows = list((await self.session.execute(stmt)).scalars().all())
        # Later rows overwrite earlier ones so the newest binding per slot wins.
        return {row.slot_id: row for row in rows}

    async def add_binding(self, binding: CloseoutBinding) -> CloseoutBinding:
        """Insert a new binding."""
        self.session.add(binding)
        await self.session.flush()
        return binding

    async def delete_bindings_for_slot(self, slot_id: uuid.UUID) -> None:
        """Delete every binding attached to a slot."""
        await self.session.execute(delete(CloseoutBinding).where(CloseoutBinding.slot_id == slot_id))
        await self.session.flush()
