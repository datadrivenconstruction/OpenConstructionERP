"""Meetings data access layer.

All database queries for meetings live here.
No business logic — pure data access.
"""

import uuid

from sqlalchemy import func, select, update
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
    ) -> tuple[list[Meeting], int]:
        """List meetings for a project with pagination and filters."""
        base = select(Meeting).where(Meeting.project_id == project_id)
        if meeting_type is not None:
            base = base.where(Meeting.meeting_type == meeting_type)
        if status is not None:
            base = base.where(Meeting.status == status)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(Meeting.meeting_date.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def next_meeting_number(self, project_id: uuid.UUID) -> str:
        """Generate the next meeting number for a project (MTG-001, MTG-002, ...)."""
        stmt = (
            select(func.count())
            .select_from(Meeting)
            .where(Meeting.project_id == project_id)
        )
        count = (await self.session.execute(stmt)).scalar_one()
        return f"MTG-{count + 1:03d}"

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
