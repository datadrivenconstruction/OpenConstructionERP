# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Lessons learned data access."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.lessons_learned.models import Lesson

# Hard ceiling for one cross-project lookup; matching runs in Python over these rows.
SEEN_SCAN_LIMIT = 5000


class LessonRepository:
    """CRUD and scoped listing of lessons."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, lesson_id: uuid.UUID) -> Lesson | None:
        return await self.session.get(Lesson, lesson_id)

    async def add(self, lesson: Lesson) -> Lesson:
        self.session.add(lesson)
        await self.session.flush()
        return lesson

    async def delete(self, lesson: Lesson) -> None:
        await self.session.delete(lesson)
        await self.session.flush()

    async def list_lessons(
        self,
        *,
        project_ids: set[uuid.UUID] | None,
        project_id: uuid.UUID | None = None,
        status: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[Lesson]:
        """Lessons of one project, or of every project in ``project_ids`` (``None`` = unrestricted)."""
        stmt = select(Lesson).order_by(Lesson.created_at.desc(), Lesson.id).limit(limit).offset(offset)
        stmt = self._scope(stmt, project_ids, project_id, status)
        return list((await self.session.execute(stmt)).scalars().all())

    async def count_lessons(
        self, *, project_ids: set[uuid.UUID] | None, project_id: uuid.UUID | None = None, status: str | None = None
    ) -> int:
        stmt = self._scope(select(func.count()).select_from(Lesson), project_ids, project_id, status)
        return int((await self.session.execute(stmt)).scalar_one())

    @staticmethod
    def _scope(
        stmt: Select[Any], project_ids: set[uuid.UUID] | None, project_id: uuid.UUID | None, status: str | None
    ) -> Select[Any]:
        if project_id is not None:
            stmt = stmt.where(Lesson.project_id == project_id)
        elif project_ids is not None:
            stmt = stmt.where(Lesson.project_id.in_(project_ids))
        if status:
            stmt = stmt.where(Lesson.status == status)
        return stmt

    async def confirmed_pool(self, project_ids: set[uuid.UUID] | None) -> list[Lesson]:
        """Confirmed lessons of the projects the caller may see, the pool "seen on" is computed from."""
        stmt = select(Lesson).where(Lesson.status == "confirmed").limit(SEEN_SCAN_LIMIT)
        if project_ids is not None:
            stmt = stmt.where(Lesson.project_id.in_(project_ids))
        return list((await self.session.execute(stmt)).scalars().all())
