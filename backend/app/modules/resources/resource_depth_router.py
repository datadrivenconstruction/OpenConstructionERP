# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Resource-depth API routes (T3.1).

Effective-dated rates, per-assignment spreading curves, the native-units setter,
and the time-phased histogram. Included into the resources ``router`` via
``router.include_router`` so it mounts under ``/api/v1/resources``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.resources.resource_depth_schemas import (
    AssignmentUnitsPatch,
    AssignmentUnitsResponse,
    CurveResponse,
    CurveUpsert,
    HistogramCellResponse,
    RateCreate,
    RatePatch,
    RateResponse,
    ResourceHistogramResponse,
)
from app.modules.resources.resource_depth_service import ResourceDepthService

resource_depth_router = APIRouter(tags=["resources"])


def _get_depth_service(session: SessionDep) -> ResourceDepthService:
    return ResourceDepthService(session)


async def _guard_assignment(
    assignment_id: uuid.UUID,
    user_id: str | None,
    session: SessionDep,
    service: ResourceDepthService,
) -> None:
    """Verify cross-project access on the project an assignment belongs to.

    ``RequirePermission(...)`` only checks role/permission scope - it does not
    prove the caller may reach the *specific* project the assignment is filed
    against. The assignment routes in the parent router resolve that project
    and run it through ``verify_project_access``; the curve and units routes
    here are keyed by the same assignment id and need the same check, or any
    reader could fetch another project's curve by guessing a UUID and any
    editor could rewrite it. Run before the service call so a later 404 or 409
    cannot confirm that a foreign row exists. ``verify_project_access`` answers
    404 on both "missing" and "denied", so the response is opaque.
    """
    assignment = await service.base.get_assignment(assignment_id)
    if assignment.project_id is not None:
        await verify_project_access(assignment.project_id, user_id, session)


# ── Rates ──────────────────────────────────────────────────────────────────


@resource_depth_router.get("/resources/{resource_id}/rates/", response_model=list[RateResponse])
async def list_rates(
    resource_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("resources.read")),
    service: ResourceDepthService = Depends(_get_depth_service),
) -> list[RateResponse]:
    rows = await service.list_rates(resource_id)
    return [RateResponse.model_validate(r) for r in rows]


@resource_depth_router.post("/rates/", response_model=RateResponse, status_code=201)
async def create_rate(
    data: RateCreate,
    _perm: None = Depends(RequirePermission("resources.create")),
    service: ResourceDepthService = Depends(_get_depth_service),
) -> RateResponse:
    rate = await service.create_rate(data)
    return RateResponse.model_validate(rate)


@resource_depth_router.patch("/rates/{rate_id}", response_model=RateResponse)
async def patch_rate(
    rate_id: uuid.UUID,
    data: RatePatch,
    _perm: None = Depends(RequirePermission("resources.update")),
    service: ResourceDepthService = Depends(_get_depth_service),
) -> RateResponse:
    rate = await service.patch_rate(rate_id, data)
    return RateResponse.model_validate(rate)


@resource_depth_router.delete("/rates/{rate_id}", status_code=204)
async def delete_rate(
    rate_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("resources.delete")),
    service: ResourceDepthService = Depends(_get_depth_service),
) -> None:
    await service.delete_rate(rate_id)


# ── Curves ─────────────────────────────────────────────────────────────────


@resource_depth_router.get("/assignments/{assignment_id}/curve", response_model=CurveResponse)
async def get_curve(
    assignment_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("resources.read")),
    service: ResourceDepthService = Depends(_get_depth_service),
) -> CurveResponse:
    await _guard_assignment(assignment_id, user_id, session, service)
    curve = await service.get_curve(assignment_id)
    if curve is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Curve not found")
    return CurveResponse.model_validate(curve)


@resource_depth_router.put("/assignments/{assignment_id}/curve", response_model=CurveResponse)
async def upsert_curve(
    assignment_id: uuid.UUID,
    data: CurveUpsert,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("resources.update")),
    service: ResourceDepthService = Depends(_get_depth_service),
) -> CurveResponse:
    await _guard_assignment(assignment_id, user_id, session, service)
    curve = await service.upsert_curve(assignment_id, data)
    return CurveResponse.model_validate(curve)


@resource_depth_router.delete("/assignments/{assignment_id}/curve", status_code=204)
async def delete_curve(
    assignment_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("resources.update")),
    service: ResourceDepthService = Depends(_get_depth_service),
) -> None:
    await _guard_assignment(assignment_id, user_id, session, service)
    await service.delete_curve(assignment_id)


# ── Native units ───────────────────────────────────────────────────────────


@resource_depth_router.patch("/assignments/{assignment_id}/units", response_model=AssignmentUnitsResponse)
async def set_assignment_units(
    assignment_id: uuid.UUID,
    data: AssignmentUnitsPatch,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("resources.update")),
    service: ResourceDepthService = Depends(_get_depth_service),
) -> AssignmentUnitsResponse:
    await _guard_assignment(assignment_id, user_id, session, service)
    updated = await service.set_units(assignment_id, data)
    return AssignmentUnitsResponse(
        assignment_id=updated.id,
        units=float(updated.units) if updated.units is not None else None,
        unit_kind=updated.unit_kind,
    )


# ── Histogram ──────────────────────────────────────────────────────────────


@resource_depth_router.get("/resources/{resource_id}/histogram", response_model=ResourceHistogramResponse)
async def resource_histogram_view(
    resource_id: uuid.UUID,
    user_id: CurrentUserId,
    start: datetime = Query(...),
    end: datetime = Query(...),
    bucket: str = Query(default="week", pattern=r"^(week|month)$"),
    rate_type: str = Query(default="cost", max_length=16),
    hours_per_day: float = Query(default=8.0, gt=0, le=24),
    _perm: None = Depends(RequirePermission("resources.read")),
    service: ResourceDepthService = Depends(_get_depth_service),
) -> ResourceHistogramResponse:
    """Time-phased demand / availability / cost histogram for one resource.

    Demand is each overlapping booking's native ``units`` (falling back to its
    percent allocation) spread by its curve; the cost lane prices that demand at
    the effective-dated rate in force. Bookings on projects the caller cannot
    reach are omitted; a bucket covered by an unavailable / holiday / sick window
    has zero availability. Read-only - nothing is moved.
    """
    if end <= start:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="end must be after start")
    payload = await service.histogram(
        resource_id,
        start,
        end,
        str(user_id),
        bucket=bucket,
        rate_type=rate_type,
        hours_per_day=hours_per_day,
    )
    cells = [HistogramCellResponse.model_validate(c) for c in payload["cells"]]
    return ResourceHistogramResponse(
        resource_id=payload["resource_id"],
        bucket=payload["bucket"],
        capacity_units=payload["capacity_units"],
        peak_demand=payload["peak_demand"],
        over_allocated_buckets=payload["over_allocated_buckets"],
        cells=cells,
    )
