# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Measurement book API, mounted at ``/api/v1/measurement-book``.

GET    /entries/?project_id=&boq_position_id=   - entries, oldest first
POST   /entries/                                - add a measurement
PATCH  /entries/{id}                            - edit an unchecked measurement
DELETE /entries/{id}                            - delete an unchecked measurement
POST   /entries/{id}/check                      - check, dispute or reopen
GET    /positions/?project_id=                  - cumulative quantities per BOQ position
GET    /running-bill/?project_id=               - checked quantities valued at BOQ rates
POST   /running-bill/post-to-progress?project_id= - record the bill as progress
GET    /validation/?project_id=                 - measurement_book rule set
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import Response

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.measurement_book.schemas import (
    EntryCheck,
    EntryCreate,
    EntryResponse,
    EntryUpdate,
    PositionSummary,
    PostToProgress,
    PostToProgressResult,
    RunningBill,
    ValidationResponse,
)
from app.modules.measurement_book.service import DEFAULT_DEVIATION_PCT, MeasurementBookService

router = APIRouter()

_READ = Depends(RequirePermission("measurement_book.read"))
_WRITE = Depends(RequirePermission("measurement_book.write"))
_CHECK = Depends(RequirePermission("measurement_book.check"))
_BILL = Depends(RequirePermission("measurement_book.bill"))


@router.get("/entries/", response_model=list[EntryResponse], dependencies=[_READ])
async def list_entries(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    boq_position_id: uuid.UUID | None = Query(default=None),
) -> list[EntryResponse]:
    await verify_project_access(project_id, user_id, session)
    rows = await MeasurementBookService(session).repo.entries(project_id, boq_position_id)
    return [EntryResponse.model_validate(r) for r in rows]


@router.post("/entries/", response_model=EntryResponse, status_code=status.HTTP_201_CREATED, dependencies=[_WRITE])
async def create_entry(body: EntryCreate, session: SessionDep, user_id: CurrentUserId) -> EntryResponse:
    await verify_project_access(body.project_id, user_id, session)
    row = await MeasurementBookService(session).create(body, user_id)
    await session.commit()
    return EntryResponse.model_validate(row)


@router.patch("/entries/{entry_id}", response_model=EntryResponse, dependencies=[_WRITE])
async def update_entry(
    entry_id: uuid.UUID, body: EntryUpdate, session: SessionDep, user_id: CurrentUserId
) -> EntryResponse:
    service = MeasurementBookService(session)
    row = await service.entry(entry_id)
    await verify_project_access(row.project_id, user_id, session)
    row = await service.update(row, body)
    await session.commit()
    return EntryResponse.model_validate(row)


@router.delete("/entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[_WRITE])
async def delete_entry(entry_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> Response:
    service = MeasurementBookService(session)
    row = await service.entry(entry_id)
    await verify_project_access(row.project_id, user_id, session)
    await service.delete(row)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/entries/{entry_id}/check", response_model=EntryResponse, dependencies=[_CHECK])
async def check_entry(
    entry_id: uuid.UUID, body: EntryCheck, session: SessionDep, user_id: CurrentUserId
) -> EntryResponse:
    service = MeasurementBookService(session)
    row = await service.entry(entry_id)
    await verify_project_access(row.project_id, user_id, session)
    row = await service.check(row, body, user_id)
    await session.commit()
    return EntryResponse.model_validate(row)


@router.get("/positions/", response_model=list[PositionSummary], dependencies=[_READ])
async def list_positions(
    session: SessionDep, user_id: CurrentUserId, project_id: uuid.UUID = Query(...)
) -> list[PositionSummary]:
    await verify_project_access(project_id, user_id, session)
    return [PositionSummary(**p) for p in await MeasurementBookService(session).positions(project_id)]


@router.get("/running-bill/", response_model=RunningBill, dependencies=[_READ])
async def running_bill(session: SessionDep, user_id: CurrentUserId, project_id: uuid.UUID = Query(...)) -> RunningBill:
    await verify_project_access(project_id, user_id, session)
    return RunningBill(**await MeasurementBookService(session).running_bill(project_id))


@router.post("/running-bill/post-to-progress", response_model=PostToProgressResult, dependencies=[_BILL])
async def post_to_progress(
    body: PostToProgress, session: SessionDep, user_id: CurrentUserId, project_id: uuid.UUID = Query(...)
) -> PostToProgressResult:
    await verify_project_access(project_id, user_id, session)
    result = await MeasurementBookService(session).post_to_progress(project_id, body.period_label, user_id)
    await session.commit()
    return PostToProgressResult(**result)


@router.get("/validation/", response_model=ValidationResponse, dependencies=[_READ])
async def validate_book(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    deviation_threshold_pct: Decimal = Query(default=DEFAULT_DEVIATION_PCT, ge=0, le=100),
) -> ValidationResponse:
    await verify_project_access(project_id, user_id, session)
    return ValidationResponse(**await MeasurementBookService(session).validate(project_id, deviation_threshold_pct))
