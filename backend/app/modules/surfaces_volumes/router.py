# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Surfaces and volumes API routes (mounted at ``/api/v1/surfaces-volumes``).

Endpoints:
    GET    /projects/{project_id}/surfaces            - surfaces of a project
    POST   /projects/{project_id}/surfaces/from-points - triangulate imported point sets
    POST   /projects/{project_id}/surfaces/landxml     - import LandXML surfaces
    DELETE /surfaces/{surface_id}                      - remove an unused surface
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
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response, status

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.surfaces_volumes.schemas import (
    BoqPositionHit,
    ConfirmRequest,
    LandXmlImport,
    LandXmlResult,
    RecordProgress,
    RecordProgressResult,
    SendToBoq,
    SendToBoqResult,
    SurfaceFromPoints,
    SurfaceOut,
    VolumeCreate,
    VolumeDetail,
    VolumeDuplicate,
    VolumeEventOut,
    VolumeOut,
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


@router.get("/projects/{project_id}/surfaces", response_model=list[SurfaceOut], dependencies=_READ)
async def list_surfaces(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> list[SurfaceOut]:
    await verify_project_access(project_id, user_id, session)
    return await VolumesService(session).list_surfaces(project_id)


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


# ── Project views ──────────────────────────────────────────────────────────


@router.get("/projects/{project_id}/volumes", response_model=list[VolumeOut], dependencies=_READ)
async def list_volumes(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, locale: str = _LOCALE
) -> list[VolumeOut]:
    await verify_project_access(project_id, user_id, session)
    return await VolumesService(session).list_volumes(project_id, locale)


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


@router.get("/projects/{project_id}/boq-positions", response_model=list[BoqPositionHit], dependencies=_READ)
async def boq_positions(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    q: str = Query("", max_length=100),
    unit: str = Query("m3", max_length=10),
) -> list[BoqPositionHit]:
    await verify_project_access(project_id, user_id, session)
    return await VolumesService(session).search_positions(project_id, q.strip(), unit.strip())


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


@router.get("/volumes/{volume_id}/history", response_model=list[VolumeEventOut], dependencies=_READ)
async def history(volume_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> list[VolumeEventOut]:
    service, v = await _volume(volume_id, session, user_id)
    return await service.history(v)


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
        headers={"Content-Disposition": f'attachment; filename="{v.code}.pdf"'},
    )
