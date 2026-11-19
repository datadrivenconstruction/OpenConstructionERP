# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Surfaces and volumes API routes (mounted at ``/api/v1/surfaces-volumes``).

Endpoints:
    GET    /projects/{project_id}/surfaces            - surfaces of a project
    POST   /projects/{project_id}/surfaces/from-points - triangulate imported point sets
    POST   /projects/{project_id}/surfaces/landxml     - import LandXML surfaces
    DELETE /surfaces/{surface_id}                      - remove an unused surface
    GET    /surfaces/{surface_id}/export               - one surface as LandXML or DXF
    GET    /projects/{project_id}/volumes             - calculations with their findings
    POST   /projects/{project_id}/volumes             - compute a new draft
    GET    /projects/{project_id}/summary             - KPI band
    GET    /projects/{project_id}/plan                - GeoJSON (WGS84) for the plan view
    GET    /projects/{project_id}/boq-positions       - BOQ lines a volume can feed
    GET    /volumes/{volume_id}                       - one calculation with its heat map
    PATCH  /volumes/{volume_id}                       - recompute a draft
    DELETE /volumes/{volume_id}                       - remove a draft
    POST   /volumes/{volume_id}/confirm               - confirm (survey.confirm)
    POST   /volumes/{volume_id}/duplicate             - copy into a new draft
    POST   /volumes/{volume_id}/send-to-boq           - write the quantity to a BOQ line
    POST   /volumes/{volume_id}/record-progress       - record measured progress
    GET    /volumes/{volume_id}/history               - who did what with the result
    GET    /volumes/{volume_id}/report.pdf            - volume report
    POST   /projects/{project_id}/surfaces/point-cloud - LAS/LAZ to a surface (tools_router)
    POST   /projects/{project_id}/staged-volumes       - cut/fill per stage (tools_router)
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response, status

from app.core.document_locale import normalize_document_locale
from app.core.i18n import SUPPORTED_LOCALES
from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.surfaces_volumes.schemas import (
    BoqPositionHitListResponse,
    ConfirmRequest,
    LandXmlImport,
    LandXmlResult,
    RecordProgress,
    RecordProgressResult,
    SendToBoq,
    SendToBoqResult,
    SurfaceFromPoints,
    SurfaceListResponse,
    SurfaceOut,
    VolumeCreate,
    VolumeDetail,
    VolumeDuplicate,
    VolumeEventListResponse,
    VolumeListResponse,
    VolumeSummary,
    VolumeUpdate,
)
from app.modules.surfaces_volumes.service import VolumesService
from app.modules.survey_core.permissions import require_survey_confirm

router = APIRouter(tags=["surfaces_volumes"])

_READ = [Depends(RequirePermission("survey.read"))]
_WRITE = [Depends(RequirePermission("survey.write"))]
_LOCALE = Query("en", max_length=10)


async def _volume(volume_id: uuid.UUID, session: SessionDep, user_id: str):
    service = VolumesService(session)
    v = await service.get_volume(volume_id)
    await verify_project_access(v.project_id, user_id, session)
    return service, v


# ── Surfaces ───────────────────────────────────────────────────────────────


@router.get("/projects/{project_id}/surfaces", response_model=SurfaceListResponse, dependencies=_READ)
async def list_surfaces(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    offset: int = Query(0, ge=0),
    limit: int = Query(1000, ge=1, le=5000),
) -> SurfaceListResponse:
    await verify_project_access(project_id, user_id, session)
    rows = await VolumesService(session).list_surfaces(project_id)
    return SurfaceListResponse(items=rows[offset : offset + limit], total=len(rows), offset=offset, limit=limit)


@router.post(
    "/projects/{project_id}/surfaces/from-points",
    response_model=SurfaceOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=_WRITE,
)
async def surface_from_points(
    project_id: uuid.UUID, body: SurfaceFromPoints, session: SessionDep, user_id: CurrentUserId
) -> SurfaceOut:
    await verify_project_access(project_id, user_id, session)
    return await VolumesService(session).surface_from_points(project_id, body, user_id)


@router.post(
    "/projects/{project_id}/surfaces/landxml",
    response_model=LandXmlResult,
    status_code=status.HTTP_201_CREATED,
    dependencies=_WRITE,
)
async def import_landxml(
    project_id: uuid.UUID, body: LandXmlImport, session: SessionDep, user_id: CurrentUserId
) -> LandXmlResult:
    await verify_project_access(project_id, user_id, session)
    return await VolumesService(session).import_landxml(project_id, body, user_id)


@router.delete("/surfaces/{surface_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=_WRITE)
async def delete_surface(surface_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> Response:
    service = VolumesService(session)
    s = await service.get_surface(surface_id)
    await verify_project_access(s.project_id, user_id, session)
    await service.delete_surface(s)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/surfaces/{surface_id}/export", response_class=Response, dependencies=_READ)
async def export_surface(
    surface_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    fmt: str = Query("landxml", alias="format", pattern="^(landxml|dxf)$"),
    locale: str = _LOCALE,
) -> Response:
    """One TIN surface as LandXML or DXF 3D faces."""
    from app.modules.survey_core.point_export import ExportSurface  # noqa: PLC0415
    from app.modules.survey_core.router import download  # noqa: PLC0415
    from app.modules.survey_core.service import SurveyService  # noqa: PLC0415

    s = await VolumesService(session).get_surface(surface_id)
    await verify_project_access(s.project_id, user_id, session)
    surface = ExportSurface(s.name, [tuple(v) for v in s.vertices or []], [tuple(f) for f in s.faces or []])
    text, findings = await SurveyService(session).write_points(
        s.project_id, [], fmt, surfaces=[surface], locale=locale, project_name=s.name
    )
    return download(text, fmt, f"surface-{s.name}", findings)


# ── Project views ──────────────────────────────────────────────────────────


@router.get("/projects/{project_id}/volumes", response_model=VolumeListResponse, dependencies=_READ)
async def list_volumes(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    locale: str = _LOCALE,
    offset: int = Query(0, ge=0),
    limit: int = Query(1000, ge=1, le=5000),
) -> VolumeListResponse:
    await verify_project_access(project_id, user_id, session)
    rows = await VolumesService(session).list_volumes(project_id, locale)
    return VolumeListResponse(items=rows[offset : offset + limit], total=len(rows), offset=offset, limit=limit)


@router.post(
    "/projects/{project_id}/volumes",
    response_model=VolumeDetail,
    status_code=status.HTTP_201_CREATED,
    dependencies=_WRITE,
)
async def create_volume(
    project_id: uuid.UUID, body: VolumeCreate, session: SessionDep, user_id: CurrentUserId
) -> VolumeDetail:
    await verify_project_access(project_id, user_id, session)
    return await VolumesService(session).create_volume(project_id, body, user_id)


@router.get("/projects/{project_id}/summary", response_model=VolumeSummary, dependencies=_READ)
async def summary(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> VolumeSummary:
    await verify_project_access(project_id, user_id, session)
    return await VolumesService(session).summary(project_id)


@router.get("/projects/{project_id}/plan", dependencies=_READ)
async def plan(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    volume_id: uuid.UUID | None = Query(None),
) -> dict:
    await verify_project_access(project_id, user_id, session)
    return await VolumesService(session).plan(project_id, volume_id)


@router.get("/projects/{project_id}/boq-positions", response_model=BoqPositionHitListResponse, dependencies=_READ)
async def boq_positions(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    q: str = Query("", max_length=100),
    unit: str = Query("m3", max_length=10),
    offset: int = Query(0, ge=0),
    limit: int = Query(1000, ge=1, le=5000),
) -> BoqPositionHitListResponse:
    await verify_project_access(project_id, user_id, session)
    rows = await VolumesService(session).search_positions(project_id, q.strip(), unit.strip())
    return BoqPositionHitListResponse(items=rows[offset : offset + limit], total=len(rows), offset=offset, limit=limit)


# ── One calculation ────────────────────────────────────────────────────────


@router.get("/volumes/{volume_id}", response_model=VolumeDetail, dependencies=_READ)
async def get_volume(
    volume_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, locale: str = _LOCALE
) -> VolumeDetail:
    service, v = await _volume(volume_id, session, user_id)
    return await service.detail(v, locale)


@router.patch("/volumes/{volume_id}", response_model=VolumeDetail, dependencies=_WRITE)
async def update_volume(
    volume_id: uuid.UUID, body: VolumeUpdate, session: SessionDep, user_id: CurrentUserId
) -> VolumeDetail:
    service, v = await _volume(volume_id, session, user_id)
    return await service.update_volume(v, body, user_id)


@router.delete("/volumes/{volume_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=_WRITE)
async def delete_volume(volume_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> Response:
    service, v = await _volume(volume_id, session, user_id)
    await service.delete_volume(v)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/volumes/{volume_id}/confirm",
    response_model=VolumeDetail,
    dependencies=[*_WRITE, Depends(require_survey_confirm)],
)
async def confirm_volume(
    volume_id: uuid.UUID,
    body: ConfirmRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    locale: str = _LOCALE,
) -> VolumeDetail:
    service, v = await _volume(volume_id, session, user_id)
    return await service.confirm(v, body, user_id, locale)


@router.post(
    "/volumes/{volume_id}/duplicate",
    response_model=VolumeDetail,
    status_code=status.HTTP_201_CREATED,
    dependencies=_WRITE,
)
async def duplicate_volume(
    volume_id: uuid.UUID, body: VolumeDuplicate, session: SessionDep, user_id: CurrentUserId
) -> VolumeDetail:
    service, v = await _volume(volume_id, session, user_id)
    return await service.duplicate(v, body, user_id)


@router.post(
    "/volumes/{volume_id}/send-to-boq",
    response_model=SendToBoqResult,
    dependencies=[*_WRITE, Depends(RequirePermission("boq.update"))],
)
async def send_to_boq(
    volume_id: uuid.UUID, body: SendToBoq, session: SessionDep, user_id: CurrentUserId, locale: str = _LOCALE
) -> SendToBoqResult:
    service, v = await _volume(volume_id, session, user_id)
    return await service.send_to_boq(v, body, user_id, locale)


@router.post("/volumes/{volume_id}/record-progress", response_model=RecordProgressResult, dependencies=_WRITE)
async def record_progress(
    volume_id: uuid.UUID, body: RecordProgress, session: SessionDep, user_id: CurrentUserId
) -> RecordProgressResult:
    service, v = await _volume(volume_id, session, user_id)
    return await service.record_progress(v, body, user_id)


@router.get("/volumes/{volume_id}/history", response_model=VolumeEventListResponse, dependencies=_READ)
async def history(
    volume_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    offset: int = Query(0, ge=0),
    limit: int = Query(1000, ge=1, le=5000),
) -> VolumeEventListResponse:
    service, v = await _volume(volume_id, session, user_id)
    rows = await service.history(v)
    return VolumeEventListResponse(items=rows[offset : offset + limit], total=len(rows), offset=offset, limit=limit)


@router.get("/volumes/{volume_id}/report.pdf", dependencies=_READ)
async def report_pdf(
    volume_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, locale: str = _LOCALE
) -> Response:
    from app.modules.projects.models import Project  # noqa: PLC0415
    from app.modules.surfaces_volumes.report_pdf import build_volume_report  # noqa: PLC0415

    service, v = await _volume(volume_id, session, user_id)
    detail = (await service.detail(v, locale)).model_dump(mode="json")
    events = [e.model_dump(mode="json") for e in await service.history(v)]
    project = await session.get(Project, v.project_id)
    pdf = build_volume_report(detail, project.name if project else "", events)
    await service.note_report(v, user_id)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{v.code}.pdf"',
            "Content-Language": normalize_document_locale(locale, SUPPORTED_LOCALES, "en"),
        },
    )


# Point cloud import and staged volumes live in their own file; same prefix and permissions.
from app.modules.surfaces_volumes.tools_router import router as _tools_router  # noqa: E402

router.include_router(_tools_router)
