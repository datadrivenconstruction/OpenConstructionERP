# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Commissioning (Cx) data access layer.

All database queries for systems, checklists, items and issues live here. No
business logic - pure data access. Readiness scoring is computed by the pure
helpers in :mod:`app.modules.commissioning.validators` from the aggregate
status counts returned by :meth:`SystemRepository.functional_status_counts`.
"""

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy.orm.util import identity_key
from sqlalchemy.sql.elements import ClauseElement

from app.modules.commissioning.models import (
    CxChecklist,
    CxChecklistItem,
    CxIssue,
    CxSystem,
)


class SystemRepository:
    """Data access for :class:`CxSystem`."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, system_id: uuid.UUID) -> CxSystem | None:
        """Get a system by ID."""
        return await self.session.get(CxSystem, system_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
        system_type: str | None = None,
    ) -> tuple[list[CxSystem], int]:
        """List systems for a project with pagination and optional filters."""
        base = select(CxSystem).where(CxSystem.project_id == project_id)
        if status is not None:
            base = base.where(CxSystem.status == status)
        if system_type is not None:
            base = base.where(CxSystem.system_type == system_type)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(CxSystem.name.asc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def create(self, system: CxSystem) -> CxSystem:
        """Insert a new system."""
        self.session.add(system)
        await self.session.flush()
        return system

    async def update_fields(self, system_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a system."""
        stmt = update(CxSystem).where(CxSystem.id == system_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        instance = self.session.identity_map.get(identity_key(CxSystem, system_id))
        if instance is None:
            return
        computed = [name for name, value in fields.items() if isinstance(value, ClauseElement)]
        for name, value in fields.items():
            if name not in computed:
                set_committed_value(instance, name, value)
        if computed:
            self.session.expire(instance, computed)

    async def delete(self, system_id: uuid.UUID) -> None:
        """Delete a system (cascades to its checklists, items and issues)."""
        system = await self.session.get(CxSystem, system_id)
        if system is not None:
            await self.session.delete(system)
            await self.session.flush()

    async def functional_status_counts(
        self,
        system_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, dict[str, int]]:
        """Count functional checklist items per (system, item-status).

        Returns ``{system_id: {item_status: count}}`` covering only checklists
        whose ``kind == 'functional'``. Systems with no functional items are
        absent from the map (the caller treats a missing entry as all-zero).
        """
        if not system_ids:
            return {}
        stmt = (
            select(CxChecklist.system_id, CxChecklistItem.status, func.count())
            .join(CxChecklist, CxChecklistItem.checklist_id == CxChecklist.id)
            .where(
                CxChecklist.system_id.in_(system_ids),
                CxChecklist.kind == "functional",
            )
            .group_by(CxChecklist.system_id, CxChecklistItem.status)
        )
        rows = (await self.session.execute(stmt)).all()
        out: dict[uuid.UUID, dict[str, int]] = {}
        for system_id, item_status, count in rows:
            out.setdefault(system_id, {})[item_status] = count
        return out

    async def open_critical_issue_counts(
        self,
        system_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, int]:
        """Count open ``critical`` issues per system for the given systems."""
        if not system_ids:
            return {}
        stmt = (
            select(CxIssue.system_id, func.count())
            .where(
                CxIssue.system_id.in_(system_ids),
                CxIssue.severity == "critical",
                CxIssue.status == "open",
            )
            .group_by(CxIssue.system_id)
        )
        rows = (await self.session.execute(stmt)).all()
        return {system_id: count for system_id, count in rows}

    async def stats_for_project(self, project_id: uuid.UUID) -> dict:
        """Aggregate commissioning statistics for a project.

        Returns a dict with keys: total_systems, by_status, by_type,
        commissioned, open_issues, open_critical_issues.
        """
        total_stmt = select(func.count()).select_from(CxSystem).where(CxSystem.project_id == project_id)
        total = (await self.session.execute(total_stmt)).scalar_one()

        status_stmt = (
            select(CxSystem.status, func.count()).where(CxSystem.project_id == project_id).group_by(CxSystem.status)
        )
        by_status = {row[0]: row[1] for row in (await self.session.execute(status_stmt)).all()}

        type_stmt = (
            select(CxSystem.system_type, func.count())
            .where(CxSystem.project_id == project_id)
            .group_by(CxSystem.system_type)
        )
        by_type = {row[0]: row[1] for row in (await self.session.execute(type_stmt)).all()}

        # Open issue counts join back to the project via the owning system.
        open_stmt = (
            select(func.count())
            .select_from(CxIssue)
            .join(CxSystem, CxIssue.system_id == CxSystem.id)
            .where(CxSystem.project_id == project_id, CxIssue.status == "open")
        )
        open_issues = (await self.session.execute(open_stmt)).scalar_one()

        open_crit_stmt = (
            select(func.count())
            .select_from(CxIssue)
            .join(CxSystem, CxIssue.system_id == CxSystem.id)
            .where(
                CxSystem.project_id == project_id,
                CxIssue.status == "open",
                CxIssue.severity == "critical",
            )
        )
        open_critical = (await self.session.execute(open_crit_stmt)).scalar_one()

        return {
            "total_systems": total,
            "by_status": by_status,
            "by_type": by_type,
            "commissioned": by_status.get("commissioned", 0),
            "open_issues": open_issues,
            "open_critical_issues": open_critical,
        }


class ChecklistRepository:
    """Data access for :class:`CxChecklist`."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, checklist_id: uuid.UUID) -> CxChecklist | None:
        """Get a checklist by ID."""
        return await self.session.get(CxChecklist, checklist_id)

    async def list_for_system(
        self,
        system_id: uuid.UUID,
        *,
        kind: str | None = None,
    ) -> list[CxChecklist]:
        """List checklists for a system, optionally filtered by kind."""
        stmt = select(CxChecklist).where(CxChecklist.system_id == system_id)
        if kind is not None:
            stmt = stmt.where(CxChecklist.kind == kind)
        stmt = stmt.order_by(CxChecklist.kind.asc(), CxChecklist.created_at.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, checklist: CxChecklist) -> CxChecklist:
        """Insert a new checklist."""
        self.session.add(checklist)
        await self.session.flush()
        return checklist

    async def update_fields(self, checklist_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a checklist."""
        stmt = update(CxChecklist).where(CxChecklist.id == checklist_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        instance = self.session.identity_map.get(identity_key(CxChecklist, checklist_id))
        if instance is None:
            return
        computed = [name for name, value in fields.items() if isinstance(value, ClauseElement)]
        for name, value in fields.items():
            if name not in computed:
                set_committed_value(instance, name, value)
        if computed:
            self.session.expire(instance, computed)

    async def delete(self, checklist_id: uuid.UUID) -> None:
        """Delete a checklist (cascades to its items)."""
        checklist = await self.session.get(CxChecklist, checklist_id)
        if checklist is not None:
            await self.session.delete(checklist)
            await self.session.flush()


class ItemRepository:
    """Data access for :class:`CxChecklistItem`."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, item_id: uuid.UUID) -> CxChecklistItem | None:
        """Get a checklist item by ID."""
        return await self.session.get(CxChecklistItem, item_id)

    async def list_for_checklist(self, checklist_id: uuid.UUID) -> list[CxChecklistItem]:
        """List items for a checklist ordered by sequence."""
        stmt = (
            select(CxChecklistItem)
            .where(CxChecklistItem.checklist_id == checklist_id)
            .order_by(CxChecklistItem.sequence.asc(), CxChecklistItem.created_at.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, item: CxChecklistItem) -> CxChecklistItem:
        """Insert a new checklist item."""
        self.session.add(item)
        await self.session.flush()
        return item

    async def update_fields(self, item_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a checklist item."""
        stmt = update(CxChecklistItem).where(CxChecklistItem.id == item_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        instance = self.session.identity_map.get(identity_key(CxChecklistItem, item_id))
        if instance is None:
            return
        computed = [name for name, value in fields.items() if isinstance(value, ClauseElement)]
        for name, value in fields.items():
            if name not in computed:
                set_committed_value(instance, name, value)
        if computed:
            self.session.expire(instance, computed)

    async def delete(self, item_id: uuid.UUID) -> None:
        """Delete a checklist item."""
        item = await self.session.get(CxChecklistItem, item_id)
        if item is not None:
            await self.session.delete(item)
            await self.session.flush()


class IssueRepository:
    """Data access for :class:`CxIssue`."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, issue_id: uuid.UUID) -> CxIssue | None:
        """Get an issue by ID."""
        return await self.session.get(CxIssue, issue_id)

    async def list_for_system(
        self,
        system_id: uuid.UUID,
        *,
        status: str | None = None,
    ) -> list[CxIssue]:
        """List issues for a system, optionally filtered by status."""
        stmt = select(CxIssue).where(CxIssue.system_id == system_id)
        if status is not None:
            stmt = stmt.where(CxIssue.status == status)
        # Open first, then most-recent, so the highest-priority work surfaces.
        stmt = stmt.order_by(CxIssue.status.asc(), CxIssue.created_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, issue: CxIssue) -> CxIssue:
        """Insert a new issue."""
        self.session.add(issue)
        await self.session.flush()
        return issue

    async def update_fields(self, issue_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on an issue."""
        stmt = update(CxIssue).where(CxIssue.id == issue_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        instance = self.session.identity_map.get(identity_key(CxIssue, issue_id))
        if instance is None:
            return
        computed = [name for name, value in fields.items() if isinstance(value, ClauseElement)]
        for name, value in fields.items():
            if name not in computed:
                set_committed_value(instance, name, value)
        if computed:
            self.session.expire(instance, computed)

    async def delete(self, issue_id: uuid.UUID) -> None:
        """Delete an issue."""
        issue = await self.session.get(CxIssue, issue_id)
        if issue is not None:
            await self.session.delete(issue)
            await self.session.flush()
