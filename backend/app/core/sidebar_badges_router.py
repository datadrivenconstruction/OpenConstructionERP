# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Sidebar badge counts - single lightweight endpoint.

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
    """Return open-item counts for sidebar badges in one round trip.

    The four counts are scalar subqueries of a single SELECT, each served by a
    ``project_id`` index, so the endpoint costs one statement however many
    modules contribute. Returns zeros if the statement fails (module tables
    not created yet) instead of an error, since badges are decoration.
    """
    from app.modules.rfi.models import RFI
    from app.modules.safety.models import SafetyIncident, SafetyObservation
    from app.modules.tasks.models import Task

    def _count(model: type, *conditions: object) -> object:
        return select(func.count()).select_from(model).where(*conditions).scalar_subquery()

    stmt = select(
        _count(Task, Task.project_id == project_id, Task.status.notin_(["completed"])).label("tasks"),
        _count(RFI, RFI.project_id == project_id, RFI.status.in_(["draft", "open"])).label("rfi"),
        _count(
            SafetyIncident,
            SafetyIncident.project_id == project_id,
            SafetyIncident.status.in_(["reported", "investigating"]),
        ).label("incidents"),
        _count(
            SafetyObservation,
            SafetyObservation.project_id == project_id,
            SafetyObservation.status.in_(["open", "in_progress"]),
        ).label("observations"),
    )
    try:
        row = (await session.execute(stmt)).one()
    except Exception:
        logger.debug("Sidebar badge counts unavailable", exc_info=True)
        return SidebarBadgesResponse()

    return SidebarBadgesResponse(
        tasks_open=row.tasks or 0,
        rfi_open=row.rfi or 0,
        safety_open=(row.incidents or 0) + (row.observations or 0),
    )
