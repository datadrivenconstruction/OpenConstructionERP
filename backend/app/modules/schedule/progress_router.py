# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Progress-rigor API (T3.2).

Typed progress, weighted steps, suspend/resume, per-activity calendar and a
read-only time-phased planned-value preview. Mounted under the same
``/api/v1/schedule`` prefix as the core schedule router (``router.include_router``).

Every endpoint resolves the owning project from the activity / step / schedule
and runs ``verify_project_access`` (404 on cross-tenant access, existence-oracle
safe) before doing any work. Permissions reuse the existing ``schedule.read`` /
``schedule.update`` grants - no new permission keys.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response, status

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.schedule.progress_schemas import (
    ActivityProgressStateResponse,
    CalendarSetRequest,
    PercentTypePreviewResponse,
    PercentTypeRequest,
    PlannedValueResponse,
    ProgressResultResponse,
    ResumeRequest,
    StepCreate,
    StepPatch,
    StepResponse,
    SuspendRequest,
    TypedProgressRequest,
)
from app.modules.schedule.progress_service import ProgressOutcome, ScheduleProgressService
from app.modules.schedule.service import _str_to_float

progress_router = APIRouter(tags=["schedule"])


def _get_service(session: SessionDep) -> ScheduleProgressService:
    return ScheduleProgressService(session)


# ── IDOR helpers (resolve project, then verify_project_access) ────────────────


async def _verify_activity(
    service: ScheduleProgressService,
    session: SessionDep,
    activity_id: uuid.UUID,
    user_id: str,
) -> object:
    activity = await service.get_activity(activity_id)
    schedule = await service.get_schedule(activity.schedule_id)
    await verify_project_access(schedule.project_id, user_id, session)
    return activity


async def _verify_step(
    service: ScheduleProgressService,
    session: SessionDep,
    step_id: uuid.UUID,
    user_id: str,
) -> object:
    step = await service.get_step(step_id)
    activity = await service.get_activity(step.activity_id)
    schedule = await service.get_schedule(activity.schedule_id)
    await verify_project_access(schedule.project_id, user_id, session)
    return step


async def _verify_schedule(
    service: ScheduleProgressService,
    session: SessionDep,
    schedule_id: uuid.UUID,
    user_id: str,
) -> object:
    schedule = await service.get_schedule(schedule_id)
    await verify_project_access(schedule.project_id, user_id, session)
    return schedule


# ── Response builders ─────────────────────────────────────────────────────────


def _outcome_to_response(outcome: ProgressOutcome) -> ProgressResultResponse:
    return ProgressResultResponse(
        activity_id=outcome.activity.id,
        percent_complete_type=outcome.pct_type,
        percent_complete=float(outcome.result.percent_complete),
        remaining_duration=outcome.result.remaining_duration,
        forecast_finish=outcome.result.forecast_finish_iso,
        status=outcome.result.status,
        evm_warnings=outcome.warnings,
        installed_units=outcome.activity.installed_units,
        budgeted_units=outcome.activity.budgeted_units,
        suspended_at=outcome.activity.suspended_at,
        suspend_reason=outcome.activity.suspend_reason,
    )


def _step_to_response(step: object) -> StepResponse:
    return StepResponse(
        id=step.id,
        activity_id=step.activity_id,
        name=step.name,
        weight=float(step.weight),
        percent_complete=float(step.percent_complete),
        sort_order=step.sort_order,
        is_milestone=step.is_milestone,
    )


def _activity_state(activity: object) -> ActivityProgressStateResponse:
    return ActivityProgressStateResponse(
        id=activity.id,
        schedule_id=activity.schedule_id,
        status=activity.status,
        progress_pct=_str_to_float(activity.progress_pct),
        percent_complete_type=activity.percent_complete_type,
        remaining_duration=activity.remaining_duration,
        start_date=activity.start_date,
        end_date=activity.end_date,
        calendar_id=activity.calendar_id,
        suspended_at=activity.suspended_at,
        resumed_at=activity.resumed_at,
        suspend_reason=activity.suspend_reason,
    )


# ── Typed progress ─────────────────────────────────────────────────────────────


@progress_router.patch(
    "/activities/{activity_id}/typed-progress/",
    response_model=ProgressResultResponse,
    summary="Set activity progress via the per-type engine",
    dependencies=[Depends(RequirePermission("schedule.update"))],
)
async def set_typed_progress(
    activity_id: uuid.UUID,
    body: TypedProgressRequest,
    user_id: CurrentUserId,
    session: SessionDep,
    service: ScheduleProgressService = Depends(_get_service),
) -> ProgressResultResponse:
    await _verify_activity(service, session, activity_id, user_id)
    outcome = await service.set_typed_progress(activity_id, body)
    return _outcome_to_response(outcome)


@progress_router.put(
    "/activities/{activity_id}/percent-type/",
    response_model=PercentTypePreviewResponse,
    summary="Change percent-complete type (preview EVM-distortion warnings)",
    dependencies=[Depends(RequirePermission("schedule.update"))],
)
async def set_percent_type(
    activity_id: uuid.UUID,
    body: PercentTypeRequest,
    user_id: CurrentUserId,
    session: SessionDep,
    service: ScheduleProgressService = Depends(_get_service),
) -> PercentTypePreviewResponse:
    await _verify_activity(service, session, activity_id, user_id)
    activity, warnings = await service.change_percent_type(activity_id, body.percent_complete_type)
    return PercentTypePreviewResponse(
        activity_id=activity.id,
        percent_complete_type=activity.percent_complete_type,
        evm_warnings=warnings,
    )


@progress_router.post(
    "/activities/{activity_id}/percent-type/preview/",
    response_model=PercentTypePreviewResponse,
    summary="Preview the EVM-distortion warnings of a percent-type change without applying it",
    dependencies=[Depends(RequirePermission("schedule.update"))],
)
async def preview_percent_type(
    activity_id: uuid.UUID,
    body: PercentTypeRequest,
    user_id: CurrentUserId,
    session: SessionDep,
    service: ScheduleProgressService = Depends(_get_service),
) -> PercentTypePreviewResponse:
    """Preview a type change's warnings without writing it.

    The progress panel shows these while the user hovers a type, so the activity
    must keep its current type until the PUT above commits one.
    """
    await _verify_activity(service, session, activity_id, user_id)
    warnings = await service.preview_percent_type(activity_id, body.percent_complete_type)
    return PercentTypePreviewResponse(
        activity_id=activity_id,
        percent_complete_type=body.percent_complete_type,
        evm_warnings=warnings,
    )


# ── Steps ───────────────────────────────────────────────────────────────────────


@progress_router.get(
    "/activities/{activity_id}/steps/",
    response_model=list[StepResponse],
    summary="List the weighted progress steps of an activity",
    dependencies=[Depends(RequirePermission("schedule.read"))],
)
async def list_steps(
    activity_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: ScheduleProgressService = Depends(_get_service),
) -> list[StepResponse]:
    await _verify_activity(service, session, activity_id, user_id)
    steps = await service.list_steps(activity_id)
    return [_step_to_response(s) for s in steps]


@progress_router.post(
    "/activities/{activity_id}/steps/",
    response_model=StepResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a weighted progress step",
    dependencies=[Depends(RequirePermission("schedule.update"))],
)
async def create_step(
    activity_id: uuid.UUID,
    body: StepCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: ScheduleProgressService = Depends(_get_service),
) -> StepResponse:
    await _verify_activity(service, session, activity_id, user_id)
    step = await service.create_step(activity_id, body)
    return _step_to_response(step)


@progress_router.patch(
    "/steps/{step_id}/",
    response_model=StepResponse,
    summary="Update a weighted progress step",
    dependencies=[Depends(RequirePermission("schedule.update"))],
)
async def patch_step(
    step_id: uuid.UUID,
    body: StepPatch,
    user_id: CurrentUserId,
    session: SessionDep,
    service: ScheduleProgressService = Depends(_get_service),
) -> StepResponse:
    await _verify_step(service, session, step_id, user_id)
    step = await service.patch_step(step_id, body)
    return _step_to_response(step)


@progress_router.delete(
    "/steps/{step_id}/",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a weighted progress step",
    dependencies=[Depends(RequirePermission("schedule.update"))],
)
async def delete_step(
    step_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: ScheduleProgressService = Depends(_get_service),
) -> Response:
    await _verify_step(service, session, step_id, user_id)
    await service.delete_step(step_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Suspend / resume / calendar ─────────────────────────────────────────────────


@progress_router.post(
    "/activities/{activity_id}/suspend/",
    response_model=ActivityProgressStateResponse,
    summary="Suspend an activity (freeze remaining duration)",
    dependencies=[Depends(RequirePermission("schedule.update"))],
)
async def suspend_activity(
    activity_id: uuid.UUID,
    body: SuspendRequest,
    user_id: CurrentUserId,
    session: SessionDep,
    service: ScheduleProgressService = Depends(_get_service),
) -> ActivityProgressStateResponse:
    await _verify_activity(service, session, activity_id, user_id)
    activity = await service.suspend(activity_id, body.reason, body.effective_date)
    return _activity_state(activity)


@progress_router.post(
    "/activities/{activity_id}/resume/",
    response_model=ActivityProgressStateResponse,
    summary="Resume a suspended activity (reschedule from frozen remaining)",
    dependencies=[Depends(RequirePermission("schedule.update"))],
)
async def resume_activity(
    activity_id: uuid.UUID,
    body: ResumeRequest,
    user_id: CurrentUserId,
    session: SessionDep,
    service: ScheduleProgressService = Depends(_get_service),
) -> ActivityProgressStateResponse:
    await _verify_activity(service, session, activity_id, user_id)
    activity = await service.resume(activity_id, body.effective_date)
    return _activity_state(activity)


@progress_router.put(
    "/activities/{activity_id}/calendar/",
    response_model=ActivityProgressStateResponse,
    summary="Attach or clear a per-activity working calendar",
    dependencies=[Depends(RequirePermission("schedule.update"))],
)
async def set_activity_calendar(
    activity_id: uuid.UUID,
    body: CalendarSetRequest,
    user_id: CurrentUserId,
    session: SessionDep,
    service: ScheduleProgressService = Depends(_get_service),
) -> ActivityProgressStateResponse:
    await _verify_activity(service, session, activity_id, user_id)
    activity = await service.set_calendar(activity_id, body.calendar_id)
    return _activity_state(activity)


# ── Time-phased planned value (read-only) ───────────────────────────────────────


@progress_router.get(
    "/schedules/{schedule_id}/planned-value/",
    response_model=PlannedValueResponse,
    summary="Time-phased planned value preview at a data date",
    dependencies=[Depends(RequirePermission("schedule.read"))],
)
async def planned_value_preview(
    schedule_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    as_of: str = Query(..., max_length=40, description="Data date (YYYY-MM-DD) for the PV/EV snapshot"),
    service: ScheduleProgressService = Depends(_get_service),
) -> PlannedValueResponse:
    await _verify_schedule(service, session, schedule_id, user_id)
    data = await service.planned_value_preview(schedule_id, as_of)
    return PlannedValueResponse(**data)
