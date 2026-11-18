# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Mine survey API routes (mounted at ``/api/v1/mine-survey``).

Endpoints:
    GET    /projects/{project_id}/units             - mining units
    POST   /projects/{project_id}/units             - new unit
    PATCH  /units/{unit_id}                         - rename, type, density
    DELETE /units/{unit_id}                         - remove an unused unit
    GET    /projects/{project_id}/periods           - periods, newest first
    POST   /projects/{project_id}/periods           - new period with its profile
    GET    /periods/{period_id}                     - lines, totals and findings
    PATCH  /periods/{period_id}                     - band, truck check, note
    DELETE /periods/{period_id}                     - remove (not with a claimed line)
    POST   /periods/{period_id}/entries             - add a unit line with its plan
    POST   /periods/{period_id}/plan-import         - plan CSV, one line per unit
    PATCH  /entries/{entry_id}                      - plan, density, advance metres
    DELETE /entries/{entry_id}                      - remove an unclaimed line
    POST   /entries/{entry_id}/compute-actual       - volume of start against end surface
    POST   /entries/{entry_id}/confirm-actual       - confirm that volume (survey.confirm)
    POST   /entries/{entry_id}/truck-loads          - truck-count tonnes from a CSV
    POST   /entries/{entry_id}/add-to-claim         - progress entry for the confirmed actual (survey.confirm)
    GET    /periods/{period_id}/report.pdf          - mine period report
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response, status

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.mine_survey.schemas import (
    AddToClaim,
    ClaimResult,
    ComputeActual,
    ConfirmActual,
    EntryCreate,
    EntryOut,
    EntryUpdate,
    PeriodCreate,
    PeriodDetail,
    PeriodOut,
    PeriodUpdate,
    PlanImport,
    PlanImportResult,
    TruckLoadsImport,
    UnitCreate,
    UnitOut,
    UnitUpdate,
)
from app.modules.mine_survey.service import MineService
from app.modules.survey_core.permissions import require_survey_confirm

router = APIRouter(tags=["mine_survey"])

_READ = [Depends(RequirePermission("survey.read"))]
_WRITE = [Depends(RequirePermission("survey.write"))]
_CONFIRM = [Depends(RequirePermission("survey.write")), Depends(require_survey_confirm)]
_LOCALE = Query("en", max_length=10)


async def _period(period_id: uuid.UUID, session: SessionDep, user_id: str):
    service = MineService(session)
    p = await service.get_period(period_id)
    await verify_project_access(p.project_id, user_id, session)
    return service, p


async def _entry(entry_id: uuid.UUID, session: SessionDep, user_id: str):
    service = MineService(session)
    e = await service.get_entry(entry_id)
    await verify_project_access(e.project_id, user_id, session)
    return service, e


# ── Units ──────────────────────────────────────────────────────────────────


@router.get("/projects/{project_id}/units", response_model=list[UnitOut], dependencies=_READ)
async def list_units(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> list[UnitOut]:
    await verify_project_access(project_id, user_id, session)
    return await MineService(session).list_units(project_id)


@router.post(
    "/projects/{project_id}/units", response_model=UnitOut, status_code=status.HTTP_201_CREATED, dependencies=_WRITE
)
async def create_unit(project_id: uuid.UUID, body: UnitCreate, session: SessionDep, user_id: CurrentUserId) -> UnitOut:
    await verify_project_access(project_id, user_id, session)
    return await MineService(session).create_unit(project_id, body, user_id)


@router.patch("/units/{unit_id}", response_model=UnitOut, dependencies=_WRITE)
async def update_unit(unit_id: uuid.UUID, body: UnitUpdate, session: SessionDep, user_id: CurrentUserId) -> UnitOut:
    service = MineService(session)
    u = await service.get_unit(unit_id)
    await verify_project_access(u.project_id, user_id, session)
    return await service.update_unit(u, body)


@router.delete("/units/{unit_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=_WRITE)
async def delete_unit(unit_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> Response:
    service = MineService(session)
    u = await service.get_unit(unit_id)
    await verify_project_access(u.project_id, user_id, session)
    await service.delete_unit(u)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Periods ────────────────────────────────────────────────────────────────


@router.get("/projects/{project_id}/periods", response_model=list[PeriodOut], dependencies=_READ)
async def list_periods(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> list[PeriodOut]:
    await verify_project_access(project_id, user_id, session)
    return await MineService(session).list_periods(project_id)


@router.post(
    "/projects/{project_id}/periods", response_model=PeriodOut, status_code=status.HTTP_201_CREATED, dependencies=_WRITE
)
async def create_period(
    project_id: uuid.UUID, body: PeriodCreate, session: SessionDep, user_id: CurrentUserId
) -> PeriodOut:
    await verify_project_access(project_id, user_id, session)
    return await MineService(session).create_period(project_id, body, user_id)


@router.get("/periods/{period_id}", response_model=PeriodDetail, dependencies=_READ)
async def get_period(
    period_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, locale: str = _LOCALE
) -> PeriodDetail:
    service, p = await _period(period_id, session, user_id)
    return await service.detail(p, locale)


@router.patch("/periods/{period_id}", response_model=PeriodOut, dependencies=_WRITE)
async def update_period(
    period_id: uuid.UUID, body: PeriodUpdate, session: SessionDep, user_id: CurrentUserId
) -> PeriodOut:
    service, p = await _period(period_id, session, user_id)
    return await service.update_period(p, body)


@router.delete("/periods/{period_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=_WRITE)
async def delete_period(period_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> Response:
    service, p = await _period(period_id, session, user_id)
    await service.delete_period(p)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Lines ──────────────────────────────────────────────────────────────────


@router.post(
    "/periods/{period_id}/entries", response_model=EntryOut, status_code=status.HTTP_201_CREATED, dependencies=_WRITE
)
async def add_entry(
    period_id: uuid.UUID, body: EntryCreate, session: SessionDep, user_id: CurrentUserId, locale: str = _LOCALE
) -> EntryOut:
    service, p = await _period(period_id, session, user_id)
    return await service.add_entry(p, body, user_id, locale)


@router.post("/periods/{period_id}/plan-import", response_model=PlanImportResult, dependencies=_WRITE)
async def import_plan(
    period_id: uuid.UUID, body: PlanImport, session: SessionDep, user_id: CurrentUserId
) -> PlanImportResult:
    service, p = await _period(period_id, session, user_id)
    return await service.import_plan(p, body, user_id)


@router.patch("/entries/{entry_id}", response_model=EntryOut, dependencies=_WRITE)
async def update_entry(
    entry_id: uuid.UUID, body: EntryUpdate, session: SessionDep, user_id: CurrentUserId, locale: str = _LOCALE
) -> EntryOut:
    service, e = await _entry(entry_id, session, user_id)
    return await service.update_entry(e, body, locale)


@router.delete("/entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=_WRITE)
async def delete_entry(entry_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> Response:
    service, e = await _entry(entry_id, session, user_id)
    await service.delete_entry(e)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/entries/{entry_id}/compute-actual", response_model=EntryOut, dependencies=_WRITE)
async def compute_actual(
    entry_id: uuid.UUID, body: ComputeActual, session: SessionDep, user_id: CurrentUserId, locale: str = _LOCALE
) -> EntryOut:
    service, e = await _entry(entry_id, session, user_id)
    return await service.compute_actual(e, body, user_id, locale)


@router.post("/entries/{entry_id}/confirm-actual", response_model=EntryOut, dependencies=_CONFIRM)
async def confirm_actual(
    entry_id: uuid.UUID, body: ConfirmActual, session: SessionDep, user_id: CurrentUserId, locale: str = _LOCALE
) -> EntryOut:
    service, e = await _entry(entry_id, session, user_id)
    return await service.confirm_actual(e, body, user_id, locale)


@router.post("/entries/{entry_id}/truck-loads", response_model=EntryOut, dependencies=_WRITE)
async def import_trucks(
    entry_id: uuid.UUID, body: TruckLoadsImport, session: SessionDep, user_id: CurrentUserId, locale: str = _LOCALE
) -> EntryOut:
    service, e = await _entry(entry_id, session, user_id)
    return await service.import_trucks(e, body, locale)


@router.post("/entries/{entry_id}/add-to-claim", response_model=ClaimResult, dependencies=_CONFIRM)
async def add_to_claim(
    entry_id: uuid.UUID, body: AddToClaim, session: SessionDep, user_id: CurrentUserId
) -> ClaimResult:
    service, e = await _entry(entry_id, session, user_id)
    return await service.add_to_claim(e, body, user_id)


# ── Report ─────────────────────────────────────────────────────────────────


@router.get("/periods/{period_id}/report.pdf", dependencies=_READ)
async def report_pdf(
    period_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, locale: str = _LOCALE
) -> Response:
    from app.modules.mine_survey.report_pdf import build_period_report  # noqa: PLC0415
    from app.modules.projects.models import Project  # noqa: PLC0415

    service, p = await _period(period_id, session, user_id)
    data = await service.report_data(p, locale)
    project = await session.get(Project, p.project_id)
    pdf = build_period_report(data, project.name if project else "")
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="mine-period-{p.label}.pdf"'},
    )
