# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Cost Explorer API routes.

Mounted at ``/api/v1/cost-explorer``. One search-first workspace over the cost
and resource databases:

    POST /by-resources               - find priced works by the resources they use
    POST /find-work                  - free-text search over priced works
    POST /compare                    - the same rate code priced across regions
    POST /substitute                 - re-price one resource line, see the delta
    GET  /price-intelligence/{code}  - a resource's price spread, reach, top works
    GET  /status                     - reverse-index size (edges / items)
    POST /reindex                    - rebuild the reverse index (manager)

Reads need viewer access; the reindex is a manager-level maintenance action.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import RequirePermission, SessionDep
from app.modules.cost_explorer.repository import CostExplorerRepository
from app.modules.cost_explorer.schemas import (
    ByResourcesRequest,
    ByResourcesResponse,
    CompareRequest,
    CompareResponse,
    FindWorkRequest,
    FindWorkResponse,
    PriceIntelResponse,
    ReindexResponse,
    SubstituteRequest,
    SubstituteResponse,
)
from app.modules.cost_explorer.service import CostExplorerNotFound, CostExplorerService

router = APIRouter()

_READ = Depends(RequirePermission("cost_explorer.read"))
_REINDEX = Depends(RequirePermission("cost_explorer.reindex"))


def _service(session: AsyncSession) -> CostExplorerService:
    return CostExplorerService(CostExplorerRepository(session))


@router.post("/by-resources", response_model=ByResourcesResponse, dependencies=[_READ])
async def by_resources(payload: ByResourcesRequest, session: SessionDep) -> ByResourcesResponse:
    """Rank priced work items by how well they match a weighted resource set."""
    return await _service(session).find_by_resources(payload)


@router.post("/find-work", response_model=FindWorkResponse, dependencies=[_READ])
async def find_work(payload: FindWorkRequest, session: SessionDep) -> FindWorkResponse:
    """Search priced work items by free text over code and description."""
    return await _service(session).find_work(payload)


@router.post("/compare", response_model=CompareResponse, dependencies=[_READ])
async def compare(payload: CompareRequest, session: SessionDep) -> CompareResponse:
    """List the same rate code priced across every installed region."""
    try:
        return await _service(session).compare(payload)
    except CostExplorerNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/substitute", response_model=SubstituteResponse, dependencies=[_READ])
async def substitute(payload: SubstituteRequest, session: SessionDep) -> SubstituteResponse:
    """Re-price one resource line of a work item and report the rate delta."""
    try:
        return await _service(session).substitute(payload)
    except CostExplorerNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/price-intelligence/{resource_code}", response_model=PriceIntelResponse, dependencies=[_READ])
async def price_intelligence(
    resource_code: str,
    session: SessionDep,
    region: str | None = Query(default=None, description="Restrict to one region price book."),
) -> PriceIntelResponse:
    """Summarise a resource's price spread, reach and top consuming works."""
    return await _service(session).price_intelligence(resource_code, region)


@router.get("/status", dependencies=[_READ])
async def index_status(session: SessionDep) -> dict:
    """Reverse-index health: edges stored, items available, and any loaded
    regions that carry works but are missing from the index (rebuild prompt)."""
    return await _service(session).index_status()


@router.post("/reindex", response_model=ReindexResponse, dependencies=[_REINDEX])
async def reindex(
    session: SessionDep,
    region: str | None = Query(default=None, description="Rebuild one region only; omit for all."),
) -> ReindexResponse:
    """Rebuild the resource -> work reverse index (manager action).

    Rebuilds a whole region (or every region), never a source-filtered subset,
    so a partial rebuild can never silently drop another source's edges. Taken
    under the shared build lock so it never races an automatic rebuild into
    duplicate edges; returns 409 when a rebuild is already running.
    """
    report = await _service(session).reindex_guarded(region=region)
    if report is None:
        raise HTTPException(status_code=409, detail="a reindex is already running; try again shortly")
    await session.commit()
    return report
