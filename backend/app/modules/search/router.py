"""Unified semantic search HTTP router.

Routes:
    GET  /api/v1/search/         — cross-collection semantic search
    GET  /api/v1/search/status/  — vector store + per-collection health
    GET  /api/v1/search/types/   — list of supported collection short names
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.dependencies import CurrentUserId
from app.modules.search.schemas import (
    SearchStatusResponse,
    UnifiedSearchResponse,
)
from app.modules.search.service import (
    search_status_snapshot,
    unified_search_service,
)

router = APIRouter()


@router.get("/", response_model=UnifiedSearchResponse)
async def unified_search_endpoint(
    _user_id: CurrentUserId,
    q: str = Query(..., min_length=1, max_length=500, description="Free-text query"),
    types: list[str] | None = Query(
        default=None,
        description=(
            "Optional list of collection short names — accepts both 'boq' / "
            "'documents' / 'tasks' / 'risks' / 'bim' / 'validation' / 'chat' "
            "and the canonical 'oe_*' forms.  When omitted, fans out to "
            "every registered collection."
        ),
    ),
    project_id: str | None = Query(default=None),
    tenant_id: str | None = Query(default=None),
    limit_per_collection: int = Query(default=10, ge=1, le=50),
    final_limit: int = Query(default=25, ge=1, le=100),
) -> UnifiedSearchResponse:
    """Run a cross-collection semantic search.

    The query text is embedded once via the active multilingual model and
    the resulting vector is searched against every selected collection in
    parallel.  Results are then fused into a single global ranking using
    Reciprocal Rank Fusion (RRF) — score-agnostic, parameter-free, robust
    to per-collection score scale differences.

    Project-scoped queries pass ``project_id`` to drop hits from other
    projects at the vector layer (no Postgres roundtrip needed).
    """
    return await unified_search_service(
        query=q,
        types=types,
        project_id=project_id,
        tenant_id=tenant_id,
        limit_per_collection=limit_per_collection,
        final_limit=final_limit,
    )


@router.get("/status/", response_model=SearchStatusResponse)
async def search_status_endpoint(_user_id: CurrentUserId) -> SearchStatusResponse:
    """Return aggregated vector-store status + per-collection counts.

    Used by the admin panel and the global Cmd+K modal to show whether
    semantic search is ready and which collections currently have data.
    """
    return search_status_snapshot()


@router.get("/types/")
async def list_search_types(_user_id: CurrentUserId) -> dict[str, list[dict[str, str]]]:
    """List the collection short names accepted by ``GET /search/?types=...``.

    Returns a structured list with both the canonical name and a human
    label so the frontend can build a multi-select filter dropdown.
    """
    from app.core.vector_index import ALL_COLLECTIONS, COLLECTION_LABELS

    return {
        "types": [
            {
                "name": collection,
                "label": COLLECTION_LABELS.get(collection, collection),
                "short": collection.removeprefix("oe_"),
            }
            for collection in ALL_COLLECTIONS
        ]
    }
