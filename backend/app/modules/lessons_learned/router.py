# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Lessons learned API routes (mounted at ``/api/v1/lessons_learned``).

Every lesson belongs to a project; reads and writes need access to that project. The cross-project lookup
(``/seen``) only counts projects the caller can reach, so it never discloses a project the caller cannot open.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.lessons_learned.schemas import (
    LessonCreate,
    LessonListResponse,
    LessonResponse,
    LessonStatus,
    LessonUpdate,
    SeenResponse,
)
from app.modules.lessons_learned.service import LessonService

router = APIRouter(tags=["lessons_learned"])

_READ = Depends(RequirePermission("lessons_learned.read"))
_CREATE = Depends(RequirePermission("lessons_learned.create"))
_UPDATE = Depends(RequirePermission("lessons_learned.update"))
_CONFIRM = Depends(RequirePermission("lessons_learned.confirm"))
_DELETE = Depends(RequirePermission("lessons_learned.delete"))


@router.get("/", response_model=LessonListResponse, dependencies=[_READ])
async def list_lessons(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID | None = None,
    status_filter: LessonStatus | None = Query(default=None, alias="status"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
) -> LessonListResponse:
    """Lessons of one project, or of every project the caller can reach."""
    if project_id is not None:
        await verify_project_access(project_id, user_id, session)
    return await LessonService(session).list_lessons(
        user_id, project_id=project_id, status_filter=status_filter, offset=offset, limit=limit
    )


@router.get("/seen", response_model=SeenResponse, dependencies=[_READ])
async def seen_on_past_projects(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID | None = None,
    trade: str | None = Query(default=None, max_length=100),
    cost_code: str | None = Query(default=None, max_length=100),
    risk_category: str | None = Query(default=None, max_length=50),
) -> SeenResponse:
    """How many other projects have a confirmed lesson for this trade, cost code or risk category."""
    if project_id is not None:
        await verify_project_access(project_id, user_id, session)
    return await LessonService(session).seen(
        user_id, project_id=project_id, trade=trade, cost_code=cost_code, risk_category=risk_category
    )


@router.post("/", response_model=LessonResponse, status_code=status.HTTP_201_CREATED, dependencies=[_CREATE])
async def create_lesson(body: LessonCreate, session: SessionDep, user_id: CurrentUserId) -> LessonResponse:
    """Capture a lesson as a draft."""
    await verify_project_access(body.project_id, user_id, session)
    out = await LessonService(session).create(body, user_id)
    await session.commit()
    return out


@router.patch("/{lesson_id}", response_model=LessonResponse, dependencies=[_UPDATE])
async def update_lesson(
    lesson_id: uuid.UUID, body: LessonUpdate, session: SessionDep, user_id: CurrentUserId
) -> LessonResponse:
    """Edit a lesson; a confirmed lesson returns to draft."""
    svc = LessonService(session)
    lesson = await svc.get(lesson_id)
    await verify_project_access(lesson.project_id, user_id, session)
    out = await svc.update(lesson, body)
    await session.commit()
    return out


@router.post("/{lesson_id}/confirm", response_model=LessonResponse, dependencies=[_CONFIRM])
async def confirm_lesson(lesson_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> LessonResponse:
    """Confirm a lesson so other projects see it (blocked while validation errors remain)."""
    svc = LessonService(session)
    lesson = await svc.get(lesson_id)
    await verify_project_access(lesson.project_id, user_id, session)
    out = await svc.confirm(lesson, user_id)
    await session.commit()
    return out


@router.delete("/{lesson_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[_DELETE])
async def delete_lesson(lesson_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> None:
    """Delete a lesson."""
    svc = LessonService(session)
    lesson = await svc.get(lesson_id)
    await verify_project_access(lesson.project_id, user_id, session)
    await svc.repo.delete(lesson)
    await session.commit()
