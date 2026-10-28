# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ESG data access layer.

All database queries for ESG entries live here - no business logic. The metric
catalogue is code-defined (``app.modules.esg.catalogue``) and never queried.
"""

import uuid

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy.orm.util import identity_key
from sqlalchemy.sql.elements import ClauseElement

from app.modules.esg.models import EsgEntry


class EsgEntryRepository:
    """Data access for :class:`EsgEntry` models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, entry_id: uuid.UUID) -> EsgEntry | None:
        """Get an entry by ID."""
        return await self.session.get(EsgEntry, entry_id)

    async def get_by_project_metric_period(
        self,
        project_id: uuid.UUID,
        metric_key: str,
        period: str,
    ) -> EsgEntry | None:
        """Get the single entry for a (project, metric, period), if any.

        Used to enforce one reading per metric per period on create.
        """
        stmt = select(EsgEntry).where(
            EsgEntry.project_id == project_id,
            EsgEntry.metric_key == metric_key,
            EsgEntry.period == period,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        metric_key: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[EsgEntry], int]:
        """List entries for a project (newest period first), with pagination."""
        base = select(EsgEntry).where(EsgEntry.project_id == project_id)
        if metric_key is not None:
            base = base.where(EsgEntry.metric_key == metric_key)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(EsgEntry.period.desc(), EsgEntry.metric_key.asc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())
        return items, total

    async def list_all_for_project(self, project_id: uuid.UUID) -> list[EsgEntry]:
        """Return every entry for a project ordered by metric then period ascending.

        Feeds the summary, which groups by metric and takes the trailing trend;
        the ascending period order means the last item per metric is the latest.
        """
        stmt = (
            select(EsgEntry)
            .where(EsgEntry.project_id == project_id)
            .order_by(EsgEntry.metric_key.asc(), EsgEntry.period.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, entry: EsgEntry) -> EsgEntry:
        """Insert a new entry."""
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def update_fields(self, entry_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on an entry."""
        stmt = update(EsgEntry).where(EsgEntry.id == entry_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        instance = self.session.identity_map.get(identity_key(EsgEntry, entry_id))
        if instance is None:
            return
        computed = [name for name, value in fields.items() if isinstance(value, ClauseElement)]
        for name, value in fields.items():
            if name not in computed:
                set_committed_value(instance, name, value)
        if computed:
            self.session.expire(instance, computed)

    async def delete(self, entry_id: uuid.UUID) -> None:
        """Delete an entry by ID."""
        await self.session.execute(sa_delete(EsgEntry).where(EsgEntry.id == entry_id))
        await self.session.flush()
