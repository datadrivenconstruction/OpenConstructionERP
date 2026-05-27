# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""‌⁠‍Clash cost-impact API routes.

The module-loader mounts this router at ``/api/v1/clash-cost-impact``
(kebab-cased directory name, per the loader convention).

Endpoints
    GET /clash/{clash_id}/impact          → per-clash breakdown
    GET /project/{project_id}/rollup      → project-wide rollup

Both endpoints require BOTH ``clash.read`` AND ``boq.read`` because the
response cross-cuts two modules. The runtime ``boq.read`` check sits in
the route body (rather than as a second ``RequirePermission`` dep) so
that an absent ``boq.read`` produces a clear 403 with the missing-
permission name, matching the rest of the codebase. Project ownership
is verified via the shared ``verify_project_access`` helper for both
endpoints (so a viewer of project A can never lift project B's clash
cost data through this surface).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import (
    CurrentUserPayload,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.clash_cost_impact.schemas import (
    ClashCostImpactResponse,
    ProjectCostImpactRollupResponse,
)
from app.modules.clash_cost_impact.service import ClashCostImpactService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Clash Cost Impact"])


def _get_service(session: SessionDep) -> ClashCostImpactService:
    return ClashCostImpactService(session)


def _require_boq_read(payload: dict[str, Any]) -> None:
    """Second permission gate — the cross-module ``boq.read`` requirement.

    The first ``clash.read`` gate is enforced by the route-level
    ``RequirePermission`` dependency; this in-body check completes the
    AND-pair. Admins bypass via the role check (same convention as
    :class:`RequirePermission`).
    """
    if payload.get("role") == "admin":
        return
    perms: list[str] = payload.get("permissions", []) or []
    if "boq.read" in perms:
        return
    # Tolerate stale JWTs by falling through to the live registry —
    # matches RequirePermission's stale-token branch.
    try:
        from app.core.permissions import permission_registry as _reg

        if _reg.role_has_permission(payload.get("role", ""), "boq.read"):
            return
    except Exception:  # noqa: BLE001
        logger.exception("Live-registry boq.read fallback failed")
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Missing permission: boq.read",
    )


@router.get(
    "/clash/{clash_id}/impact",
    response_model=ClashCostImpactResponse,
    dependencies=[Depends(RequirePermission("clash.read"))],
)
async def get_clash_impact(
    clash_id: uuid.UUID,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: ClashCostImpactService = Depends(_get_service),
) -> ClashCostImpactResponse:
    """Cost-impact breakdown for a single clash.

    Returns a 404 if the clash (or its owning run / project) does not
    exist, and a 403 if the caller cannot see the project the clash
    belongs to (IDOR guard).
    """
    _require_boq_read(payload)
    # Resolve owning project FIRST so the access check runs before any
    # impact computation. This removes the 404-vs-403 timing oracle
    # where a non-existent clash would return immediately while an
    # existing-but-forbidden clash would only fail after the full
    # impact computation.
    user_id = payload.get("sub", "")
    project_id = await service.project_id_for_clash(clash_id)
    if project_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Clash {clash_id} not found",
        )
    await verify_project_access(project_id, user_id, session)
    impact, _ = await service.impact_for_clash(clash_id)
    if impact is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Clash {clash_id} not found",
        )
    return ClashCostImpactResponse.model_validate(impact)


#: Accepted ``status`` query values for the rollup endpoint. The two
#: aggregate aliases are ``open`` (the open-statuses tuple) and ``all``
#: (no filter); the remaining values are the per-row statuses surfaced
#: by the clash module. Anything else returns 400 — silently accepting
#: arbitrary strings used to produce empty rollups that looked like a
#: clean project, which is misleading on a money endpoint.
_ALLOWED_STATUS_FILTERS = frozenset({"open", "all", "new", "active", "reviewed", "approved", "resolved", "ignored"})


@router.get(
    "/project/{project_id}/rollup",
    response_model=ProjectCostImpactRollupResponse,
    dependencies=[Depends(RequirePermission("clash.read"))],
)
async def get_project_rollup(
    project_id: uuid.UUID,
    payload: CurrentUserPayload,
    session: SessionDep,
    status_filter: str = Query(
        default="open",
        alias="status",
        description="Clash status filter. ``open`` (default) — clashes "
        "still needing attention (new/active/reviewed). ``all`` — every "
        "clash regardless of status. Otherwise a literal status string "
        "from the clash module's vocabulary "
        "(``new``/``active``/``reviewed``/``resolved``/``ignored``).",
    ),
    service: ClashCostImpactService = Depends(_get_service),
) -> ProjectCostImpactRollupResponse:
    """Project-level open-impact rollup over the (filtered) clashes."""
    _require_boq_read(payload)
    if status_filter not in _ALLOWED_STATUS_FILTERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(f"Invalid status filter {status_filter!r}; allowed: {sorted(_ALLOWED_STATUS_FILTERS)}"),
        )
    user_id = payload.get("sub", "")
    await verify_project_access(project_id, user_id, session)

    rollup = await service.rollup_for_project(project_id, status_filter=status_filter)
    if rollup is None:
        # Should never fire — verify_project_access 404s already — but
        # keep the safety net so a transient race doesn't crash the call.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found",
        )
    return ProjectCostImpactRollupResponse.model_validate(rollup)
