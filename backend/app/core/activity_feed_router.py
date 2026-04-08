"""Activity feed API router.

Endpoint:
    GET /api/v1/activity?project_id=...&limit=20&offset=0
"""

import logging
from typing import Any

from fastapi import APIRouter, Query

from app.core.activity_feed import get_activity_feed
from app.dependencies import CurrentUserId, SessionDep

router = APIRouter(prefix="/api/v1/activity", tags=["Activity"])
logger = logging.getLogger(__name__)


@router.get("", response_model=list[dict[str, Any]])
async def activity_feed(
    session: SessionDep,
    _user_id: CurrentUserId,
    project_id: str | None = Query(default=None, description="Filter to a specific project"),
    limit: int = Query(default=20, ge=1, le=100, description="Maximum entries to return"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
) -> list[dict[str, Any]]:
    """Get a chronological feed of recent actions across all modules.

    Aggregates from the audit log with user name resolution.
    Each entry includes: type, entity_type, entity_id, title, action,
    user_id, user_name, timestamp, url, icon, details.
    """
    return await get_activity_feed(
        session,
        project_id=project_id,
        limit=limit,
        offset=offset,
    )
