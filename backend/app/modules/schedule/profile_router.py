# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Scheduling profiles API.

Mounted into the schedule router, so these share the ``/api/v1/schedule``
prefix. Every endpoint resolves the owning project and runs
``verify_project_access`` (404 on cross-tenant access) before any work.

* ``GET/POST /scheduling-profiles/``, ``PATCH/DELETE /scheduling-profiles/{id}``
* ``GET/PUT /schedules/{id}/scheduling-profile`` - the profile a schedule uses
* ``POST /schedules/{id}/recalculate/preview`` - dates per activity and which
  setting moved them, nothing written
* ``POST /schedules/{id}/recalculate/apply`` - write those dates
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response, status

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.schedule.profile_schemas import (
    EffectiveProfileResponse,
    ProfileAssignRequest,
    ProfileSettings,
    RecalculateRequest,
    RecalculateResponse,
    SchedulingProfileCreate,
    SchedulingProfileResponse,
    SchedulingProfileUpdate,
)
from app.modules.schedule.profile_service import SchedulingProfileService

profile_router = APIRouter(tags=["schedule"])


def _service(session: SessionDep) -> SchedulingProfileService:
    return SchedulingProfileService(session)


async def _verify_schedule(
    service: SchedulingProfileService, session: SessionDep, schedule_id: uuid.UUID, user_id: str
):
    schedule = await service.base.get_schedule(schedule_id)
    await verify_project_access(schedule.project_id, user_id, session)
    return schedule


async def _verify_profile(service: SchedulingProfileService, session: SessionDep, profile_id: uuid.UUID, user_id: str):
    profile = await service.get(profile_id)
    await verify_project_access(profile.project_id, user_id, session)
    return profile


@profile_router.get(
    "/scheduling-profiles/",
    response_model=list[SchedulingProfileResponse],
    dependencies=[Depends(RequirePermission("schedule.read"))],
)
async def list_profiles(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
) -> list[SchedulingProfileResponse]:
    """The project's scheduling profiles, default first."""
    await verify_project_access(project_id, user_id, session)
    rows = await _service(session).list_for_project(project_id)
    return [SchedulingProfileResponse.model_validate(r) for r in rows]


@profile_router.post(
    "/scheduling-profiles/",
    response_model=SchedulingProfileResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("schedule.update"))],
)
async def create_profile(
    data: SchedulingProfileCreate,
    session: SessionDep,
    user_id: CurrentUserId,
) -> SchedulingProfileResponse:
    """Create a profile; ``is_default`` takes the default over from any other."""
    await verify_project_access(data.project_id, user_id, session)
    profile = await _service(session).create(data, user_id)
    return SchedulingProfileResponse.model_validate(profile)


@profile_router.patch(
    "/scheduling-profiles/{profile_id}",
    response_model=SchedulingProfileResponse,
    dependencies=[Depends(RequirePermission("schedule.update"))],
)
async def update_profile(
    profile_id: uuid.UUID,
    data: SchedulingProfileUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
) -> SchedulingProfileResponse:
    service = _service(session)
    await _verify_profile(service, session, profile_id, user_id)
    profile = await service.update(profile_id, data, user_id)
    return SchedulingProfileResponse.model_validate(profile)


@profile_router.delete(
    "/scheduling-profiles/{profile_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(RequirePermission("schedule.update"))],
)
async def delete_profile(profile_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> Response:
    """Delete a profile. Schedules that named it fall back to the project default."""
    service = _service(session)
    await _verify_profile(service, session, profile_id, user_id)
    await service.delete(profile_id, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _effective_response(schedule_id: uuid.UUID, effective) -> EffectiveProfileResponse:  # noqa: ANN001
    return EffectiveProfileResponse(
        schedule_id=schedule_id,
        profile_id=effective.profile.id if effective.profile else None,
        profile_name=effective.profile.name if effective.profile else None,
        source=effective.source,
        settings=ProfileSettings(**effective.settings),
    )


@profile_router.get(
    "/schedules/{schedule_id}/scheduling-profile",
    response_model=EffectiveProfileResponse,
    dependencies=[Depends(RequirePermission("schedule.read"))],
)
async def get_schedule_profile(
    schedule_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> EffectiveProfileResponse:
    service = _service(session)
    schedule = await _verify_schedule(service, session, schedule_id, user_id)
    return _effective_response(schedule_id, await service.resolve(schedule))


@profile_router.put(
    "/schedules/{schedule_id}/scheduling-profile",
    response_model=EffectiveProfileResponse,
    dependencies=[Depends(RequirePermission("schedule.update"))],
)
async def assign_schedule_profile(
    schedule_id: uuid.UUID,
    data: ProfileAssignRequest,
    session: SessionDep,
    user_id: CurrentUserId,
) -> EffectiveProfileResponse:
    """Choose the schedule's profile; ``null`` returns it to the project default."""
    service = _service(session)
    await _verify_schedule(service, session, schedule_id, user_id)
    schedule = await service.assign(schedule_id, data.profile_id, user_id)
    return _effective_response(schedule_id, await service.resolve(schedule))


@profile_router.post(
    "/schedules/{schedule_id}/recalculate/preview",
    response_model=RecalculateResponse,
    dependencies=[Depends(RequirePermission("schedule.read"))],
)
async def preview_recalculation(
    schedule_id: uuid.UUID,
    data: RecalculateRequest,
    session: SessionDep,
    user_id: CurrentUserId,
) -> RecalculateResponse:
    """Run CPM with a profile and show what each setting would change. Writes nothing."""
    service = _service(session)
    await _verify_schedule(service, session, schedule_id, user_id)
    result = await service.recalculate(schedule_id, profile_id=data.profile_id)
    return RecalculateResponse(**result)


@profile_router.post(
    "/schedules/{schedule_id}/recalculate/apply",
    response_model=RecalculateResponse,
    dependencies=[Depends(RequirePermission("schedule.update"))],
)
async def apply_recalculation(
    schedule_id: uuid.UUID,
    data: RecalculateRequest,
    session: SessionDep,
    user_id: CurrentUserId,
) -> RecalculateResponse:
    """Recalculate with a profile and write the dates (audited)."""
    service = _service(session)
    await _verify_schedule(service, session, schedule_id, user_id)
    result = await service.recalculate(schedule_id, profile_id=data.profile_id, apply=True, actor_id=user_id)
    return RecalculateResponse(**result)
