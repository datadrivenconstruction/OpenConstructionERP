# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Plan-editor land routes, included by the land parcels router (same prefix and permissions).

Endpoints:
    POST /projects/{project_id}/work-zones        - a work zone drawn on the plan
    GET  /work-zones/{zone_id}                    - ring, touched parcels and PAR-003 findings
    PUT  /work-zones/{zone_id}                    - edit the ring or the name
    GET  /projects/{project_id}/boundary-points   - the boundary point register (number, E/N, mark)
    POST /projects/{project_id}/demo/riverside    - six riverside parcels with deliberate errors
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.core.active_markets import ActiveMarkets
from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.land_parcels.plan_service import ParcelPlanService
from app.modules.land_parcels.schemas import BoundaryPointRegister, DemoLoadResult, WorkZoneDetail, WorkZoneIn

router = APIRouter(tags=["land_parcels"])

_READ = [Depends(RequirePermission("survey.read"))]
_WRITE = [Depends(RequirePermission("survey.write"))]
Locale = Annotated[str, Query(max_length=10)]


async def _zone(service: ParcelPlanService, zone_id: uuid.UUID, user_id: str):
    zone = await service.get_zone(zone_id)
    await verify_project_access(zone.project_id, user_id, service.session)
    return zone


@router.post(
    "/projects/{project_id}/work-zones",
    response_model=WorkZoneDetail,
    status_code=status.HTTP_201_CREATED,
    dependencies=_WRITE,
)
async def create_zone(
    project_id: uuid.UUID,
    body: WorkZoneIn,
    session: SessionDep,
    user_id: CurrentUserId,
    markets: ActiveMarkets,
    locale: Locale = "en",
) -> WorkZoneDetail:
    await verify_project_access(project_id, user_id, session)
    service = ParcelPlanService(session)
    zone = await service.create_zone(project_id, body, user_id)
    return await service.zone_detail(zone, markets, locale)


@router.get("/work-zones/{zone_id}", response_model=WorkZoneDetail, dependencies=_READ)
async def get_zone(
    zone_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, markets: ActiveMarkets, locale: Locale = "en"
) -> WorkZoneDetail:
    service = ParcelPlanService(session)
    return await service.zone_detail(await _zone(service, zone_id, user_id), markets, locale)


@router.put("/work-zones/{zone_id}", response_model=WorkZoneDetail, dependencies=_WRITE)
async def put_zone(
    zone_id: uuid.UUID,
    body: WorkZoneIn,
    session: SessionDep,
    user_id: CurrentUserId,
    markets: ActiveMarkets,
    locale: Locale = "en",
    base_rev: int | None = Query(None, ge=0),
) -> WorkZoneDetail:
    service = ParcelPlanService(session)
    zone = await service.update_zone(await _zone(service, zone_id, user_id), body, user_id, base_rev)
    return await service.zone_detail(zone, markets, locale)


@router.get("/projects/{project_id}/boundary-points", response_model=BoundaryPointRegister, dependencies=_READ)
async def boundary_points(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, markets: ActiveMarkets
) -> BoundaryPointRegister:
    await verify_project_access(project_id, user_id, session)
    return await ParcelPlanService(session).boundary_points(project_id, markets)


@router.post("/projects/{project_id}/demo/riverside", response_model=DemoLoadResult, dependencies=_WRITE)
async def load_demo(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> DemoLoadResult:
    await verify_project_access(project_id, user_id, session)
    return await ParcelPlanService(session).load_demo(project_id, user_id)
