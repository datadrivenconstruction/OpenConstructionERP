# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Field Time data access layer.

All database queries for field timesheets and their lines live here - pure data
access, no business logic (which stays in :class:`FieldTimeService`).
"""

from __future__ import annotations

import re
import uuid
from datetime import date

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy.orm.util import identity_key
from sqlalchemy.sql.elements import ClauseElement

from app.core.orm_write import apply_update
from app.modules.field_time.models import FieldTimesheet, FieldTimesheetLine

# Human reference format, e.g. "FT-000123".
_REFERENCE_PREFIX = "FT-"
_REFERENCE_RE = re.compile(r"(\d+)\s*$")


class FieldTimeRepository:
    """Data access for :class:`FieldTimesheet` and its lines."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Timesheet ────────────────────────────────────────────────────────────

    async def get_by_id(self, timesheet_id: uuid.UUID) -> FieldTimesheet | None:
        """Get a timesheet by id (lines eager-loaded via the selectin relationship)."""
        return await self.session.get(FieldTimesheet, timesheet_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        date_from: date | None = None,
        date_to: date | None = None,
        status: str | None = None,
    ) -> tuple[list[FieldTimesheet], int]:
        """List timesheets for a project with pagination and filters."""
        base = select(FieldTimesheet).where(FieldTimesheet.project_id == project_id)
        if date_from is not None:
            base = base.where(FieldTimesheet.date >= date_from)
        if date_to is not None:
            base = base.where(FieldTimesheet.date <= date_to)
        if status is not None:
            base = base.where(FieldTimesheet.status == status)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(FieldTimesheet.date.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), int(total)

    async def create(self, timesheet: FieldTimesheet) -> FieldTimesheet:
        """Insert a new timesheet."""
        self.session.add(timesheet)
        await self.session.flush()
        return timesheet

    async def update_fields(self, timesheet_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a timesheet."""
        stmt = update(FieldTimesheet).where(FieldTimesheet.id == timesheet_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        instance = self.session.identity_map.get(identity_key(FieldTimesheet, timesheet_id))
        if instance is None:
            return
        computed = [name for name, value in fields.items() if isinstance(value, ClauseElement)]
        for name, value in fields.items():
            if name not in computed:
                set_committed_value(instance, name, value)
        if computed:
            self.session.expire(instance, computed)

    async def delete(self, timesheet_id: uuid.UUID) -> None:
        """Hard delete a timesheet (cascades to its lines)."""
        timesheet = await self.get_by_id(timesheet_id)
        if timesheet is not None:
            await self.session.delete(timesheet)
            await self.session.flush()

    async def next_reference(self, project_id: uuid.UUID) -> str:
        """Return the next per-project human reference, e.g. ``FT-000042``.

        Derived from the highest numeric suffix already used in the project so a
        deleted draft never causes a duplicate (the ``(project_id, reference)``
        unique constraint would otherwise reject it).
        """
        stmt = select(FieldTimesheet.reference).where(FieldTimesheet.project_id == project_id)
        rows = (await self.session.execute(stmt)).scalars().all()
        highest = 0
        for ref in rows:
            match = _REFERENCE_RE.search(ref or "")
            if match:
                highest = max(highest, int(match.group(1)))
        return f"{_REFERENCE_PREFIX}{highest + 1:06d}"

    async def status_counts(self, project_id: uuid.UUID) -> dict[str, int]:
        """Return ``{status: count}`` for a project's timesheets."""
        rows = (
            await self.session.execute(
                select(FieldTimesheet.status, func.count())
                .where(FieldTimesheet.project_id == project_id)
                .group_by(FieldTimesheet.status),
            )
        ).all()
        return {row[0]: int(row[1]) for row in rows}

    # ── Lines ────────────────────────────────────────────────────────────────

    async def get_line(self, line_id: uuid.UUID) -> FieldTimesheetLine | None:
        """Get a single line by id."""
        return await self.session.get(FieldTimesheetLine, line_id)

    async def list_lines(self, timesheet_id: uuid.UUID) -> list[FieldTimesheetLine]:
        """Return all lines for a timesheet."""
        stmt = select(FieldTimesheetLine).where(FieldTimesheetLine.timesheet_id == timesheet_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def add_line(self, line: FieldTimesheetLine) -> FieldTimesheetLine:
        """Insert a new line."""
        self.session.add(line)
        await self.session.flush()
        return line

    async def update_line_fields(self, line_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a line."""
        await apply_update(self.session, FieldTimesheetLine, line_id, **fields)

    async def delete_line(self, line_id: uuid.UUID) -> None:
        """Hard delete a single line."""
        line = await self.get_line(line_id)
        if line is not None:
            await self.session.delete(line)
            await self.session.flush()
