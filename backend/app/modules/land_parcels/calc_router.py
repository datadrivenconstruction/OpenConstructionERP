# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Parcel subdivision, merge, corner register and setback routes, included in the parcels router.

Endpoints:
    POST  /parcels/{parcel_id}/split             - split by line or to an area (preview, then save)
    POST  /projects/{project_id}/parcels/merge   - merge two neighbouring parcels (preview, then save)
    GET   /parcels/{parcel_id}/corners           - the boundary corner register with precision checks
    PATCH /parcels/{parcel_id}/corners/{seq}     - corner status, precision class, precision, mark
    POST  /parcels/{parcel_id}/corners/stake     - a setting-out request with one stake per corner
    POST  /parcels/{parcel_id}/setback           - footprint distance to each boundary edge
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.core.active_markets import ActiveMarkets
from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.land_parcels.calc_schemas import (
    CornerPatch,
    CornerRegisterOut,
    MergeIn,
    SetbackIn,
    SetbackOut,
    SplitIn,
    SplitOut,
    StakeCornersIn,
    StakeCornersOut,
)
from app.modules.land_parcels.calc_service import ParcelCalcService
from app.modules.land_parcels.models import LandParcel

router = APIRouter(tags=["land_parcels"])

_READ = [Depends(RequirePermission("survey.read"))]
_WRITE = [Depends(RequirePermission("survey.write"))]
Locale = Annotated[str, Query(max_length=10)]


async def _parcel(service: ParcelCalcService, parcel_id: uuid.UUID, user_id: str) -> LandParcel:
    parcel = await service.get_parcel(parcel_id)
    await verify_project_access(parcel.project_id, user_id, service.session)
    return parcel


@router.post("/parcels/{parcel_id}/split", response_model=SplitOut, dependencies=_WRITE)
async def split_parcel(
    parcel_id: uuid.UUID, body: SplitIn, session: SessionDep, user_id: CurrentUserId, locale: Locale = "en"
) -> SplitOut:
    service = ParcelCalcService(session)
    return await service.split(await _parcel(service, parcel_id, user_id), body, user_id, locale)


@router.post("/projects/{project_id}/parcels/merge", response_model=SplitOut, dependencies=_WRITE)
async def merge_parcels(
    project_id: uuid.UUID, body: MergeIn, session: SessionDep, user_id: CurrentUserId, locale: Locale = "en"
) -> SplitOut:
    await verify_project_access(project_id, user_id, session)
    return await ParcelCalcService(session).merge(project_id, body, user_id, locale)


@router.get("/parcels/{parcel_id}/corners", response_model=CornerRegisterOut, dependencies=_READ)
async def get_corners(
    parcel_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, markets: ActiveMarkets, locale: Locale = "en"
) -> CornerRegisterOut:
    service = ParcelCalcService(session)
    return await service.corners(await _parcel(service, parcel_id, user_id), markets, locale)


@router.patch("/parcels/{parcel_id}/corners/{seq}", response_model=CornerRegisterOut, dependencies=_WRITE)
async def patch_corner(
    parcel_id: uuid.UUID,
    seq: int,
    body: CornerPatch,
    session: SessionDep,
    user_id: CurrentUserId,
    markets: ActiveMarkets,
    locale: Locale = "en",
) -> CornerRegisterOut:
    service = ParcelCalcService(session)
    parcel = await _parcel(service, parcel_id, user_id)
    return await service.patch_corner(parcel, seq, body, markets, user_id, locale)


@router.post(
    "/parcels/{parcel_id}/corners/stake",
    response_model=StakeCornersOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=_WRITE,
)
async def stake_corners(
    parcel_id: uuid.UUID, body: StakeCornersIn, session: SessionDep, user_id: CurrentUserId, markets: ActiveMarkets
) -> StakeCornersOut:
    service = ParcelCalcService(session)
    return await service.stake_corners(await _parcel(service, parcel_id, user_id), body, markets, user_id)


@router.post("/parcels/{parcel_id}/setback", response_model=SetbackOut, dependencies=_READ)
async def check_setback(
    parcel_id: uuid.UUID, body: SetbackIn, session: SessionDep, user_id: CurrentUserId, locale: Locale = "en"
) -> SetbackOut:
    service = ParcelCalcService(session)
    return await service.setback(await _parcel(service, parcel_id, user_id), body, locale)
