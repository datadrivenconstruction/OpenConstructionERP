# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Coordination Hub API routes.

Mounted by the loader at ``/api/v1/coordination``.

Endpoints
    GET /projects/{project_id}/dashboard      → KPI rollup
    GET /projects/{project_id}/trade-matrix   → 6×6 discipline-pair matrix
    GET /projects/{project_id}/timeline       → activity stream (?days=N)

Auth pattern matches the sibling clash/clash_cost_impact routers:

    * A coarse ``RequirePermission("coordination.read")`` gate as a
      FastAPI dependency.
    * A per-project IDOR guard (``verify_project_access``) checked
      inside each route so a VIEWER of project A can never read project
      B's coordination signal.

The aggregator service is defensive - every sub-module is wrapped in a
``_safe_count`` (see :mod:`app.modules.coordination_hub.service`) so a
partial deploy still returns honest zeros instead of 500s.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import select

from app.dependencies import (
    CurrentUserPayload,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.coordination_hub.models import KNOWN_METRICS
from app.modules.coordination_hub.schemas import (
    CoordinationDashboardResponse,
    CoordinationThresholdsResponse,
    CoordinationThresholdUpdate,
    ThresholdRow,
    TimelineResponse,
    TradeMatrixResponse,
)
from app.modules.coordination_hub.service import CoordinationHubService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Coordination Hub"])


def _get_service(session: SessionDep) -> CoordinationHubService:
    return CoordinationHubService(session)


async def _load_project_currency(
    session: SessionDep,
    project_id: uuid.UUID,
) -> str:
    """Resolve the project's display currency for the dashboard header.

    The project row is already loaded by :func:`verify_project_access`;
    we re-issue a tiny scalar SELECT here rather than thread the row
    through because the verify helper returns ``None`` and surfaces a
    404 before this runs.
    """
    from app.modules.projects.models import Project

    stmt = select(Project.currency).where(Project.id == project_id)
    result = await session.execute(stmt)
    currency = result.scalar()
    # Empty-string fallback (not a hard-coded "EUR") - the project row's
    # currency is authoritative; absent that we surface the absence so
    # the UI can render unitless rather than mis-label totals.
    # See feedback/v3_db_eur_defaults_killed.
    return currency or ""


@router.get(
    "/projects/{project_id}/dashboard",
    response_model=CoordinationDashboardResponse,
    dependencies=[Depends(RequirePermission("coordination.read"))],
)
async def get_dashboard(
    project_id: uuid.UUID,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: CoordinationHubService = Depends(_get_service),
) -> CoordinationDashboardResponse:
    """KPI rollup across every coordination signal for one project."""
    user_id = payload.get("sub", "")
    await verify_project_access(project_id, user_id, session)
    currency = await _load_project_currency(session, project_id)
    return await service.dashboard(project_id, currency=currency)


@router.get(
    "/projects/{project_id}/trade-matrix",
    response_model=TradeMatrixResponse,
    dependencies=[Depends(RequirePermission("coordination.read"))],
)
async def get_trade_matrix(
    project_id: uuid.UUID,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: CoordinationHubService = Depends(_get_service),
) -> TradeMatrixResponse:
    """6×6 discipline-pair grid of clashes - drives the heat-map cell."""
    user_id = payload.get("sub", "")
    await verify_project_access(project_id, user_id, session)
    currency = await _load_project_currency(session, project_id)
    return await service.trade_matrix(project_id, currency=currency)


@router.get(
    "/projects/{project_id}/timeline",
    response_model=TimelineResponse,
    dependencies=[Depends(RequirePermission("coordination.read"))],
)
async def get_timeline(
    project_id: uuid.UUID,
    payload: CurrentUserPayload,
    session: SessionDep,
    days: int = Query(
        default=30,
        ge=1,
        le=365,
        description="Lookback window in days (1–365). Defaults to 30.",
    ),
    service: CoordinationHubService = Depends(_get_service),
) -> TimelineResponse:
    """Recent activity across federations / clash runs / rules / BCF."""
    user_id = payload.get("sub", "")
    await verify_project_access(project_id, user_id, session)
    return await service.timeline(project_id, days=days)


@router.get(
    "/projects/{project_id}/export.csv",
    response_class=PlainTextResponse,
    dependencies=[Depends(RequirePermission("coordination.read"))],
)
async def export_snapshot_csv(
    project_id: uuid.UUID,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: CoordinationHubService = Depends(_get_service),
) -> PlainTextResponse:
    """Download the live coordination snapshot as a single CSV file.

    One attachable artefact for a coordination meeting: headline KPIs +
    threshold-alert status + the per-discipline-pair (cost-weighted)
    breakdown. Always reflects live numbers (the dashboard TTL cache is
    bypassed for the export). Read-only - same ``coordination.read`` gate
    as the dashboard, with the per-project IDOR guard.
    """
    user_id = payload.get("sub", "")
    await verify_project_access(project_id, user_id, session)
    currency = await _load_project_currency(session, project_id)
    csv_text = await service.export_snapshot_csv(project_id, currency=currency)
    filename = f"coordination-{project_id}.csv"
    return PlainTextResponse(
        content=csv_text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Thresholds ─────────────────────────────────────────────────────────────


@router.get(
    "/projects/{project_id}/thresholds",
    response_model=CoordinationThresholdsResponse,
    dependencies=[Depends(RequirePermission("coordination.read"))],
)
async def list_thresholds(
    project_id: uuid.UUID,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: CoordinationHubService = Depends(_get_service),
) -> CoordinationThresholdsResponse:
    """Return the project's thresholds + their current evaluated state.

    Defaults seed on first access **for callers holding
    ``coordination.write``** so operators always see something they can
    edit and the alert banner has data to render against. A plain
    ``coordination.read`` caller (VIEWER) gets ephemeral defaults so a
    GET never triggers a DB write - the seed runs the first time an
    EDITOR / MANAGER / ADMIN touches the threshold view.
    """
    user_id = payload.get("sub", "")
    await verify_project_access(project_id, user_id, session)
    # Determine seed authority from the caller's live permissions /
    # role. Mirrors the same check ``RequirePermission("coordination.write")``
    # would do - but inline because the surrounding gate is the coarser
    # ``coordination.read``.
    perms: list[str] = payload.get("permissions", []) or []
    role: str = payload.get("role", "") or ""
    can_seed = role == "admin" or "coordination.write" in perms
    if not can_seed:
        # Fall through to the live registry so a stale JWT (issued
        # before a role-permission map change) still honours the
        # current mapping - same pattern as RequirePermission uses.
        try:
            from app.core.permissions import permission_registry as _reg

            can_seed = _reg.role_has_permission(role, "coordination.write")
        except Exception:  # noqa: BLE001 - registry is best-effort here
            can_seed = False
    return await service.evaluate_thresholds(project_id, allow_seed=can_seed)


@router.put(
    "/projects/{project_id}/thresholds/{metric}",
    response_model=ThresholdRow,
    dependencies=[Depends(RequirePermission("coordination.write"))],
)
async def update_threshold(
    project_id: uuid.UUID,
    metric: str,
    data: CoordinationThresholdUpdate,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: CoordinationHubService = Depends(_get_service),
) -> ThresholdRow:
    """Patch one threshold's warn / error value or its ``enabled`` flag.

    422s on unknown metric keys so a typo can never persist an orphan
    row no evaluator reads. The dashboard cache is invalidated inside
    the service so the next poll picks up the new threshold.
    """
    user_id = payload.get("sub", "")
    await verify_project_access(project_id, user_id, session)
    if metric not in KNOWN_METRICS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Unknown coordination metric '{metric}'.",
        )
    try:
        row = await service.update_threshold(
            project_id,
            metric,
            warn_value=data.warn_value,
            error_value=data.error_value,
            enabled=data.enabled,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    # Re-evaluate to surface the updated row with current_value + level.
    evaluated = await service.evaluate_thresholds(project_id)
    for tr in evaluated.thresholds:
        if tr.metric == row.metric:
            return tr
    # Fallback - return the persisted row with neutral evaluation state.
    return ThresholdRow(
        metric=row.metric,
        warn_value=row.warn_value,
        error_value=row.error_value,
        enabled=row.enabled,
        current_value=row.warn_value,
        level="ok",
        message="",
    )
