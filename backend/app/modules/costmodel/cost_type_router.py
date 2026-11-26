# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cost-type grid endpoint, mounted on the cost model router.

GET /projects/{project_id}/5d/cost-type-grid/?cost_type=&cost_code=   budget, committed, actual,
    forecast, EAC and variance per cost code x cost type, with subtotals and the ``cost_types``
    findings (costmodel.read). A line's forecast is edited through PATCH /5d/budget-lines/{id}.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.costmodel.cost_type_grid import CostTypeGridResponse, build_cost_type_grid

router = APIRouter(tags=["costmodel"])


@router.get(
    "/projects/{project_id}/5d/cost-type-grid/",
    response_model=CostTypeGridResponse,
    dependencies=[Depends(RequirePermission("costmodel.read"))],
)
async def get_cost_type_grid(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    cost_type: str | None = Query(default=None, max_length=100, description="A budget category, or 'untyped'."),
    cost_code: str | None = Query(default=None, max_length=80, description="Cost code prefix."),
) -> CostTypeGridResponse:
    """Budget and forecast per cost code x cost type for one project."""
    from app.core.i18n import get_locale

    await verify_project_access(project_id, user_id, session)
    return await build_cost_type_grid(
        session, project_id, cost_type=cost_type, cost_code=cost_code, locale=get_locale()
    )
