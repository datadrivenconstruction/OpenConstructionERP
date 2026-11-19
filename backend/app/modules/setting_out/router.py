# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Setting-out API routes (mounted at ``/api/v1/setting-out``).

Endpoints:
    GET    /projects/{project_id}/profiles           - demo, active-pack and project tolerance profiles
    POST   /projects/{project_id}/profiles           - add a project tolerance profile
    GET    /projects/{project_id}/requests           - stakeout requests with pass/fail counts
    POST   /projects/{project_id}/requests           - new request
    GET    /projects/{project_id}/summary            - KPIs: open, passed, failed, NCR drafts
    POST   /projects/{project_id}/validate           - the ``setting_out`` rule set
    POST   /projects/{project_id}/demo/riverside     - load the Riverside Yard request "Columns axis C"
    GET    /requests/{request_id}                    - request with stakes and newest records
    PATCH  /requests/{request_id}                    - edit (tolerance change is audited)
    DELETE /requests/{request_id}                    - remove request, stakes and records
    POST   /requests/{request_id}/design/preview     - read a design CSV/LandXML; nothing saved
    POST   /requests/{request_id}/design             - import design stakes and/or alignment
    POST   /requests/{request_id}/stakes             - add one stake (E/N or chainage/offset)
    POST   /requests/{request_id}/chainage           - chainage/offset calculator on the alignment
    POST   /requests/{request_id}/measured           - import measured stakes from CSV
    GET    /requests/{request_id}/sheet.pdf          - setting-out sheet
    POST   /stakes/{stake_id}/records                - record one measurement, instant verdict
    GET    /stakes/{stake_id}/records                - measurement history of a stake
    POST   /records/{record_id}/ncr                  - NCR draft in Quality for a failed stake
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response, status

from app.core.active_markets import ActiveMarkets
from app.core.document_locale import normalize_document_locale
from app.core.i18n import SUPPORTED_LOCALES
from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.setting_out.schemas import (
    ChainageAnswer,
    ChainageQuery,
    DesignImport,
    DesignPreview,
    MeasuredImport,
    MeasuredImportResult,
    NcrDraftOut,
    RecordCreate,
    RecordListResponse,
    RecordOut,
    RequestCreate,
    RequestDetail,
    RequestListResponse,
    RequestOut,
    RequestUpdate,
    SettingOutSummary,
    StakeCreate,
    StakeOut,
    ToleranceProfileCreate,
    ToleranceProfileListResponse,
    ToleranceProfileOut,
    ValidationReportOut,
)
from app.modules.setting_out.service import SettingOutService

router = APIRouter(tags=["setting_out"])

_READ = [Depends(RequirePermission("survey.read"))]
_WRITE = [Depends(RequirePermission("survey.write"))]
_LOCALE = Query("en", max_length=10)


async def _request(request_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId):  # noqa: ANN202
    service = SettingOutService(session)
    req = await service.get_request(request_id)
    await verify_project_access(req.project_id, user_id, session)
    return service, req


@router.get("/projects/{project_id}/profiles", response_model=ToleranceProfileListResponse, dependencies=_READ)
async def list_profiles(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    markets: ActiveMarkets,
    offset: int = Query(0, ge=0),
    limit: int = Query(1000, ge=1, le=5000),
) -> ToleranceProfileListResponse:
    await verify_project_access(project_id, user_id, session)
    rows = await SettingOutService(session).profiles(project_id, markets)
    return ToleranceProfileListResponse(
        items=rows[offset : offset + limit], total=len(rows), offset=offset, limit=limit
    )


@router.post(
    "/projects/{project_id}/profiles",
    response_model=ToleranceProfileOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=_WRITE,
)
async def create_profile(
    project_id: uuid.UUID, body: ToleranceProfileCreate, session: SessionDep, user_id: CurrentUserId
) -> ToleranceProfileOut:
    await verify_project_access(project_id, user_id, session)
    return await SettingOutService(session).create_profile(project_id, body, user_id)


@router.get("/projects/{project_id}/requests", response_model=RequestListResponse, dependencies=_READ)
async def list_requests(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    offset: int = Query(0, ge=0),
    limit: int = Query(1000, ge=1, le=5000),
) -> RequestListResponse:
    await verify_project_access(project_id, user_id, session)
    rows = await SettingOutService(session).list_requests(project_id)
    return RequestListResponse(items=rows[offset : offset + limit], total=len(rows), offset=offset, limit=limit)


@router.post(
    "/projects/{project_id}/requests",
    response_model=RequestOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=_WRITE,
)
async def create_request(
    project_id: uuid.UUID, body: RequestCreate, session: SessionDep, user_id: CurrentUserId, markets: ActiveMarkets
) -> RequestOut:
    await verify_project_access(project_id, user_id, session)
    return await SettingOutService(session).create_request(project_id, body, user_id, markets)


@router.get("/projects/{project_id}/summary", response_model=SettingOutSummary, dependencies=_READ)
async def summary(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> SettingOutSummary:
    await verify_project_access(project_id, user_id, session)
    return await SettingOutService(session).summary(project_id)


@router.post("/projects/{project_id}/validate", response_model=ValidationReportOut, dependencies=_READ)
async def validate(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, locale: str = _LOCALE
) -> ValidationReportOut:
    await verify_project_access(project_id, user_id, session)
    return await SettingOutService(session).validate(project_id, locale)


@router.post("/projects/{project_id}/demo/riverside", response_model=RequestDetail, dependencies=_WRITE)
async def load_demo(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> RequestDetail:
    await verify_project_access(project_id, user_id, session)
    return await SettingOutService(session).load_riverside_demo(project_id, user_id)


@router.get("/requests/{request_id}", response_model=RequestDetail, dependencies=_READ)
async def get_request(request_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> RequestDetail:
    service, req = await _request(request_id, session, user_id)
    return await service.detail(req)


@router.patch("/requests/{request_id}", response_model=RequestOut, dependencies=_WRITE)
async def update_request(
    request_id: uuid.UUID, body: RequestUpdate, session: SessionDep, user_id: CurrentUserId, markets: ActiveMarkets
) -> RequestOut:
    service, req = await _request(request_id, session, user_id)
    return await service.update_request(req, body, user_id, markets)


@router.delete("/requests/{request_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=_WRITE)
async def delete_request(request_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> Response:
    service, req = await _request(request_id, session, user_id)
    await service.delete_request(req, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/requests/{request_id}/design/preview", response_model=DesignPreview, dependencies=_WRITE)
async def design_preview(
    request_id: uuid.UUID, body: DesignImport, session: SessionDep, user_id: CurrentUserId
) -> DesignPreview:
    service, req = await _request(request_id, session, user_id)
    return await service.preview_design(req, body)


@router.post("/requests/{request_id}/design", response_model=RequestDetail, dependencies=_WRITE)
async def design_import(
    request_id: uuid.UUID, body: DesignImport, session: SessionDep, user_id: CurrentUserId
) -> RequestDetail:
    service, req = await _request(request_id, session, user_id)
    return await service.import_design(req, body, user_id)


@router.post(
    "/requests/{request_id}/stakes", response_model=StakeOut, status_code=status.HTTP_201_CREATED, dependencies=_WRITE
)
async def add_stake(request_id: uuid.UUID, body: StakeCreate, session: SessionDep, user_id: CurrentUserId) -> StakeOut:
    service, req = await _request(request_id, session, user_id)
    return await service.add_stake(req, body, user_id)


@router.post("/requests/{request_id}/chainage", response_model=ChainageAnswer, dependencies=_READ)
async def chainage(
    request_id: uuid.UUID, body: ChainageQuery, session: SessionDep, user_id: CurrentUserId
) -> ChainageAnswer:
    service, req = await _request(request_id, session, user_id)
    return service.chainage(req, body)


@router.post("/requests/{request_id}/measured", response_model=MeasuredImportResult, dependencies=_WRITE)
async def import_measured(
    request_id: uuid.UUID, body: MeasuredImport, session: SessionDep, user_id: CurrentUserId
) -> MeasuredImportResult:
    service, req = await _request(request_id, session, user_id)
    return await service.import_measured(req, body, user_id)


@router.get("/requests/{request_id}/sheet.pdf", response_class=Response, dependencies=_READ)
async def sheet_pdf(
    request_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, locale: str = _LOCALE
) -> Response:
    service, req = await _request(request_id, session, user_id)
    pdf = await service.sheet_pdf(req, locale)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="setting-out-{req.code}.pdf"',
            "Content-Language": normalize_document_locale(locale, SUPPORTED_LOCALES, "en"),
        },
    )


async def _stake(stake_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId):  # noqa: ANN202
    service = SettingOutService(session)
    stake = await service.get_stake(stake_id)
    await verify_project_access(stake.project_id, user_id, session)
    return service, stake


@router.post(
    "/stakes/{stake_id}/records", response_model=RecordOut, status_code=status.HTTP_201_CREATED, dependencies=_WRITE
)
async def add_record(stake_id: uuid.UUID, body: RecordCreate, session: SessionDep, user_id: CurrentUserId) -> RecordOut:
    service, stake = await _stake(stake_id, session, user_id)
    return await service.add_record(stake, body, user_id)


@router.get("/stakes/{stake_id}/records", response_model=RecordListResponse, dependencies=_READ)
async def history(
    stake_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    offset: int = Query(0, ge=0),
    limit: int = Query(1000, ge=1, le=5000),
) -> RecordListResponse:
    service, stake = await _stake(stake_id, session, user_id)
    rows = await service.history(stake)
    return RecordListResponse(items=rows[offset : offset + limit], total=len(rows), offset=offset, limit=limit)


@router.post(
    "/records/{record_id}/ncr", response_model=NcrDraftOut, status_code=status.HTTP_201_CREATED, dependencies=_WRITE
)
async def create_ncr(
    record_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, locale: str = _LOCALE
) -> NcrDraftOut:
    service = SettingOutService(session)
    rec = await service.get_record(record_id)
    await verify_project_access(rec.project_id, user_id, session)
    return await service.create_ncr_draft(rec, user_id, locale)


from app.modules.setting_out.road_router import router as _road_router  # noqa: E402

router.include_router(_road_router)
