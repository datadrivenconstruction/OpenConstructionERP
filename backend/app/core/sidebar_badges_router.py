"""Sidebar badge counts — single lightweight endpoint.

Returns open/active item counts for Tasks, RFIs, and Safety
in a single response so the sidebar can display notification badges
without N separate API calls.

Endpoint:
    GET /api/v1/sidebar/badges/?project_id=X
"""

import logging
import uuid

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.dependencies import CurrentUserId, SessionDep

router = APIRouter(prefix="/api/v1/sidebar", tags=["Sidebar"])
logger = logging.getLogger(__name__)


class SidebarBadgesResponse(BaseModel):
    """Aggregated open-item counts for sidebar navigation badges."""

    tasks_open: int = Field(default=0, description="Tasks not completed (open + in_progress + draft)")
    rfi_open: int = Field(default=0, description="RFIs in draft or open status")
    safety_open: int = Field(
        default=0,
        description="Open safety incidents + open observations",
    )


@router.get("/badges/", response_model=SidebarBadgesResponse)
async def sidebar_badges(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> SidebarBadgesResponse:
    """Return open-item counts for sidebar badges in a single query batch.

    Uses COUNT queries (no full row fetches) for minimal DB load.
    Gracefully returns 0 for any module whose table doesn't exist yet.
    """
    tasks_open = 0
    rfi_open = 0
    safety_open = 0

    # Tasks: count non-completed tasks
    try:
        from app.modules.tasks.models import Task

        result = await session.execute(
            select(func.count())
            .select_from(Task)
            .where(
                Task.project_id == project_id,
                Task.status.notin_(["completed"]),
            )
        )
        tasks_open = result.scalar() or 0
    except Exception:
        logger.debug("Tasks table not available for sidebar badges", exc_info=True)

    # RFIs: count draft + open
    try:
        from app.modules.rfi.models import RFI

        result = await session.execute(
            select(func.count())
            .select_from(RFI)
            .where(
                RFI.project_id == project_id,
                RFI.status.in_(["draft", "open"]),
            )
        )
        rfi_open = result.scalar() or 0
    except Exception:
        logger.debug("RFI table not available for sidebar badges", exc_info=True)

    # Safety: open incidents + open observations
    try:
        from app.modules.safety.models import SafetyIncident, SafetyObservation

        inc_result = await session.execute(
            select(func.count())
            .select_from(SafetyIncident)
            .where(
                SafetyIncident.project_id == project_id,
                SafetyIncident.status.in_(["reported", "investigating"]),
            )
        )
        obs_result = await session.execute(
            select(func.count())
            .select_from(SafetyObservation)
            .where(
                SafetyObservation.project_id == project_id,
                SafetyObservation.status.in_(["open", "in_progress"]),
            )
        )
        safety_open = (inc_result.scalar() or 0) + (obs_result.scalar() or 0)
    except Exception:
        logger.debug("Safety tables not available for sidebar badges", exc_info=True)

    return SidebarBadgesResponse(
        tasks_open=tasks_open,
        rfi_open=rfi_open,
        safety_open=safety_open,
    )
