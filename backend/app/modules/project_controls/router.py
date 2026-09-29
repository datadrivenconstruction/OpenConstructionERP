# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""FastAPI router for the Project Controls module.

Mounted by the module loader at ``/api/v1/project-controls/``.

Security model:

* Both endpoints are gated by ``project_controls.read`` (VIEWER).
* When a ``project_id`` is supplied the caller must own / be a member of that
  project (``verify_project_access`` - which 404s on miss/denied to avoid
  leaking the existence of projects the caller cannot see). Project-less
  (portfolio) calls are scoped to the caller's accessible projects via
  ``accessible_project_ids`` (admins get ``None`` = no filter) so a non-admin
  cannot aggregate across other tenants' projects.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, Query

from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    accessible_project_ids,
    verify_project_access,
)
from app.modules.bi_dashboards.kpis import _parse_date
from app.modules.project_controls.schemas import (
    ControlsDrillResponse,
    ControlsSnapshotResponse,
)
from app.modules.project_controls.service import ProjectControlsService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["project_controls"])


def _service(session: SessionDep) -> ProjectControlsService:
    return ProjectControlsService(session)


@router.get(
    "/snapshot",
    response_model=ControlsSnapshotResponse,
    dependencies=[Depends(RequirePermission("project_controls.read"))],
    summary="Cross-module controls snapshot",
)
async def controls_snapshot(
    user_id: CurrentUserId,
    session: SessionDep,
    service: ProjectControlsService = Depends(_service),
    project_id: uuid.UUID | None = Query(default=None),
    period_start: str | None = Query(default=None),
    period_end: str | None = Query(default=None),
) -> ControlsSnapshotResponse:
    """Assemble the cost + schedule + quality + safety + risk + change spine.

    Omit ``project_id`` for a portfolio-wide aggregation. Dates are ISO
    ``YYYY-MM-DD`` strings; unparseable values are treated as absent.
    """
    allowed: set[uuid.UUID] | None = None
    if project_id is not None:
        await verify_project_access(project_id, user_id, session)
    else:
        # Portfolio mode lists live projects only: a deleted (archived)
        # project is not part of the rollup, for admins either.
        allowed = await accessible_project_ids(session, user_id, live_only=True)
    result = await service.snapshot(
        project_id=project_id,
        period_start=_parse_date(period_start),
        period_end=_parse_date(period_end),
        allowed_project_ids=allowed,
    )
    return ControlsSnapshotResponse(**result)


@router.get(
    "/drill/{kpi_code}",
    response_model=ControlsDrillResponse,
    dependencies=[Depends(RequirePermission("project_controls.read"))],
    summary="Drill-down rows for a controls KPI",
)
async def controls_drill(
    kpi_code: str,
    user_id: CurrentUserId,
    session: SessionDep,
    service: ProjectControlsService = Depends(_service),
    project_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> ControlsDrillResponse:
    """Return the underlying source rows behind a KPI with cross-module deep links."""
    allowed: set[uuid.UUID] | None = None
    if project_id is not None:
        await verify_project_access(project_id, user_id, session)
    else:
        # Portfolio mode lists live projects only: a deleted (archived)
        # project is not part of the rollup, for admins either.
        allowed = await accessible_project_ids(session, user_id, live_only=True)
    result = await service.drill(kpi_code, project_id=project_id, limit=limit, allowed_project_ids=allowed)
    return ControlsDrillResponse(**result)
