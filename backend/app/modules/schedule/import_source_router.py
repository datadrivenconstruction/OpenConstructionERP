# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Source of an imported schedule: compare, accept, restore.

Mounted into the schedule router under ``/api/v1/schedule``:

* ``GET  /schedules/{id}/import-source``         - source vs current dates
* ``POST /schedules/{id}/import-source/accept``  - accept the recalculated dates
* ``POST /schedules/{id}/import-source/restore`` - put the source dates back
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.schedule.import_source import ImportSourceService
from app.modules.schedule.import_source_schemas import (
    ImportSourceRecord,
    SourceComparisonResponse,
    SourceRestoreResponse,
)
from app.modules.schedule.service import ScheduleService

import_source_router = APIRouter(tags=["schedule"])


async def _verify(session: SessionDep, schedule_id: uuid.UUID, user_id: str) -> None:
    schedule = await ScheduleService(session).get_schedule(schedule_id)
    await verify_project_access(schedule.project_id, user_id, session)


@import_source_router.get(
    "/schedules/{schedule_id}/import-source",
    response_model=SourceComparisonResponse,
    dependencies=[Depends(RequirePermission("schedule.read"))],
)
async def get_import_source(
    schedule_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> SourceComparisonResponse:
    """Dates as in the source file beside the current dates, with the deviation in days."""
    await _verify(session, schedule_id, user_id)
    return SourceComparisonResponse(**await ImportSourceService(session).comparison(schedule_id))


@import_source_router.post(
    "/schedules/{schedule_id}/import-source/accept",
    response_model=ImportSourceRecord,
    dependencies=[Depends(RequirePermission("schedule.update"))],
)
async def accept_import_recalculation(
    schedule_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> ImportSourceRecord:
    """Accept the recalculated dates. The source file and source dates are kept."""
    await _verify(session, schedule_id, user_id)
    return ImportSourceRecord(**await ImportSourceService(session).accept(schedule_id, user_id))


@import_source_router.post(
    "/schedules/{schedule_id}/import-source/restore",
    response_model=SourceRestoreResponse,
    dependencies=[Depends(RequirePermission("schedule.update"))],
)
async def restore_import_source_dates(
    schedule_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> SourceRestoreResponse:
    """Put every imported activity back on the dates it had in the source file."""
    await _verify(session, schedule_id, user_id)
    moved = await ImportSourceService(session).restore(schedule_id, user_id)
    await ScheduleService(session).sync_schedule_end_date(schedule_id)
    return SourceRestoreResponse(schedule_id=schedule_id, moved=moved)
