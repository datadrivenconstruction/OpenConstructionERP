# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Surface tools routes, included by the surfaces router (same prefix and permissions).

Endpoints:
    POST /projects/{project_id}/surfaces/point-cloud - LAS/LAZ upload gridded to a surface
    POST /projects/{project_id}/staged-volumes       - cut and fill per stage over a surface chain
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.surfaces_volumes.pointcloud import STATS
from app.modules.surfaces_volumes.schemas import CloudImportResult, StagedRequest, StagedResult
from app.modules.surfaces_volumes.tools_service import SurfaceToolsService

router = APIRouter(tags=["surfaces_volumes"])

_READ = [Depends(RequirePermission("survey.read"))]
_WRITE = [Depends(RequirePermission("survey.write"))]
#: A drone or LiDAR tile; the upload is spooled to disk, never held in memory.
MAX_CLOUD_BYTES = 2 * 1024 * 1024 * 1024
_CLOUD_SUFFIXES = (".las", ".laz")


@router.post(
    "/projects/{project_id}/surfaces/point-cloud",
    response_model=CloudImportResult,
    status_code=status.HTTP_201_CREATED,
    dependencies=_WRITE,
)
async def import_point_cloud(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    file: UploadFile = File(...),
    name: str = Form("", max_length=255),
    cell_size_m: float = Form(0.5, gt=0, le=100),
    stat: str = Form("min"),
    ground_only: bool = Form(True),
    locale: str = Query("en", max_length=10),
) -> CloudImportResult:
    await verify_project_access(project_id, user_id, session)
    filename = (file.filename or "").strip()
    if not filename.lower().endswith(_CLOUD_SUFFIXES):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Upload a .las or .laz file")
    if stat not in STATS:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="stat is min, mean or max")
    if file.size is not None and file.size > MAX_CLOUD_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="The file is over 2 GB")
    return await SurfaceToolsService(session).import_cloud(
        project_id,
        file.file,
        filename=filename[:255],
        name=name,
        cell=cell_size_m,
        stat=stat,
        ground_only=ground_only,
        user_id=user_id,
        locale=locale,
    )


@router.post("/projects/{project_id}/staged-volumes", response_model=StagedResult, dependencies=_READ)
async def staged_volumes(
    project_id: uuid.UUID,
    body: StagedRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    locale: str = Query("en", max_length=10),
) -> StagedResult:
    await verify_project_access(project_id, user_id, session)
    return await SurfaceToolsService(session).staged(project_id, body, locale)
