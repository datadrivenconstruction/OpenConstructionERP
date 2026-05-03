"""Punch List data access layer.

All database queries for punch list items live here.
No business logic — pure data access.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.punchlist.models import PunchItem


class PunchListRepository:
    """Data access for PunchItem models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, item_id: uuid.UUID) -> PunchItem | None:
        """Get punch item by ID."""
        return await self.session.get(PunchItem, item_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
        priority: str | None = None,
        assigned_to: str | None = None,
        category: str | None = None,
    ) -> tuple[list[PunchItem], int]:
        """List punch items for a project with pagination and filters."""
        base = select(PunchItem).where(PunchItem.project_id == project_id)
        if status is not None:
            base = base.where(PunchItem.status == status)
        if priority is not None:
            base = base.where(PunchItem.priority == priority)
        if assigned_to is not None:
            base = base.where(PunchItem.assigned_to == assigned_to)
        if category is not None:
            base = base.where(PunchItem.category == category)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(PunchItem.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def create(self, item: PunchItem) -> PunchItem:
        """Insert a new punch item."""
        self.session.add(item)
        await self.session.flush()
        return item

    async def update_fields(self, item_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a punch item."""
        stmt = update(PunchItem).where(PunchItem.id == item_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, item_id: uuid.UUID) -> None:
        """Hard delete a punch item."""
        item = await self.get_by_id(item_id)
        if item is not None:
            await self.session.delete(item)
            await self.session.flush()

    async def all_for_project(self, project_id: uuid.UUID) -> list[PunchItem]:
        """Return all punch items for a project (used for summary)."""
        stmt = select(PunchItem).where(PunchItem.project_id == project_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def summary_aggregates(
        self, project_id: uuid.UUID
    ) -> dict[str, object]:
        """Return SQL aggregates for the punch-list summary.

        Counts and group-by-status/priority are pure SQL. The closed
        durations still need a Python loop because SQLite lacks a
        portable date diff, but we project only 5 timestamp columns
        instead of hydrating full ORM rows.
        """
        total = (
            await self.session.execute(
                select(func.count(PunchItem.id)).where(
                    PunchItem.project_id == project_id
                )
            )
        ).scalar_one()

        status_rows = (
            await self.session.execute(
                select(PunchItem.status, func.count())
                .where(PunchItem.project_id == project_id)
                .group_by(PunchItem.status)
            )
        ).all()

        priority_rows = (
            await self.session.execute(
                select(PunchItem.priority, func.count())
                .where(PunchItem.project_id == project_id)
                .group_by(PunchItem.priority)
            )
        ).all()

        closed_rows = (
            await self.session.execute(
                select(
                    PunchItem.created_at,
                    PunchItem.verified_at,
                    PunchItem.resolved_at,
                    PunchItem.updated_at,
                ).where(
                    PunchItem.project_id == project_id,
                    PunchItem.status.in_(("closed", "verified")),
                )
            )
        ).all()

        return {
            "total": int(total),
            "by_status": {row[0]: row[1] for row in status_rows},
            "by_priority": {row[0]: row[1] for row in priority_rows},
            "closed_timestamps": list(closed_rows),
        }

    async def count_overdue(self, project_id: uuid.UUID) -> int:
        """Count punch items that are past due and not closed/verified."""
        now = datetime.now(UTC)
        stmt = select(func.count()).select_from(
            select(PunchItem)
            .where(
                PunchItem.project_id == project_id,
                PunchItem.due_date.isnot(None),
                PunchItem.due_date < now,
                PunchItem.status.notin_(["verified", "closed"]),
            )
            .subquery()
        )
        return (await self.session.execute(stmt)).scalar_one()

    async def count_open_critical(
        self,
        project_id: uuid.UUID,
        *,
        exclude_id: uuid.UUID | None = None,
    ) -> int:
        """Count critical punch items that are not yet verified or closed.

        Optionally excludes a specific item (the one being transitioned).
        """
        base = (
            select(PunchItem)
            .where(
                PunchItem.project_id == project_id,
                PunchItem.priority == "critical",
                PunchItem.status.notin_(["verified", "closed"]),
            )
        )
        if exclude_id is not None:
            base = base.where(PunchItem.id != exclude_id)
        stmt = select(func.count()).select_from(base.subquery())
        return (await self.session.execute(stmt)).scalar_one()
