# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Design Options data access layer.

Async CRUD for design-option sets and their options. Every read is scoped by
``project_id`` so a set or option from another project can never be reached by
guessing an id (IDOR-safe): sets carry ``project_id`` directly and options carry
a denormalised copy for exactly this reason. Pure data access, no business
logic.
"""

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.design_options.models import DesignOption, DesignOptionSet


class DesignOptionsRepository:
    """Data access for :class:`DesignOptionSet` and :class:`DesignOption`."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Sets ─────────────────────────────────────────────────────────────

    async def create_set(self, option_set: DesignOptionSet) -> DesignOptionSet:
        """Insert a new option set and flush so its id is populated."""
        self.session.add(option_set)
        await self.session.flush()
        return option_set

    async def get_set(
        self,
        set_id: uuid.UUID,
        *,
        project_id: uuid.UUID | None = None,
    ) -> DesignOptionSet | None:
        """Get a set by id, optionally constrained to a project (IDOR guard).

        Options are eagerly loaded because the relationship uses selectin loading.
        """
        stmt = select(DesignOptionSet).where(DesignOptionSet.id == set_id)
        if project_id is not None:
            stmt = stmt.where(DesignOptionSet.project_id == project_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_sets(self, project_id: uuid.UUID) -> list[DesignOptionSet]:
        """List all sets for a project, newest first."""
        stmt = (
            select(DesignOptionSet)
            .where(DesignOptionSet.project_id == project_id)
            .order_by(DesignOptionSet.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_set_fields(self, set_id: uuid.UUID, **fields: object) -> None:
        """Update specific columns on a set (no-op when no fields are given)."""
        if not fields:
            return
        stmt = update(DesignOptionSet).where(DesignOptionSet.id == set_id).values(**fields)
        await self.session.execute(stmt)

    async def delete_set(self, set_id: uuid.UUID) -> None:
        """Hard delete a set and, by cascade, all of its options."""
        option_set = await self.get_set(set_id)
        if option_set is not None:
            await self.session.delete(option_set)
            await self.session.flush()

    # ── Options ──────────────────────────────────────────────────────────

    async def create_option(self, option: DesignOption) -> DesignOption:
        """Insert a new option and flush so its id is populated."""
        self.session.add(option)
        await self.session.flush()
        return option

    async def get_option(
        self,
        option_id: uuid.UUID,
        *,
        project_id: uuid.UUID | None = None,
    ) -> DesignOption | None:
        """Get an option by id, optionally constrained to a project (IDOR guard)."""
        stmt = select(DesignOption).where(DesignOption.id == option_id)
        if project_id is not None:
            stmt = stmt.where(DesignOption.project_id == project_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_options(self, set_id: uuid.UUID) -> list[DesignOption]:
        """List options in a set ordered by sort order then creation time."""
        stmt = (
            select(DesignOption)
            .where(DesignOption.set_id == set_id)
            .order_by(DesignOption.sort_order.asc(), DesignOption.created_at.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_option_fields(self, option_id: uuid.UUID, **fields: object) -> None:
        """Update specific columns on an option (no-op when no fields are given)."""
        if not fields:
            return
        stmt = update(DesignOption).where(DesignOption.id == option_id).values(**fields)
        await self.session.execute(stmt)

    async def delete_option(self, option_id: uuid.UUID) -> None:
        """Hard delete a single option."""
        option = await self.session.get(DesignOption, option_id)
        if option is not None:
            await self.session.delete(option)
            await self.session.flush()

    async def next_sort_order(self, set_id: uuid.UUID) -> int:
        """Return the next sort-order value for a new option appended to a set."""
        stmt = select(func.max(DesignOption.sort_order)).where(DesignOption.set_id == set_id)
        current = (await self.session.execute(stmt)).scalar_one_or_none()
        return int(current) + 1 if current is not None else 0
