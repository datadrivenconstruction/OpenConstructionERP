# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Lessons learned business logic: write, validate, confirm and look up "seen on N past projects"."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import accessible_project_ids
from app.modules.lessons_learned.logic import seen_on
from app.modules.lessons_learned.models import Lesson
from app.modules.lessons_learned.repository import LessonRepository
from app.modules.lessons_learned.schemas import (
    Finding,
    LessonCreate,
    LessonListResponse,
    LessonResponse,
    LessonUpdate,
    SeenLesson,
    SeenResponse,
)
from app.modules.lessons_learned.validators import evaluate

_TAGS = ("trade", "cost_code", "risk_category")


def _snapshot(lesson: Lesson) -> dict:
    return {
        "title": lesson.title,
        "description": lesson.description,
        "recommendation": lesson.recommendation,
        "trade": lesson.trade,
        "cost_code": lesson.cost_code,
        "risk_category": lesson.risk_category,
        "status": lesson.status,
    }


class LessonService:
    """Lessons of the projects the caller may reach."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = LessonRepository(session)

    async def _findings(self, lesson: Lesson) -> list[Finding]:
        failed = await evaluate(_snapshot(lesson), target_id=str(lesson.id))
        return [Finding(rule_id=r.rule_id, severity=r.severity.value, message=r.message) for r in failed]

    async def _out(self, lesson: Lesson) -> LessonResponse:
        out = LessonResponse.model_validate(lesson)
        out.findings = await self._findings(lesson)
        return out

    async def create(self, body: LessonCreate, user_id: str) -> LessonResponse:
        """Save a draft. Drafts may be incomplete: the findings tell the author what is missing."""
        data = body.model_dump()
        for key in ("title", "description", "recommendation", *_TAGS):
            data[key] = data[key].strip()
        lesson = await self.repo.add(Lesson(**data, status="draft", created_by=user_id))
        return await self._out(lesson)

    async def get(self, lesson_id: uuid.UUID) -> Lesson:
        lesson = await self.repo.get(lesson_id)
        if lesson is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Lesson not found")
        return lesson

    async def update(self, lesson: Lesson, body: LessonUpdate) -> LessonResponse:
        """Edit a lesson. Editing a confirmed lesson sends it back to draft for a fresh confirmation."""
        for key, value in body.model_dump(exclude_unset=True).items():
            if value is not None:
                setattr(lesson, key, value.strip() if isinstance(value, str) else value)
        if lesson.status == "confirmed":
            lesson.status = "draft"
            lesson.confirmed_by = None
            lesson.confirmed_at = None
        await self.session.flush()
        return await self._out(lesson)

    async def confirm(self, lesson: Lesson, user_id: str) -> LessonResponse:
        """Confirm a lesson so other projects see it. Validation errors block it."""
        if lesson.status == "confirmed":
            return await self._out(lesson)
        snap = _snapshot(lesson) | {"status": "confirmed"}
        failed = await evaluate(snap, target_id=str(lesson.id))
        blocking = [r for r in failed if r.severity.value == "error"]
        if blocking:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"code": "lesson_incomplete", "rules": [r.rule_id for r in blocking]},
            )
        lesson.status = "confirmed"
        lesson.confirmed_by = user_id
        lesson.confirmed_at = datetime.now(UTC)
        await self.session.flush()
        return await self._out(lesson)

    async def list_lessons(
        self,
        user_id: str,
        *,
        project_id: uuid.UUID | None,
        status_filter: str | None,
        offset: int = 0,
        limit: int = 200,
    ) -> LessonListResponse:
        ids = await accessible_project_ids(self.session, user_id)
        rows = await self.repo.list_lessons(
            project_ids=ids, project_id=project_id, status=status_filter, limit=limit, offset=offset
        )
        total = await self.repo.count_lessons(project_ids=ids, project_id=project_id, status=status_filter)
        return LessonListResponse(items=[await self._out(r) for r in rows], total=total, offset=offset, limit=limit)

    async def seen(
        self,
        user_id: str,
        *,
        project_id: uuid.UUID | None,
        trade: str | None,
        cost_code: str | None,
        risk_category: str | None,
    ) -> SeenResponse:
        """Distinct other projects with a confirmed lesson matching the situation."""
        ids = await accessible_project_ids(self.session, user_id)
        pool = await self.repo.confirmed_pool(ids)
        found = seen_on(
            pool, trade=trade, cost_code=cost_code, risk_category=risk_category, exclude_project_id=project_id
        )
        return SeenResponse(
            projects=found.projects,
            lessons=found.lessons,
            top=[
                SeenLesson(
                    id=le.id,
                    project_id=le.project_id,
                    title=le.title,
                    recommendation=le.recommendation,
                    impact=le.impact,
                    matched=hits,
                )
                for le, hits in found.top
            ],
        )
