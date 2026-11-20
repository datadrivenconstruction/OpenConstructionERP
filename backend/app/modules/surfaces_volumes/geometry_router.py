# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Plan-editor surface routes, included by the surfaces router (same prefix and permissions).

Endpoints:
    POST /projects/{project_id}/surfaces/pad        - design pad outline, level, batters to a TIN
    POST /projects/{project_id}/surfaces/pad/check  - live SRV-083 check of a pad being drawn
    GET  /surfaces/{surface_id}/contours            - contour lines (automatic or given interval)
    POST /surfaces/{surface_id}/sample              - heights along a polyline at offsets
    GET  /surfaces/{surface_id}/mesh                - vertices and triangles for hillshade
    GET  /volumes/{volume_id}/heat                  - base minus compare on a grid, for the cut/fill map
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.surfaces_volumes.geometry_schemas import (
    ContoursOut,
    MeshOut,
    PadCheckIn,
    PadCheckOut,
    PadCreate,
    PadOut,
    SampleIn,
    SampleOut,
)
from app.modules.surfaces_volumes.geometry_service import SurfaceGeometryService

router = APIRouter(tags=["surfaces_volumes"])

_READ = [Depends(RequirePermission("survey.read"))]
_WRITE = [Depends(RequirePermission("survey.write"))]


@router.post(
    "/projects/{project_id}/surfaces/pad",
    response_model=PadOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=_WRITE,
)
async def create_pad(
    project_id: uuid.UUID,
    body: PadCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    locale: str = Query("en", max_length=10),
) -> PadOut:
    await verify_project_access(project_id, user_id, session)
    return await SurfaceGeometryService(session).create_pad(project_id, body, user_id, locale)


@router.post("/projects/{project_id}/surfaces/pad/check", response_model=PadCheckOut, dependencies=_READ)
async def check_pad(
    project_id: uuid.UUID,
    body: PadCheckIn,
    session: SessionDep,
    user_id: CurrentUserId,
    locale: str = Query("en", max_length=10),
) -> PadCheckOut:
    await verify_project_access(project_id, user_id, session)
    return await SurfaceGeometryService(session).check_pad(project_id, body, locale)


async def _surface(surface_id: uuid.UUID, session: SessionDep, user_id: str):
    service = SurfaceGeometryService(session)
    s = await service.surface_in(None, surface_id)
    await verify_project_access(s.project_id, user_id, session)
    return service, s


@router.get("/surfaces/{surface_id}/contours", response_model=ContoursOut, dependencies=_READ)
async def contours(
    surface_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    interval: float | None = Query(None, gt=0, le=1000),
) -> ContoursOut:
    service, s = await _surface(surface_id, session, user_id)
    return await service.contours(s, interval)


@router.post("/surfaces/{surface_id}/sample", response_model=SampleOut, dependencies=_READ)
async def sample(surface_id: uuid.UUID, body: SampleIn, session: SessionDep, user_id: CurrentUserId) -> SampleOut:
    service, s = await _surface(surface_id, session, user_id)
    return await service.sample(s, body)


@router.get("/surfaces/{surface_id}/mesh", response_model=MeshOut, dependencies=_READ)
async def mesh(surface_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> MeshOut:
    service, s = await _surface(surface_id, session, user_id)
    return service.mesh(s)


@router.get("/volumes/{volume_id}/heat", dependencies=_READ)
async def volume_heat(volume_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict:
    """Cut (positive) and fill (negative) depth of a volume on a grid in project metres."""
    import asyncio  # noqa: PLC0415

    from app.modules.surfaces_volumes.dh_grid import dh_grid  # noqa: PLC0415
    from app.modules.surfaces_volumes.service import VolumesService, tin_of  # noqa: PLC0415

    volumes = VolumesService(session)
    vol = await volumes.get_volume(volume_id)
    await verify_project_access(vol.project_id, user_id, session)
    if vol.base_surface_id is None or vol.compare_surface_id is None:
        return {"volume_id": str(vol.id), "heat": None}
    base = tin_of(await volumes.get_surface(vol.base_surface_id))
    compare = tin_of(await volumes.get_surface(vol.compare_surface_id))
    heat, _ = await asyncio.to_thread(dh_grid, base, compare)
    return {"volume_id": str(vol.id), "heat": heat}
