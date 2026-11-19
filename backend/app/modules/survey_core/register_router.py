# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Point register routes, included by the survey_core router (same prefix and permissions).

Endpoints:
    GET    /points/{point_id}                        - one point with its source and what uses it
    PATCH  /points/{point_id}                        - edit a point (locked when a confirmed result uses it)
    DELETE /points/{point_id}                        - delete a point
    POST   /projects/{project_id}/points/bulk        - change code or kind, move to a set, delete
    POST   /projects/{project_id}/points/export      - CSV/TXT, DXF or LandXML of the selection
    GET    /projects/{project_id}/control            - control points with their check shots
    POST   /projects/{project_id}/control/checks     - record a check shot
    DELETE /projects/{project_id}/control/checks/{check_id} - remove a check shot
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response, status

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.survey_core.register_schemas import (
    BulkRequest,
    BulkResult,
    ControlCheckIn,
    ControlCheckOut,
    ControlListResponse,
    ExportRequest,
    PointDetail,
    PointUpdate,
)
from app.modules.survey_core.register_service import RegisterService

router = APIRouter(tags=["survey_core"])

_READ = [Depends(RequirePermission("survey.read"))]
_WRITE = [Depends(RequirePermission("survey.write"))]


async def _point(point_id: uuid.UUID, session: SessionDep, user_id: str):
    service = RegisterService(session)
    p = await service.get_point(point_id)
    await verify_project_access(p.project_id, user_id, session)
    return service, p


@router.get("/points/{point_id}", response_model=PointDetail, dependencies=_READ)
async def get_point(point_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> PointDetail:
    service, p = await _point(point_id, session, user_id)
    return await service.detail(p)


@router.patch("/points/{point_id}", response_model=PointDetail, dependencies=_WRITE)
async def update_point(
    point_id: uuid.UUID, body: PointUpdate, session: SessionDep, user_id: CurrentUserId
) -> PointDetail:
    service, p = await _point(point_id, session, user_id)
    return await service.update(p, body, user_id)


@router.delete("/points/{point_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=_WRITE)
async def delete_point(point_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> Response:
    service, p = await _point(point_id, session, user_id)
    await service.delete_point(p, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/projects/{project_id}/points/bulk", response_model=BulkResult, dependencies=_WRITE)
async def bulk_points(
    project_id: uuid.UUID, body: BulkRequest, session: SessionDep, user_id: CurrentUserId
) -> BulkResult:
    await verify_project_access(project_id, user_id, session)
    return await RegisterService(session).bulk(project_id, body, user_id)


@router.post("/projects/{project_id}/points/export", dependencies=_READ)
async def export_points(
    project_id: uuid.UUID, body: ExportRequest, session: SessionDep, user_id: CurrentUserId
) -> Response:
    await verify_project_access(project_id, user_id, session)
    data, media, ext = await RegisterService(session).export(project_id, body)
    return Response(
        content=data,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="survey_points.{ext}"'},
    )


@router.get("/projects/{project_id}/control", response_model=ControlListResponse, dependencies=_READ)
async def list_control(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> ControlListResponse:
    await verify_project_access(project_id, user_id, session)
    return await RegisterService(session).control(project_id)


@router.post(
    "/projects/{project_id}/control/checks",
    response_model=ControlCheckOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=_WRITE,
)
async def add_control_check(
    project_id: uuid.UUID, body: ControlCheckIn, session: SessionDep, user_id: CurrentUserId
) -> ControlCheckOut:
    await verify_project_access(project_id, user_id, session)
    return await RegisterService(session).add_check(project_id, body, user_id)


@router.delete(
    "/projects/{project_id}/control/checks/{check_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=_WRITE
)
async def delete_control_check(
    project_id: uuid.UUID, check_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> Response:
    await verify_project_access(project_id, user_id, session)
    await RegisterService(session).delete_check(project_id, check_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
