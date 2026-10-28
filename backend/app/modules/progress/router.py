# OpenConstructionERP - DataDrivenConstruction (DDC)
# DDC-CWICR-OE-2026
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Progress tracking API routes.

Endpoints:
    POST   /entries/                        - Record a progress observation
    GET    /entries/?project_id=X           - List entries (with filters)
    GET    /entries/{id}                    - Get single entry
    GET    /cumulative/?project_id=X        - Per-period breakdown + running total
    GET    /position/{position_id}/summary  - Position summary (parent rollup)
    GET    /s-curve/?project_id=X           - Actual vs planned S-curve
    GET    /quantity-variance/?project_id=X - Design vs earned quantity variance
    POST   /plan/                           - Upsert a planned data point
    GET    /plan/?project_id=X              - List plan data points
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.progress.schemas import (
    CumulativeProgressResponse,
    PositionProgressSummary,
    ProgressEntryCreate,
    ProgressEntryResponse,
    ProgressPlanCreate,
    ProgressPlanResponse,
    QuantityVarianceResponse,
    SCurveResponse,
)
from app.modules.progress.service import ProgressService

router = APIRouter(tags=["progress"])
logger = logging.getLogger(__name__)


def _get_service(session: SessionDep) -> ProgressService:
    return ProgressService(session)


def _entry_to_response(entry: object) -> ProgressEntryResponse:
    return ProgressEntryResponse(
        id=entry.id,  # type: ignore[attr-defined]
        project_id=entry.project_id,  # type: ignore[attr-defined]
        boq_position_id=getattr(entry, "boq_position_id", None),
        period_label=entry.period_label,  # type: ignore[attr-defined]
        percent_complete=float(entry.percent_complete),  # type: ignore[attr-defined]
        notes=getattr(entry, "notes", None),
        recorded_by=getattr(entry, "recorded_by", None),
        recorded_at=entry.recorded_at,  # type: ignore[attr-defined]
        geo_lat=float(entry.geo_lat) if getattr(entry, "geo_lat", None) is not None else None,  # type: ignore[attr-defined]
        geo_lon=float(entry.geo_lon) if getattr(entry, "geo_lon", None) is not None else None,  # type: ignore[attr-defined]
        photos=getattr(entry, "photos", None) or [],
        metadata=getattr(entry, "metadata_", None) or {},
        created_at=entry.created_at,  # type: ignore[attr-defined]
        updated_at=entry.updated_at,  # type: ignore[attr-defined]
    )


# ── Record entry ─────────────────────────────────────────────────────────────


@router.post("/entries/", response_model=ProgressEntryResponse, status_code=201)
async def record_entry(
    data: ProgressEntryCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("progress.create")),
    service: ProgressService = Depends(_get_service),
) -> ProgressEntryResponse:
    """Record a new percent-complete observation for a BOQ position."""
    await verify_project_access(data.project_id, user_id, session)
    try:
        entry = await service.record_entry(data, user_id=str(user_id))
        return _entry_to_response(entry)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unable to record progress entry")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to record progress entry",
        )


# ── List entries ─────────────────────────────────────────────────────────────


@router.get("/entries/", response_model=list[ProgressEntryResponse])
async def list_entries(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    boq_position_id: uuid.UUID | None = Query(default=None),
    period_label: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: ProgressService = Depends(_get_service),
) -> list[ProgressEntryResponse]:
    """List progress entries for a project with optional filters."""
    await verify_project_access(project_id, user_id, session)
    entries = await service.list_entries(
        project_id,
        boq_position_id=boq_position_id,
        period_label=period_label,
        offset=offset,
        limit=limit,
    )
    return [_entry_to_response(e) for e in entries]


# ── Get single entry ──────────────────────────────────────────────────────────


@router.get("/entries/{entry_id}", response_model=ProgressEntryResponse)
async def get_entry(
    entry_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: ProgressService = Depends(_get_service),
) -> ProgressEntryResponse:
    """Get a single progress entry by ID."""
    entry = await service.get_entry(entry_id)
    await verify_project_access(entry.project_id, str(user_id), session)  # type: ignore[arg-type]
    return _entry_to_response(entry)


# ── Cumulative breakdown ──────────────────────────────────────────────────────


@router.get("/cumulative/", response_model=CumulativeProgressResponse)
async def get_cumulative(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    boq_position_id: uuid.UUID | None = Query(default=None),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: ProgressService = Depends(_get_service),
) -> CumulativeProgressResponse:
    """Return per-period deltas and running cumulative % for a project or position.

    Deltas are computed as ``cumulative_pct[i] - cumulative_pct[i-1]``.
    Multiple entries in the same period are collapsed to the maximum reading.
    """
    await verify_project_access(project_id, user_id, session)
    return await service.get_cumulative(project_id, boq_position_id=boq_position_id)


# ── Position summary (parent rollup) ─────────────────────────────────────────


@router.get(
    "/position/{position_id}/summary",
    response_model=PositionProgressSummary,
)
async def get_position_summary(
    position_id: uuid.UUID,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: ProgressService = Depends(_get_service),
) -> PositionProgressSummary:
    """Get current progress for a BOQ position.

    If the position has children in the BOQ hierarchy, ``current_pct`` is the
    unweighted average of their latest percent_completes and ``is_rollup=true``
    is set in the response.
    """
    await verify_project_access(project_id, user_id, session)
    return await service.get_position_summary(project_id, position_id)


# ── S-curve ───────────────────────────────────────────────────────────────────


@router.get("/s-curve/", response_model=SCurveResponse)
async def get_s_curve(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: ProgressService = Depends(_get_service),
) -> SCurveResponse:
    """Return actual vs planned S-curve data for a project.

    Each point carries ``actual_cumulative_pct`` (from recorded entries) and
    ``planned_cumulative_pct`` (from the plan, or null if no plan exists for
    that period).
    """
    await verify_project_access(project_id, user_id, session)
    return await service.get_s_curve(project_id)


# --- Quantity variance --------------------------------------------------------


@router.get("/quantity-variance/", response_model=QuantityVarianceResponse)
async def get_quantity_variance(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("progress.read")),
    service: ProgressService = Depends(_get_service),
) -> QuantityVarianceResponse:
    """Design-vs-earned quantity variance for a project.

    For each BOQ position with a recorded progress observation, compares the
    installed-to-date quantity (design quantity x latest percent / 100)
    against the design quantity, reporting the variance, a guarded variance
    percent, and an over-run / under-run flag, then rolls the counts and
    totals up to the project.
    """
    await verify_project_access(project_id, user_id, session)
    return await service.get_quantity_variance(project_id)


# ── Plan management ───────────────────────────────────────────────────────────


@router.post("/plan/", response_model=ProgressPlanResponse, status_code=201)
async def upsert_plan_point(
    data: ProgressPlanCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("progress.plan_edit")),
    service: ProgressService = Depends(_get_service),
) -> ProgressPlanResponse:
    """Create or update a planned S-curve data point for a (project, period)."""
    await verify_project_access(data.project_id, user_id, session)
    try:
        plan = await service.upsert_plan_point(data)
        return ProgressPlanResponse(
            id=plan.id,
            project_id=plan.project_id,
            period_label=plan.period_label,
            planned_pct=float(plan.planned_pct),
            notes=plan.notes,
            created_at=plan.created_at,
            updated_at=plan.updated_at,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unable to upsert progress plan point")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to upsert plan point",
        )


@router.get("/plan/", response_model=list[ProgressPlanResponse])
async def list_plan(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: ProgressService = Depends(_get_service),
) -> list[ProgressPlanResponse]:
    """List all planned S-curve data points for a project."""
    await verify_project_access(project_id, user_id, session)
    plans = await service.list_plan(project_id)
    return [
        ProgressPlanResponse(
            id=p.id,
            project_id=p.project_id,
            period_label=p.period_label,
            planned_pct=float(p.planned_pct),
            notes=p.notes,
            created_at=p.created_at,
            updated_at=p.updated_at,
        )
        for p in plans
    ]
