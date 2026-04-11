"""Unified search service — fan-out + RRF over every vector collection."""

from __future__ import annotations

import logging
from typing import Any

from app.core.vector_index import (
    ALL_COLLECTIONS,
    COLLECTION_LABELS,
    all_collection_status,
    reciprocal_rank_fusion,
    search_collection,
)
from app.modules.search.schemas import (
    CollectionStatusItem,
    SearchStatusResponse,
    UnifiedSearchHit,
    UnifiedSearchResponse,
)

logger = logging.getLogger(__name__)


# Map short names ("boq", "documents", …) → full collection names so the
# frontend can pass either form.  Single source of truth: the labels dict
# from vector_index plus a few common aliases.
_SHORT_NAME_ALIASES: dict[str, str] = {
    "boq": "oe_boq_positions",
    "boq_positions": "oe_boq_positions",
    "documents": "oe_documents",
    "docs": "oe_documents",
    "tasks": "oe_tasks",
    "risks": "oe_risks",
    "risk": "oe_risks",
    "bim": "oe_bim_elements",
    "bim_elements": "oe_bim_elements",
    "validation": "oe_validation",
    "chat": "oe_chat",
}


def _normalize_types(raw: list[str] | None) -> list[str]:
    """Resolve a list of user-supplied type names to canonical collections."""
    if not raw:
        return list(ALL_COLLECTIONS)
    out: list[str] = []
    for name in raw:
        cleaned = (name or "").strip().lower()
        if not cleaned:
            continue
        canonical = _SHORT_NAME_ALIASES.get(cleaned, cleaned)
        if canonical in ALL_COLLECTIONS and canonical not in out:
            out.append(canonical)
    if not out:
        return list(ALL_COLLECTIONS)
    return out


async def unified_search_service(
    query: str,
    *,
    types: list[str] | None = None,
    project_id: str | None = None,
    tenant_id: str | None = None,
    limit_per_collection: int = 10,
    final_limit: int = 25,
) -> UnifiedSearchResponse:
    """Search every selected collection in parallel and merge via RRF.

    The merge uses Reciprocal Rank Fusion (Cormack et al., 2009) which is
    parameter-free, robust to score scale differences across collections,
    and known to produce a globally coherent ordering even when each
    individual retriever has its own quality.

    Returns the unified envelope with hits + per-collection facet counts.
    """
    import asyncio

    chosen = _normalize_types(types)
    coros = [
        search_collection(
            collection,
            query,
            project_id=project_id,
            tenant_id=tenant_id,
            limit=limit_per_collection,
        )
        for collection in chosen
    ]
    rankings = await asyncio.gather(*coros, return_exceptions=False)

    facets: dict[str, int] = {}
    for collection, ranking in zip(chosen, rankings, strict=False):
        facets[collection] = len(ranking)

    fused = reciprocal_rank_fusion(rankings)
    fused = fused[:final_limit]

    hits = [
        UnifiedSearchHit(
            id=h.id,
            score=h.score,
            title=h.title,
            snippet=h.snippet,
            text=h.text,
            module=h.module or COLLECTION_LABELS.get(h.collection, h.collection),
            project_id=h.project_id,
            tenant_id=h.tenant_id,
            payload=h.payload,
            collection=h.collection,
        )
        for h in fused
    ]
    return UnifiedSearchResponse(
        query=query,
        types=chosen,
        project_id=project_id,
        total=len(hits),
        hits=hits,
        facets=facets,
    )


def search_status_snapshot() -> SearchStatusResponse:
    """Aggregate status from every collection — used by the search status
    endpoint and the global health page."""
    raw: dict[str, Any] = all_collection_status()
    multi = raw.get("multi_collection") or {}
    collections = [
        CollectionStatusItem(
            collection=meta.get("collection", name),
            label=meta.get("label", name),
            vectors_count=int(meta.get("vectors_count", 0) or 0),
            ready=bool(meta.get("ready", False)),
        )
        for name, meta in multi.items()
    ]
    return SearchStatusResponse(
        backend=str(raw.get("backend", "")),
        engine=str(raw.get("engine", "")),
        model_name=str(raw.get("model_name", "")),
        embedding_dim=int(raw.get("embedding_dim", 0) or 0),
        connected=bool(raw.get("connected", False)),
        collections=collections,
        cost_collection=raw.get("cost_collection"),
    )
