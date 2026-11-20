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
    GET    /units/{unit_id}/materials               - ore/waste/low-grade polygons of a unit
    POST   /units/{unit_id}/materials[/import]      - add one, or import GeoJSON / drawing layers
    DELETE /materials/{material_id}                 - remove a polygon
    POST   /entries/{entry_id}/material-split       - clip the actual by the polygons, tonnes per material
    GET    /units/{unit_id}/drive                   - face pickups, profiles, advance and overbreak
    POST   /units/{unit_id}/faces                   - a face pickup (sets the period advance)
    POST   /units/{unit_id}/profiles[/import]       - measured profiles (area or outline, or a CSV)
    GET    /projects/{project_id}/blast-patterns    - blast patterns
    POST   /projects/{project_id}/blast-patterns    - new pattern with its design collars
    GET    /blast-patterns/{pattern_id}             - holes, as-drilled check, SRV-093 findings
    PATCH  /blast-patterns/{pattern_id}             - name, tolerances, note
    POST   /blast-patterns/{pattern_id}/as-drilled  - import the as-drilled holes
    GET    /blast-patterns/{pattern_id}/stake-list.csv - design collars for the instrument
    DELETE /blast-patterns/{pattern_id}             - remove a pattern
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Response, status

from app.core.document_locale import normalize_document_locale
from app.core.i18n import SUPPORTED_LOCALES
from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.mine_survey.depth import MineDepthService
from app.modules.mine_survey.models import MineUnit
from app.modules.mine_survey.schemas import (
    AddToClaim,
    ClaimResult,
    ComputeActual,
    ConfirmActual,
    DrilledImport,
    DriveDetail,
    EntryCreate,
    EntryOut,
    EntryUpdate,
    FaceIn,
    FaceOut,
    MaterialImport,
    MaterialImportResult,
    MaterialIn,
    MaterialListResponse,
    MaterialOut,
    PatternCreate,
    PatternDetail,
    PatternListResponse,
    PatternUpdate,
    PeriodCreate,
    PeriodDetail,
    PeriodListResponse,
    PeriodOut,
    PeriodUpdate,
    PlanImport,
    PlanImportResult,
    ProfileImport,
    ProfileIn,
    ProfileOut,
    TruckLoadsImport,
    UnitCreate,
    UnitListResponse,
    UnitOut,
    UnitUpdate,
)
from app.modules.mine_survey.service import MineService
from app.modules.survey_core.dependencies import require_survey_confirm

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


@router.get("/projects/{project_id}/units", response_model=UnitListResponse, dependencies=_READ)
async def list_units(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    offset: int = Query(0, ge=0),
    limit: int = Query(1000, ge=1, le=5000),
) -> UnitListResponse:
    await verify_project_access(project_id, user_id, session)
    rows = await MineService(session).list_units(project_id)
    return UnitListResponse(items=rows[offset : offset + limit], total=len(rows), offset=offset, limit=limit)


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


@router.get("/projects/{project_id}/periods", response_model=PeriodListResponse, dependencies=_READ)
async def list_periods(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    offset: int = Query(0, ge=0),
    limit: int = Query(1000, ge=1, le=5000),
) -> PeriodListResponse:
    await verify_project_access(project_id, user_id, session)
    rows = await MineService(session).list_periods(project_id)
    return PeriodListResponse(items=rows[offset : offset + limit], total=len(rows), offset=offset, limit=limit)


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
        headers={
            "Content-Disposition": f'attachment; filename="mine-period-{p.label}.pdf"',
            "Content-Language": normalize_document_locale(locale, SUPPORTED_LOCALES, "en"),
        },
    )


# ── v2: material split, drives, blast patterns ─────────────────────────────


async def _unit_of(unit_id: uuid.UUID, session: SessionDep, user_id: str) -> tuple[MineDepthService, MineUnit]:
    depth = MineDepthService(session)
    u = await depth._unit(unit_id)  # noqa: SLF001
    await verify_project_access(u.project_id, user_id, session)
    return depth, u


@router.get("/units/{unit_id}/materials", response_model=MaterialListResponse, dependencies=_READ)
async def list_materials(unit_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> MaterialListResponse:
    depth, u = await _unit_of(unit_id, session, user_id)
    rows = await depth.list_materials(u.id)
    return MaterialListResponse(items=rows, total=len(rows), limit=max(len(rows), 1))


@router.post("/units/{unit_id}/materials", response_model=MaterialOut, status_code=201, dependencies=_WRITE)
async def add_material(
    unit_id: uuid.UUID, body: MaterialIn, session: SessionDep, user_id: CurrentUserId
) -> MaterialOut:
    depth, u = await _unit_of(unit_id, session, user_id)
    return await depth.add_material(u, body, user_id)


@router.post("/units/{unit_id}/materials/import", response_model=MaterialImportResult, dependencies=_WRITE)
async def import_materials(
    unit_id: uuid.UUID, body: MaterialImport, session: SessionDep, user_id: CurrentUserId
) -> MaterialImportResult:
    depth, u = await _unit_of(unit_id, session, user_id)
    return await depth.import_materials(u, body, user_id)


@router.delete("/materials/{material_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=_WRITE)
async def delete_material(material_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> Response:
    depth = MineDepthService(session)
    m = await depth.get_material(material_id)
    await verify_project_access(m.project_id, user_id, session)
    await depth.repo.delete(m)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/entries/{entry_id}/material-split", response_model=EntryOut, dependencies=_WRITE)
async def material_split(
    entry_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, locale: str = _LOCALE
) -> EntryOut:
    service, e = await _entry(entry_id, session, user_id)
    service._open(e)  # noqa: SLF001
    await MineDepthService(session).split_entry(e)
    return await service._entry_response(e, locale)  # noqa: SLF001


@router.get("/units/{unit_id}/drive", response_model=DriveDetail, dependencies=_READ)
async def drive_detail(
    unit_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    period_id: uuid.UUID | None = None,
    locale: str = _LOCALE,
) -> DriveDetail:
    depth, u = await _unit_of(unit_id, session, user_id)
    period = await MineService(session).get_period(period_id) if period_id else None
    return await depth.drive_detail(u, period, locale)


@router.post("/units/{unit_id}/faces", response_model=FaceOut, status_code=201, dependencies=_WRITE)
async def add_face(unit_id: uuid.UUID, body: FaceIn, session: SessionDep, user_id: CurrentUserId) -> FaceOut:
    depth, u = await _unit_of(unit_id, session, user_id)
    return await depth.add_face(u, body)


@router.post("/units/{unit_id}/profiles", response_model=ProfileOut, status_code=201, dependencies=_WRITE)
async def add_profile(unit_id: uuid.UUID, body: ProfileIn, session: SessionDep, user_id: CurrentUserId) -> ProfileOut:
    depth, u = await _unit_of(unit_id, session, user_id)
    return await depth.add_profile(u, body)


@router.post("/units/{unit_id}/profiles/import", response_model=list[ProfileOut], dependencies=_WRITE)
async def import_profiles(
    unit_id: uuid.UUID, body: ProfileImport, session: SessionDep, user_id: CurrentUserId
) -> list[ProfileOut]:
    depth, u = await _unit_of(unit_id, session, user_id)
    rows, _ = await depth.import_profiles(u, body)
    return rows


@router.get("/projects/{project_id}/blast-patterns", response_model=PatternListResponse, dependencies=_READ)
async def list_patterns(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> PatternListResponse:
    await verify_project_access(project_id, user_id, session)
    rows = await MineDepthService(session).list_patterns(project_id)
    return PatternListResponse(items=rows, total=len(rows))


@router.post(
    "/projects/{project_id}/blast-patterns", response_model=PatternDetail, status_code=201, dependencies=_WRITE
)
async def create_pattern(
    project_id: uuid.UUID, body: PatternCreate, session: SessionDep, user_id: CurrentUserId, locale: str = _LOCALE
) -> PatternDetail:
    await verify_project_access(project_id, user_id, session)
    depth = MineDepthService(session)
    p, problems = await depth.create_pattern(project_id, body, user_id)
    return await depth.pattern_detail(p, locale, problems)


async def _pattern(pattern_id: uuid.UUID, session: SessionDep, user_id: str) -> tuple[MineDepthService, Any]:
    depth = MineDepthService(session)
    p = await depth.get_pattern(pattern_id)
    await verify_project_access(p.project_id, user_id, session)
    return depth, p


@router.get("/blast-patterns/{pattern_id}", response_model=PatternDetail, dependencies=_READ)
async def pattern_detail(
    pattern_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, locale: str = _LOCALE
) -> PatternDetail:
    depth, p = await _pattern(pattern_id, session, user_id)
    return await depth.pattern_detail(p, locale)


@router.patch("/blast-patterns/{pattern_id}", response_model=PatternDetail, dependencies=_WRITE)
async def update_pattern(
    pattern_id: uuid.UUID, body: PatternUpdate, session: SessionDep, user_id: CurrentUserId, locale: str = _LOCALE
) -> PatternDetail:
    depth, p = await _pattern(pattern_id, session, user_id)
    await depth.update_pattern(p, body)
    return await depth.pattern_detail(p, locale)


@router.post("/blast-patterns/{pattern_id}/as-drilled", response_model=PatternDetail, dependencies=_WRITE)
async def import_drilled(
    pattern_id: uuid.UUID, body: DrilledImport, session: SessionDep, user_id: CurrentUserId, locale: str = _LOCALE
) -> PatternDetail:
    depth, p = await _pattern(pattern_id, session, user_id)
    problems = await depth.import_drilled(p, body)
    return await depth.pattern_detail(p, locale, problems)


@router.get("/blast-patterns/{pattern_id}/stake-list.csv", dependencies=_READ)
async def stake_list(pattern_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> Response:
    depth, p = await _pattern(pattern_id, session, user_id)
    return Response(
        content=await depth.stake_list(p),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{p.code}-collars.csv"'},
    )


@router.delete("/blast-patterns/{pattern_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=_WRITE)
async def delete_pattern(pattern_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> Response:
    depth, p = await _pattern(pattern_id, session, user_id)
    await depth.repo.delete(p)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# The mine on the plan (blast blocks, the period's volumes and surfaces); same prefix and permissions.
from app.modules.mine_survey.plan_router import router as _plan_router  # noqa: E402

router.include_router(_plan_router)
