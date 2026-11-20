# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Monitoring API routes (mounted at ``/api/v1/monitoring``).

Endpoints:
    GET    /projects/{project_id}/profiles            - demo, active-pack and project threshold profiles
    POST   /projects/{project_id}/profiles            - add a project threshold profile
    GET    /projects/{project_id}/settings            - the profile the project is judged against
    PUT    /projects/{project_id}/settings            - choose that profile
    GET    /projects/{project_id}/points              - points with baseline, latest, displacement, rate, level
    POST   /projects/{project_id}/points              - add a point by hand
    GET    /projects/{project_id}/summary              - KPIs: points per level, last epoch
    POST   /projects/{project_id}/readings/preview    - read a readings CSV; nothing saved
    POST   /projects/{project_id}/readings            - import readings; crossed levels open alerts
    POST   /projects/{project_id}/validate            - the ``monitoring`` rule set (MON-001)
    GET    /projects/{project_id}/report.pdf          - alarm report
    POST   /projects/{project_id}/demo/riverside      - load the Riverside Yard wall points and profile
    GET    /points/{point_id}                         - point with its series, bands and alert history
    PATCH  /points/{point_id}                         - edit
    DELETE /points/{point_id}                         - remove the point, its readings and alerts
    POST   /points/{point_id}/acknowledge             - acknowledge open alerts with a note (survey.confirm)
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response, status

from app.core.active_markets import ActiveMarkets
from app.core.document_locale import normalize_document_locale
from app.core.i18n import SUPPORTED_LOCALES
from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.monitoring.schemas import (
    Acknowledge,
    MonitoringSummary,
    PointCreate,
    PointDetail,
    PointListResponse,
    PointOut,
    PointUpdate,
    ProfileCreate,
    ProfileListResponse,
    ProfileOut,
    ReadingsImport,
    ReadingsPreview,
    ReadingsResult,
    SettingsOut,
    SettingsUpdate,
    ValidationReportOut,
)
from app.modules.monitoring.service import MonitoringService
from app.modules.survey_core.dependencies import require_survey_confirm

router = APIRouter(tags=["monitoring"])

_READ = [Depends(RequirePermission("survey.read"))]
_WRITE = [Depends(RequirePermission("survey.write"))]
_CONFIRM = [*_READ, Depends(require_survey_confirm)]
_LOCALE = Query("en", max_length=10)


async def _point(point_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId):  # noqa: ANN202
    service = MonitoringService(session)
    point = await service.get_point(point_id)
    await verify_project_access(point.project_id, user_id, session)
    return service, point


@router.get("/projects/{project_id}/profiles", response_model=ProfileListResponse, dependencies=_READ)
async def list_profiles(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    markets: ActiveMarkets,
    offset: int = Query(0, ge=0),
    limit: int = Query(1000, ge=1, le=5000),
) -> ProfileListResponse:
    await verify_project_access(project_id, user_id, session)
    rows = await MonitoringService(session).profiles(project_id, markets)
    return ProfileListResponse(items=rows[offset : offset + limit], total=len(rows), offset=offset, limit=limit)


@router.post(
    "/projects/{project_id}/profiles",
    response_model=ProfileOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=_WRITE,
)
async def create_profile(
    project_id: uuid.UUID, body: ProfileCreate, session: SessionDep, user_id: CurrentUserId
) -> ProfileOut:
    await verify_project_access(project_id, user_id, session)
    return await MonitoringService(session).create_profile(project_id, body, user_id)


@router.get("/projects/{project_id}/settings", response_model=SettingsOut, dependencies=_READ)
async def get_settings(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, markets: ActiveMarkets
) -> SettingsOut:
    await verify_project_access(project_id, user_id, session)
    return await MonitoringService(session).get_settings(project_id, markets)


@router.put("/projects/{project_id}/settings", response_model=SettingsOut, dependencies=_WRITE)
async def set_settings(
    project_id: uuid.UUID, body: SettingsUpdate, session: SessionDep, user_id: CurrentUserId, markets: ActiveMarkets
) -> SettingsOut:
    await verify_project_access(project_id, user_id, session)
    return await MonitoringService(session).set_settings(project_id, body, user_id, markets)


@router.get("/projects/{project_id}/points", response_model=PointListResponse, dependencies=_READ)
async def list_points(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    markets: ActiveMarkets,
    offset: int = Query(0, ge=0),
    limit: int = Query(1000, ge=1, le=5000),
) -> PointListResponse:
    await verify_project_access(project_id, user_id, session)
    rows = await MonitoringService(session).list_points(project_id, markets)
    return PointListResponse(items=rows[offset : offset + limit], total=len(rows), offset=offset, limit=limit)


@router.post(
    "/projects/{project_id}/points", response_model=PointOut, status_code=status.HTTP_201_CREATED, dependencies=_WRITE
)
async def create_point(
    project_id: uuid.UUID, body: PointCreate, session: SessionDep, user_id: CurrentUserId
) -> PointOut:
    await verify_project_access(project_id, user_id, session)
    return await MonitoringService(session).create_point(project_id, body, user_id)


@router.get("/projects/{project_id}/summary", response_model=MonitoringSummary, dependencies=_READ)
async def summary(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, markets: ActiveMarkets
) -> MonitoringSummary:
    await verify_project_access(project_id, user_id, session)
    return await MonitoringService(session).summary(project_id, markets)


@router.post("/projects/{project_id}/readings/preview", response_model=ReadingsPreview, dependencies=_WRITE)
async def preview_readings(
    project_id: uuid.UUID, body: ReadingsImport, session: SessionDep, user_id: CurrentUserId
) -> ReadingsPreview:
    await verify_project_access(project_id, user_id, session)
    return await MonitoringService(session).preview_readings(project_id, body)


@router.post("/projects/{project_id}/readings", response_model=ReadingsResult, dependencies=_WRITE)
async def import_readings(
    project_id: uuid.UUID,
    body: ReadingsImport,
    session: SessionDep,
    user_id: CurrentUserId,
    markets: ActiveMarkets,
    locale: str = _LOCALE,
) -> ReadingsResult:
    await verify_project_access(project_id, user_id, session)
    return await MonitoringService(session).import_readings(project_id, body, user_id, markets, locale)


@router.post("/projects/{project_id}/validate", response_model=ValidationReportOut, dependencies=_READ)
async def validate(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, markets: ActiveMarkets, locale: str = _LOCALE
) -> ValidationReportOut:
    await verify_project_access(project_id, user_id, session)
    return await MonitoringService(session).validate(project_id, markets, locale)


@router.get("/projects/{project_id}/report.pdf", response_class=Response, dependencies=_READ)
async def report_pdf(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, markets: ActiveMarkets, locale: str = _LOCALE
) -> Response:
    await verify_project_access(project_id, user_id, session)
    pdf = await MonitoringService(session).report_pdf(project_id, markets, locale)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="monitoring-alarm-report.pdf"',
            "Content-Language": normalize_document_locale(locale, SUPPORTED_LOCALES, "en"),
        },
    )


@router.post("/projects/{project_id}/demo/riverside", response_model=list[PointOut], dependencies=_WRITE)
async def load_demo(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    markets: ActiveMarkets,
    epochs: int = Query(0, ge=0, le=4),
    locale: str = _LOCALE,
) -> list[PointOut]:
    await verify_project_access(project_id, user_id, session)
    return await MonitoringService(session).load_riverside_demo(project_id, user_id, markets, locale, epochs)


@router.get("/points/{point_id}", response_model=PointDetail, dependencies=_READ)
async def get_point(
    point_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, markets: ActiveMarkets
) -> PointDetail:
    service, point = await _point(point_id, session, user_id)
    return await service.detail(point, markets)


@router.patch("/points/{point_id}", response_model=PointOut, dependencies=_WRITE)
async def update_point(
    point_id: uuid.UUID, body: PointUpdate, session: SessionDep, user_id: CurrentUserId, markets: ActiveMarkets
) -> PointOut:
    service, point = await _point(point_id, session, user_id)
    return await service.update_point(point, body, user_id, markets)


@router.delete("/points/{point_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=_WRITE)
async def delete_point(point_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> Response:
    service, point = await _point(point_id, session, user_id)
    await service.delete_point(point, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/points/{point_id}/acknowledge", response_model=PointDetail, dependencies=_CONFIRM)
async def acknowledge(
    point_id: uuid.UUID, body: Acknowledge, session: SessionDep, user_id: CurrentUserId, markets: ActiveMarkets
) -> PointDetail:
    service, point = await _point(point_id, session, user_id)
    return await service.acknowledge(point, body, user_id, markets)


from app.modules.monitoring.plan_router import router as _plan_router  # noqa: E402

router.include_router(_plan_router)
