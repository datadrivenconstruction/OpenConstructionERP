# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Estimate-rollup API routes.

Mounted at ``/api/v1/estimate-rollup``. One read-only endpoint composes a
project's full estimate headline number:

    GET /projects/{project_id}  - the composed estimate rollup

Reading needs viewer access to the project. The route verifies project access
first (404 on both missing and forbidden, so a project id is never an existence
oracle), then returns the composition. It writes nothing.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.estimate_rollup.schemas import EstimateRollupResponse
from app.modules.estimate_rollup.service import compute_estimate_rollup

router = APIRouter()

_READ = Depends(RequirePermission("estimate_rollup.read"))


@router.get("/projects/{project_id}", response_model=EstimateRollupResponse, dependencies=[_READ])
async def get_estimate_rollup(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> EstimateRollupResponse:
    """Compose and return a project's estimate rollup (BOQ base + prelims + allowances)."""
    await verify_project_access(project_id, user_id, session)
    rollup = await compute_estimate_rollup(session, project_id)
    return EstimateRollupResponse.from_rollup(rollup, project_id=project_id)
