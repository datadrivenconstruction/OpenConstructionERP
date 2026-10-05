# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Trainer API routes, mounted at ``/api/v1/trainer``.

Trailing slashes follow decision 31 exactly, because the app runs with
``redirect_slashes=False`` and a mismatch is a 404, not a redirect:
``/public/status/`` carries a slash, every learner route carries none. The
frontend ``TRAINER_PATHS`` table (``frontend/src/features/trainer/api.ts``)
is pinned against this router by ``tests/unit/trainer/test_trainer_routes_match_the_frontend.py``.

| Method | Path | Auth | Response |
|---|---|---|---|
| GET | ``/public/status/`` | public | ``PublicStatus`` (200 also when the flag is off) |
| POST | ``/webhook/`` | HMAC, per-IP limit | ``{status}`` |
| GET | ``/me`` | trainer.learn | ``TrainerMe`` (404: no enrolment) |
| GET | ``/tasks/{task_id}`` | trainer.learn | ``TaskView`` |
| PUT | ``/tasks/{task_id}/answers`` | trainer.learn | ``AnswersSaved`` |
| POST | ``/tasks/{task_id}/check`` | trainer.learn, per-user limit | ``AttemptResult`` |
| GET | ``/tasks/{task_id}/readback`` | trainer.learn | ``ReadbackResponse`` |
| POST | ``/tasks/{task_id}/hints/reveal`` | trainer.learn | ``HintRevealResult`` |
| POST | ``/unlocks/{lock_id}/seen`` | trainer.learn | 204 |
| GET | ``/admin/enrolments/`` | trainer.admin | ``list[AdminEnrolmentOut]`` |
| POST | ``/admin/enrolments/`` | trainer.admin | ``AdminEnrolmentOut`` (201) |
| POST | ``/admin/enrolments/{id}/reseed`` | trainer.admin | ``AdminEnrolmentOut`` |
| GET | ``/admin/courses/`` | trainer.admin | ``list[AdminCourseOut]`` |
| POST | ``/courses/reload/`` | trainer.admin | ``list[CourseLoadReport]`` |

Every route except the public status answers 404 while the academy flag is
off, before authentication runs: an install without the flag shows no
trainer surface at all. The public status answers ``academy_mode: false``
instead, because the sign-in page reads it on every install.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select

from app.config import Settings, get_settings
from app.core.rate_limiter import RateLimiter, client_identifier
from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.trainer.schemas import (
    AdminEnrolmentCreate,
    AdminEnrolmentOut,
    AnswersPut,
    AnswersSaved,
    AttemptResult,
    CheckRequest,
    HintRevealResult,
    PublicStatus,
    ReadbackResponse,
    TaskView,
    TrainerMe,
)
from app.modules.trainer.service import TrainerService, reseed_enrolment, seed_on_enrol

#: Store deliveries per client IP and minute. A store sends a handful per
#: order; this only stops a flood, and every rejected delivery writes a row.
webhook_limiter = RateLimiter(max_requests=30, window_seconds=60)

#: "Check my work" per learner and minute (design §7). A check runs probes and
#: may recompute a levelling table, so it is the expensive call.
check_limiter = RateLimiter(max_requests=6, window_seconds=60)


async def require_academy_mode() -> None:
    """404 unless the academy flag is on. Runs before authentication."""
    if not get_settings().academy_mode:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")


def _too_many() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="rate_limited",
        headers={"Retry-After": "60"},
    )


SettingsDep = Annotated[Settings, Depends(get_settings)]

router = APIRouter(tags=["Trainer"])

# ── Public ───────────────────────────────────────────────────────────────────


@router.get("/public/status/", response_model=PublicStatus)
async def public_status(settings: SettingsDep) -> PublicStatus:
    """Whether this box is an academy box, readable before sign-in (design §9.3)."""
    if not settings.academy_mode:
        return PublicStatus(academy_mode=False, store_url=None)
    return PublicStatus(academy_mode=True, store_url=settings.trainer_store_url or None)


async def _webhook_rate_limit(request: Request) -> None:
    allowed, _remaining = webhook_limiter.is_allowed(client_identifier(request))
    if not allowed:
        raise _too_many()


@router.post(
    "/webhook/",
    response_model=None,
    dependencies=[Depends(require_academy_mode), Depends(_webhook_rate_limit)],
)
async def store_webhook(request: Request, session: SessionDep, settings: SettingsDep) -> JSONResponse:
    """A store delivery: HMAC over the raw body, idempotent per event id (design §8)."""
    from app.modules.trainer.webhook import handle_webhook

    raw_body = await request.body()
    outcome = await handle_webhook(
        session,
        settings,
        raw_body=raw_body,
        headers=request.headers,
        seed_on_enrol=seed_on_enrol,
    )
    return JSONResponse(outcome.body(), status_code=outcome.http_status)


# ── Learner ──────────────────────────────────────────────────────────────────

#: Learner routes: the flag first (404 before authentication), then the permission.
LEARNER = [Depends(require_academy_mode), Depends(RequirePermission("trainer.learn"))]


@router.get("/me", response_model=TrainerMe, dependencies=LEARNER)
async def get_me(session: SessionDep, user_id: CurrentUserId, settings: SettingsDep) -> TrainerMe:
    """The learner's running course. 404 when the learner has none."""
    return await TrainerService(session, settings).get_me(user_id)


@router.get("/tasks/{task_id}", response_model=TaskView, dependencies=LEARNER)
async def get_task(task_id: str, session: SessionDep, user_id: CurrentUserId, settings: SettingsDep) -> TaskView:
    """One task, without a single expected value."""
    return await TrainerService(session, settings).get_task_view(user_id, task_id)


@router.put("/tasks/{task_id}/answers", response_model=AnswersSaved, dependencies=LEARNER)
async def put_answers(
    task_id: str, body: AnswersPut, session: SessionDep, user_id: CurrentUserId, settings: SettingsDep
) -> AnswersSaved:
    """Replace the task's whole answer set (decision 28). 409 on a stale revision."""
    return await TrainerService(session, settings).put_answers(user_id, task_id, body)


@router.post("/tasks/{task_id}/check", response_model=AttemptResult, dependencies=LEARNER)
async def check_task(
    task_id: str, body: CheckRequest, session: SessionDep, user_id: CurrentUserId, settings: SettingsDep
) -> AttemptResult:
    """Grade the saved answers and the learner's project (decision 29)."""
    allowed, _remaining = check_limiter.is_allowed(f"check:{user_id}")
    if not allowed:
        raise _too_many()
    return await TrainerService(session, settings).check(user_id, task_id, body)


@router.get("/tasks/{task_id}/readback", response_model=ReadbackResponse, dependencies=LEARNER)
async def get_readback(
    task_id: str, session: SessionDep, user_id: CurrentUserId, settings: SettingsDep
) -> ReadbackResponse:
    """What the ERP holds now, read-only (decision 36)."""
    return await TrainerService(session, settings).readback(user_id, task_id)


@router.post("/tasks/{task_id}/hints/reveal", response_model=HintRevealResult, dependencies=LEARNER)
async def reveal_hint(
    task_id: str, session: SessionDep, user_id: CurrentUserId, settings: SettingsDep
) -> HintRevealResult:
    """Reveal the next hint (decision 30); idempotent at the last one."""
    return await TrainerService(session, settings).reveal_hint(user_id, task_id)


@router.post(
    "/unlocks/{lock_id}/seen", status_code=status.HTTP_204_NO_CONTENT, response_class=Response, dependencies=LEARNER
)
async def unlock_seen(lock_id: str, session: SessionDep, user_id: CurrentUserId, settings: SettingsDep) -> Response:
    """The learner closed the unlock dialog of ``lock_id``. Idempotent."""
    await TrainerService(session, settings).mark_unlock_seen(user_id, lock_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Admin ────────────────────────────────────────────────────────────────────


class AdminCourseOut(BaseModel):
    """One stored course row, valid or not (decision 26)."""

    id: uuid.UUID
    course_key: str
    version: str
    title: str
    country: str
    language: str
    status: str
    source_file: str
    loaded_at: datetime
    errors: list[str]


class CourseLoadReport(BaseModel):
    """What a reload did to one course file."""

    source_file: str
    status: str
    course_key: str | None
    version: str | None
    errors: list[str]


#: Admin routes: the flag first, then the admin permission.
ADMIN = [Depends(require_academy_mode), Depends(RequirePermission("trainer.admin"))]


@router.get("/admin/enrolments/", response_model=list[AdminEnrolmentOut], dependencies=ADMIN)
async def admin_list_enrolments(
    session: SessionDep,
    settings: SettingsDep,
    status_filter: Annotated[
        Literal["queued", "provisioning", "active", "completed", "suspended", "revoked", "failed"] | None,
        Query(alias="status"),
    ] = None,
    email: Annotated[str | None, Query(max_length=255)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AdminEnrolmentOut]:
    """Enrolments, newest first."""
    return await TrainerService(session, settings).admin_list(
        status_filter=status_filter, email=email, limit=limit, offset=offset
    )


_PROVISIONING_ERRORS: dict[str, int] = {
    "disabled": status.HTTP_404_NOT_FOUND,
    "ignored": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "failed": status.HTTP_409_CONFLICT,
}


@router.post(
    "/admin/enrolments/", response_model=AdminEnrolmentOut, status_code=status.HTTP_201_CREATED, dependencies=ADMIN
)
async def admin_create_enrolment(
    body: AdminEnrolmentCreate, session: SessionDep, settings: SettingsDep
) -> AdminEnrolmentOut:
    """Provision a learner by hand: the same path as a paid order, ``source="admin"``."""
    from app.modules.trainer.provisioning import complete_provisioning, provision_learner

    result = await provision_learner(
        session,
        settings,
        email=str(body.email),
        name=body.full_name,
        locale=body.locale,
        course_keys=[body.course_key],
        source="admin",
    )
    if result.status != "processed" or not result.enrolments:
        await session.rollback()
        raise HTTPException(
            status_code=_PROVISIONING_ERRORS.get(result.status, status.HTTP_409_CONFLICT),
            detail=result.error or result.status,
        )
    await session.commit()
    await complete_provisioning(session, settings, result, seed_on_enrol=seed_on_enrol)
    return await TrainerService(session, settings).admin_enrolment_out(result.enrolments[0].enrolment_id)


@router.post("/admin/enrolments/{enrolment_id}/reseed", response_model=AdminEnrolmentOut, dependencies=ADMIN)
async def admin_reseed_enrolment(
    enrolment_id: uuid.UUID, session: SessionDep, settings: SettingsDep
) -> AdminEnrolmentOut:
    """Retry a failed seed (decision 41); the "ready" email follows a success."""
    return await reseed_enrolment(session, settings, enrolment_id)


@router.get("/admin/courses/", response_model=list[AdminCourseOut], dependencies=ADMIN)
async def admin_list_courses(session: SessionDep) -> list[AdminCourseOut]:
    """Every stored course row, invalid ones with their errors (decision 26)."""
    from app.modules.trainer.models import TrainerCourse

    rows = await session.execute(select(TrainerCourse).order_by(TrainerCourse.course_key, TrainerCourse.version))
    return [
        AdminCourseOut(
            id=row.id,
            course_key=row.course_key,
            version=row.version,
            title=row.title,
            country=row.country,
            language=row.language,
            status=row.status,
            source_file=row.source_file,
            loaded_at=row.loaded_at,
            errors=_report_errors(row.validation_report),
        )
        for row in rows.scalars().all()
    ]


def _report_errors(report: Any) -> list[str]:
    if not isinstance(report, dict):
        return []
    errors = report.get("error_list")
    return [str(e) for e in errors] if isinstance(errors, list) else []


@router.post("/courses/reload/", response_model=list[CourseLoadReport], dependencies=ADMIN)
async def reload_courses(session: SessionDep) -> list[CourseLoadReport]:
    """Reload the course files from ``OE_TRAINER_COURSES_DIR`` (decision 35)."""
    from app.modules.trainer.loader import SqlCourseStore, load_courses_dir

    outcomes = await load_courses_dir(SqlCourseStore(session))
    await session.commit()
    return [
        CourseLoadReport(
            source_file=o.source_file,
            status=o.status,
            course_key=o.course_key,
            version=o.version,
            errors=list(o.errors),
        )
        for o in outcomes
    ]
