# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Deadlines API routes.

Endpoints:
    GET  /         - the cross-module deadline register for a project
    POST /sweep    - manually trigger one overdue sweep pass (ops / tests)

Auto-mounts at ``/api/v1/deadlines`` (kebab-case module-loader convention).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.deadlines import service
from app.modules.deadlines.schemas import DeadlineRegisterResponse, DeadlineSweepResponse
from app.modules.deadlines.sweeper import sweep_overdue

router = APIRouter(tags=["deadlines"])


@router.get("/", response_model=DeadlineRegisterResponse)
async def list_deadlines(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    status: str = Query("all", pattern=r"^(all|overdue|approaching)$"),
    module: str | None = Query(default=None),
    approaching_days: int = Query(default=3, ge=0, le=30),
    limit: int = Query(default=200, ge=1, le=500),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("deadlines.read")),
) -> DeadlineRegisterResponse:
    """The unified overdue + approaching register for one project."""
    await verify_project_access(project_id, user_id, session)
    return await service.compute_deadlines(
        session,
        [project_id],
        status=status,
        module=module,
        approaching_days=approaching_days,
        limit=limit,
    )


class DeadlineSweepRequest(BaseModel):
    """Optional sweep scope. ``project_id=null`` sweeps all projects."""

    project_id: uuid.UUID | None = None


@router.post("/sweep", response_model=DeadlineSweepResponse)
async def trigger_sweep(
    session: SessionDep,
    body: DeadlineSweepRequest | None = None,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("deadlines.sweep")),
) -> DeadlineSweepResponse:
    """Drain one overdue-sweep pass now (managers / ops), without the timer.

    The sweep is global across projects (the escalation notifications it
    writes are per-user, so nothing leaks cross-tenant). The session
    dependency commits on success.
    """
    actioned = await sweep_overdue(session)
    return DeadlineSweepResponse(actioned=actioned)
