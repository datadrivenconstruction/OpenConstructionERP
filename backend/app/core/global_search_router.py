"""Global search API router.

Endpoint:
    GET /api/v1/global-search?q=...&project_id=...&limit=20

The prefix used to be /api/v1/search, but the module-loader auto-mounts
``app.modules.search`` at the same /api/v1/search prefix. Both routers
work today because their child paths don't overlap, but adding a route
in one that collides with the other would silently shadow. The prefixes
are now distinct so that class of bug can't slip past code review.
"""

import logging
from typing import Any

from fastapi import APIRouter, Query

from app.core.global_search import global_search
from app.dependencies import CurrentUserId, SessionDep

router = APIRouter(prefix="/api/v1/global-search", tags=["Search"])
logger = logging.getLogger(__name__)


@router.get("", response_model=list[dict[str, Any]])
async def search(
    session: SessionDep,
    _user_id: CurrentUserId,
    q: str = Query(default="", description="Search query string"),
    project_id: str | None = Query(default=None, description="Limit search to a specific project"),
    limit: int = Query(default=20, ge=1, le=100, description="Maximum results to return"),
) -> list[dict[str, Any]]:
    """Search across all modules — BOQ positions, contacts, documents, RFIs,
    tasks, cost items, meetings, inspections, and NCRs.

    Results are ranked by relevance score. Each result includes:
    module, type, id, title, subtitle, url, score.
    """
    if not q.strip():
        return []
    return await global_search(session, query=q, project_id=project_id, limit=limit)
