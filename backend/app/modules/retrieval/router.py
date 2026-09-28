# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Retrieval API routes (mounted at ``/api/v1/retrieval`` by the loader).

* ``GET /search`` - faceted, ranked search across the project record
  (documents, correspondence, change orders), with provenance on each hit.
* ``GET/POST/PATCH/DELETE /saved-searches`` - the searches the caller pinned to
  re-run later, and ``POST /saved-searches/{id}/use`` to record a replay.

Everything is project-scoped: the caller must have access to the project. Saved
searches are additionally private to their owner - a pin belonging to somebody
else answers 404 rather than 403, so the API cannot be used to discover ids.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, status

from app.dependencies import CurrentUserId, SessionDep, verify_project_access
from app.modules.retrieval.facet_query import FacetQuery
from app.modules.retrieval.models import SavedSearch
from app.modules.retrieval.saved_search_logic import FACET_FIELDS
from app.modules.retrieval.schemas import (
    RetrievalResponse,
    RetrievalResultOut,
    SavedSearchCreate,
    SavedSearchFacets,
    SavedSearchListResponse,
    SavedSearchOut,
    SavedSearchUpdate,
)
from app.modules.retrieval.service import RetrievalService, SavedSearchInvalid, SavedSearchService

router = APIRouter(tags=["retrieval"])

#: Body text shown on a result card is truncated to keep payloads lean.
_SNIPPET_LEN = 280


def _one(value: str) -> frozenset[str]:
    """A single-value facet set, or empty when the value is blank."""
    return frozenset([value.strip()]) if value and value.strip() else frozenset()


@router.get("/search", response_model=RetrievalResponse)
async def search_records(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(..., description="Project to search within"),
    text: str = Query("", description="Free-text terms"),
    party: str = Query("", description="Filter to a party"),
    date_from: str = Query("", description="ISO date lower bound (inclusive)"),
    date_to: str = Query("", description="ISO date upper bound (inclusive)"),
    entity: str = Query("", description="Filter to records referencing this entity"),
    record_type: str = Query("", description="Filter to one record type"),
    as_of: str = Query("", description="Reference date for recency weighting"),
) -> RetrievalResponse:
    """Rank the project's records against the supplied facets, newest-best-first."""
    await verify_project_access(project_id, user_id, session)
    query = FacetQuery(
        text=text,
        parties=_one(party),
        date_from=date_from,
        date_to=date_to,
        entity_refs=_one(entity),
        record_types=_one(record_type),
    )
    ranked = await RetrievalService(session).search(project_id, query, as_of=as_of)
    results = [
        RetrievalResultOut(
            record_type=r.record.record_type,
            record_id=r.record.record_id,
            title=r.record.title,
            snippet=r.record.body[:_SNIPPET_LEN],
            source_module=r.record.source_module,
            party=r.record.party,
            occurred_at=r.record.occurred_at,
            entity_refs=list(r.record.entity_refs),
            score=round(r.score, 4),
            matched_facets=list(r.matched_facets),
            provenance=r.provenance,
        )
        for r in ranked
    ]
    return RetrievalResponse(count=len(results), results=results)


# ── Saved searches ───────────────────────────────────────────────────────────


def _to_out(saved: SavedSearch) -> SavedSearchOut:
    """Shape one row for the API, folding the facet columns back into a query."""
    return SavedSearchOut(
        id=saved.id,
        project_id=saved.project_id,
        label=saved.label,
        query=SavedSearchFacets(**{field: getattr(saved, field) or "" for field in FACET_FIELDS}),
        signature=saved.signature,
        use_count=saved.use_count,
        last_used_at=saved.last_used_at,
        created_at=saved.created_at,
        updated_at=saved.updated_at,
        validation_status=saved.validation_status,
        validation_findings=saved.validation_findings or [],
    )


def _invalid(exc: SavedSearchInvalid) -> HTTPException:
    """Turn a blocking validation failure into a 422 naming every reason."""
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={"message": "The saved search did not pass validation", "findings": exc.findings},
    )


async def _owned_or_404(
    saved_id: uuid.UUID,
    user_id: str,
    session: SessionDep,
) -> SavedSearch:
    """Fetch a pin the caller owns, or raise 404."""
    saved = await SavedSearchService(session).repo.get_owned(saved_id, uuid.UUID(str(user_id)))
    if saved is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Saved search not found",
        )
    return saved


@router.get("/saved-searches", response_model=SavedSearchListResponse)
async def list_saved_searches(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(..., description="Project the searches belong to"),
) -> SavedSearchListResponse:
    """List the caller's pinned searches on a project, most useful first."""
    await verify_project_access(project_id, user_id, session)
    rows = await SavedSearchService(session).list_saved(uuid.UUID(str(user_id)), project_id)
    return SavedSearchListResponse(count=len(rows), results=[_to_out(row) for row in rows])


@router.post(
    "/saved-searches",
    response_model=SavedSearchOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_saved_search(
    payload: SavedSearchCreate,
    user_id: CurrentUserId,
    session: SessionDep,
) -> SavedSearchOut:
    """Pin a search, or update the pin that already holds the same facets."""
    await verify_project_access(payload.project_id, user_id, session)
    service = SavedSearchService(session)
    try:
        saved = await service.save(
            uuid.UUID(str(user_id)),
            payload.project_id,
            label=payload.label,
            raw_facets=payload.query.model_dump(),
        )
    except SavedSearchInvalid as exc:
        raise _invalid(exc) from exc
    await session.commit()
    return _to_out(saved)


@router.patch("/saved-searches/{saved_id}", response_model=SavedSearchOut)
async def update_saved_search(
    saved_id: uuid.UUID,
    payload: SavedSearchUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
) -> SavedSearchOut:
    """Rename a pin, or re-point it at different facets."""
    saved = await _owned_or_404(saved_id, user_id, session)
    try:
        updated = await SavedSearchService(session).update(
            saved,
            label=payload.label,
            raw_facets=payload.query.model_dump() if payload.query is not None else None,
        )
    except SavedSearchInvalid as exc:
        raise _invalid(exc) from exc
    await session.commit()
    return _to_out(updated)


@router.post("/saved-searches/{saved_id}/use", response_model=SavedSearchOut)
async def record_saved_search_use(
    saved_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> SavedSearchOut:
    """Record that the caller replayed a pin, so it climbs their list."""
    saved = await _owned_or_404(saved_id, user_id, session)
    used = await SavedSearchService(session).record_use(saved)
    await session.commit()
    return _to_out(used)


@router.delete("/saved-searches/{saved_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_saved_search(
    saved_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> None:
    """Unpin a search."""
    saved = await _owned_or_404(saved_id, user_id, session)
    await SavedSearchService(session).delete(saved)
    await session.commit()
