"""Meetings data access layer.

All database queries for meetings live here.
No business logic — pure data access.
"""

import uuid

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.meetings.models import Meeting


class MeetingRepository:
    """Data access for Meeting models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, meeting_id: uuid.UUID) -> Meeting | None:
        """Get meeting by ID."""
        return await self.session.get(Meeting, meeting_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        meeting_type: str | None = None,
        status: str | None = None,
        search: str | None = None,
        sort_by: str | None = None,
        sort_order: str = "desc",
    ) -> tuple[list[Meeting], int]:
        """List meetings for a project with pagination, filters, and search."""
        base = select(Meeting).where(Meeting.project_id == project_id)
        if meeting_type is not None:
            base = base.where(Meeting.meeting_type == meeting_type)
        if status is not None:
            base = base.where(Meeting.status == status)

        # Free-text search across title, agenda, minutes, and meeting number
        if search and search.strip():
            pattern = f"%{search.strip()}%"
            base = base.where(
                or_(
                    Meeting.title.ilike(pattern),
                    Meeting.agenda.ilike(pattern),
                    Meeting.minutes.ilike(pattern),
                    Meeting.meeting_number.ilike(pattern),
                )
            )

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        # Sorting
        order_clause = None
        if sort_by:
            col = getattr(Meeting, sort_by, None)
            if col is not None:
                order_clause = col.desc() if sort_order == "desc" else col.asc()
        if order_clause is None:
            order_clause = Meeting.meeting_date.desc()

        stmt = base.order_by(order_clause).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def next_meeting_number(self, project_id: uuid.UUID) -> str:
        """Generate the next meeting number using MAX to avoid duplicates."""
        from sqlalchemy import Integer as SAInteger
        from sqlalchemy import cast
        from sqlalchemy.sql import func as sqlfunc

        stmt = (
            select(
                sqlfunc.coalesce(
                    sqlfunc.max(
                        cast(
                            func.substr(Meeting.meeting_number, 5),
                            SAInteger,
                        )
                    ),
                    0,
                )
            )
            .where(Meeting.project_id == project_id)
        )
        max_num = (await self.session.execute(stmt)).scalar_one()
        return f"MTG-{max_num + 1:03d}"

    async def create(self, meeting: Meeting) -> Meeting:
        """Insert a new meeting."""
        self.session.add(meeting)
        await self.session.flush()
        return meeting

    async def update_fields(self, meeting_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a meeting."""
        stmt = update(Meeting).where(Meeting.id == meeting_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, meeting_id: uuid.UUID) -> None:
        """Hard delete a meeting."""
        meeting = await self.get_by_id(meeting_id)
        if meeting is not None:
            await self.session.delete(meeting)
            await self.session.flush()

    async def stats_for_project(self, project_id: uuid.UUID) -> dict:
        """Compute aggregate meeting statistics for a project.

        Returns dict with total, by_status, by_type, and next_meeting_date.
        open_action_items_count is computed separately in the service layer
        because action_items is a JSON column that requires Python-level parsing.
        """
        # Total
        total_stmt = (
            select(func.count())
            .select_from(Meeting)
            .where(Meeting.project_id == project_id)
        )
        total = (await self.session.execute(total_stmt)).scalar_one()

        # By status
        status_stmt = (
            select(Meeting.status, func.count())
            .where(Meeting.project_id == project_id)
            .group_by(Meeting.status)
        )
        status_rows = (await self.session.execute(status_stmt)).all()
        by_status = {row[0]: row[1] for row in status_rows}

        # By type
        type_stmt = (
            select(Meeting.meeting_type, func.count())
            .where(Meeting.project_id == project_id)
            .group_by(Meeting.meeting_type)
        )
        type_rows = (await self.session.execute(type_stmt)).all()
        by_type = {row[0]: row[1] for row in type_rows}

        # Next upcoming meeting (meeting_date >= today, ordered ASC, limit 1)
        from datetime import UTC, datetime

        today_str = datetime.now(UTC).strftime("%Y-%m-%d")
        next_stmt = (
            select(Meeting.meeting_date)
            .where(Meeting.project_id == project_id)
            .where(Meeting.meeting_date >= today_str)
            .where(Meeting.status.in_(("draft", "scheduled", "in_progress")))
            .order_by(Meeting.meeting_date.asc())
            .limit(1)
        )
        next_date = (await self.session.execute(next_stmt)).scalar_one_or_none()

        return {
            "total": total,
            "by_status": by_status,
            "by_type": by_type,
            "next_meeting_date": next_date,
        }

    async def all_for_project(self, project_id: uuid.UUID) -> list[Meeting]:
        """Load all meetings for a project (used for action item extraction).

        Only loads non-cancelled meetings to avoid scanning completed+cancelled
        meetings that should not have active action items.
        """
        stmt = (
            select(Meeting)
            .where(Meeting.project_id == project_id)
            .where(Meeting.status.notin_(("cancelled",)))
            .order_by(Meeting.meeting_date.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
