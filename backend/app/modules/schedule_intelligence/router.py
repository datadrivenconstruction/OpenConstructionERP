"""Schedule Intelligence API routes.

Mounted automatically by the module loader at
``/api/v1/schedule-intelligence/``. Phase 0 exposes the governance surface
only — locked figures (E5.2) and confidence configuration/preview (E5.3).
Insight endpoints (readiness, risk, decision) land with their engines.

Every project-scoped endpoint is gated twice: ``RequirePermission`` checks the
RBAC verb, and ``verify_project_access`` checks the caller may touch *this*
project (404-on-deny IDOR defence). Applying a locked-figure change is refused
by the guard with a 409 that names exactly what was blocked.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status

from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.schedule_intelligence import service
from app.modules.schedule_intelligence.confidence import ConfidencePolicy
from app.modules.schedule_intelligence.models import ReadinessResult
from app.modules.schedule_intelligence.schemas import (
    ConfidenceConfigRead,
    ConfidenceConfigUpsert,
    ConfidencePreviewRequest,
    ConfidencePreviewResponse,
    LockedFigureRead,
    LockFigureRequest,
    ReadinessEvaluateRequest,
    ReadinessResultRead,
    ReadinessRunResponse,
    VerifyWritesRequest,
    VerifyWritesResponse,
    WriteViolation,
)

router = APIRouter(tags=["schedule_intelligence"])


def _as_uuid(user_id: str) -> uuid.UUID | None:
    """Best-effort parse of the JWT subject into a UUID for audit columns."""
    try:
        return uuid.UUID(str(user_id))
    except (ValueError, TypeError):
        return None


def _readiness_run_response(
    run_id: str | None,
    rows: list[ReadinessResult],
) -> ReadinessRunResponse:
    counts: dict[str, int] = {"ready": 0, "at_risk": 0, "blocked": 0}
    for r in rows:
        counts[r.classification] = counts.get(r.classification, 0) + 1
    look_ahead_ref = rows[0].look_ahead_ref if rows else None
    return ReadinessRunResponse(
        evaluation_run_id=run_id,
        look_ahead_ref=look_ahead_ref,
        counts=counts,
        results=[ReadinessResultRead.model_validate(r) for r in rows],
    )


def _config_read(source: str, policy: ConfidencePolicy) -> ConfidenceConfigRead:
    return ConfidenceConfigRead(
        source=source,
        version=policy.version,
        band_thresholds=dict(policy.band_thresholds),
        schedule_quality_caps=dict(policy.schedule_quality_caps),
        feed_coverage_caps=dict(policy.feed_coverage_caps),
        corroboration_bonuses=dict(policy.corroboration_bonuses),
    )


@router.get("/")
async def module_info() -> dict[str, str]:
    """Health-style ping so operators can confirm the module mounted."""
    return {"module": "oe_schedule_intelligence", "status": "active"}


# ─────────────────────────────────────────────────────────────────────────────
# E5.2 — Locked figures
# ─────────────────────────────────────────────────────────────────────────────
@router.post(
    "/projects/{project_id}/locked-figures",
    response_model=LockedFigureRead,
    status_code=status.HTTP_201_CREATED,
)
async def lock_figure(
    project_id: uuid.UUID,
    payload: LockFigureRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    _: None = Depends(RequirePermission("schedule_intelligence.lock")),
) -> LockedFigureRead:
    await verify_project_access(project_id, user_id, session)
    row = await service.lock_figure(session, project_id, payload, _as_uuid(user_id))
    await session.commit()
    return LockedFigureRead.model_validate(row)


@router.get(
    "/projects/{project_id}/locked-figures",
    response_model=list[LockedFigureRead],
)
async def list_locked_figures(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    include_inactive: bool = Query(False),
    _: None = Depends(RequirePermission("schedule_intelligence.read")),
) -> list[LockedFigureRead]:
    await verify_project_access(project_id, user_id, session)
    rows = await service.list_locked_figures(session, project_id, include_inactive=include_inactive)
    return [LockedFigureRead.model_validate(r) for r in rows]


@router.post(
    "/projects/{project_id}/locked-figures/{figure_id}/unlock",
    response_model=LockedFigureRead,
)
async def unlock_figure(
    project_id: uuid.UUID,
    figure_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _: None = Depends(RequirePermission("schedule_intelligence.lock")),
) -> LockedFigureRead:
    await verify_project_access(project_id, user_id, session)
    row = await service.unlock_figure(session, project_id, figure_id, _as_uuid(user_id))
    await session.commit()
    return LockedFigureRead.model_validate(row)


@router.post(
    "/projects/{project_id}/locked-figures/verify",
    response_model=VerifyWritesResponse,
)
async def verify_writes(
    project_id: uuid.UUID,
    payload: VerifyWritesRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    _: None = Depends(RequirePermission("schedule_intelligence.read")),
) -> VerifyWritesResponse:
    """Dry-run proposed writes against active locks (read-only preview)."""
    await verify_project_access(project_id, user_id, session)
    violations = await service.verify_writes(session, project_id, payload)
    return VerifyWritesResponse(
        ok=not violations,
        violations=[
            WriteViolation(
                path=v.path,
                locked_value=v.locked_value,
                attempted_value=v.attempted_value,
            )
            for v in violations
        ],
    )


# ─────────────────────────────────────────────────────────────────────────────
# E5.3 — Confidence configuration + preview
# ─────────────────────────────────────────────────────────────────────────────
@router.get(
    "/projects/{project_id}/confidence-config",
    response_model=ConfidenceConfigRead,
)
async def get_confidence_config(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _: None = Depends(RequirePermission("schedule_intelligence.read")),
) -> ConfidenceConfigRead:
    await verify_project_access(project_id, user_id, session)
    policy, source = await service.resolve_policy(session, project_id)
    return _config_read(source, policy)


@router.put(
    "/projects/{project_id}/confidence-config",
    response_model=ConfidenceConfigRead,
    status_code=status.HTTP_201_CREATED,
)
async def upsert_confidence_config(
    project_id: uuid.UUID,
    payload: ConfidenceConfigUpsert,
    session: SessionDep,
    user_id: CurrentUserId,
    _: None = Depends(RequirePermission("schedule_intelligence.configure")),
) -> ConfidenceConfigRead:
    await verify_project_access(project_id, user_id, session)
    await service.upsert_confidence_config(session, project_id, payload, _as_uuid(user_id))
    await session.commit()
    policy, source = await service.resolve_policy(session, project_id)
    return _config_read(source, policy)


@router.post(
    "/projects/{project_id}/confidence/preview",
    response_model=ConfidencePreviewResponse,
)
async def preview_confidence(
    project_id: uuid.UUID,
    payload: ConfidencePreviewRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    _: None = Depends(RequirePermission("schedule_intelligence.read")),
) -> ConfidencePreviewResponse:
    await verify_project_access(project_id, user_id, session)
    result = await service.preview_confidence(session, project_id, payload)
    return ConfidencePreviewResponse(score=result.score, band=result.band, rationale=result.rationale)


# ─────────────────────────────────────────────────────────────────────────────
# E1 — Readiness (Watch)
# ─────────────────────────────────────────────────────────────────────────────
@router.post(
    "/projects/{project_id}/look-aheads/{look_ahead_id}/readiness/evaluate",
    response_model=ReadinessRunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def evaluate_readiness(
    project_id: uuid.UUID,
    look_ahead_id: uuid.UUID,
    payload: ReadinessEvaluateRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    _: None = Depends(RequirePermission("schedule_intelligence.watch")),
) -> ReadinessRunResponse:
    """Evaluate & snapshot Ready/At-risk/Blocked for a look-ahead's activities.

    Idempotent: re-running over identical inputs returns the existing run.
    """
    await verify_project_access(project_id, user_id, session)
    run_id, rows = await service.evaluate_readiness(session, project_id, look_ahead_id, today=payload.today)
    await session.commit()
    return _readiness_run_response(run_id, rows)


@router.get(
    "/projects/{project_id}/readiness",
    response_model=ReadinessRunResponse,
)
async def list_readiness(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    look_ahead_id: uuid.UUID | None = Query(None),
    _: None = Depends(RequirePermission("schedule_intelligence.read")),
) -> ReadinessRunResponse:
    """Return the latest readiness run (optionally scoped to one look-ahead)."""
    await verify_project_access(project_id, user_id, session)
    run_id, rows = await service.list_readiness(session, project_id, look_ahead_id=look_ahead_id)
    return _readiness_run_response(run_id, rows)
