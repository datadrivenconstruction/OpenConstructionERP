"""Cost database API routes.

Endpoints:
    POST /            — Create a cost item (auth required)
    GET  /            — Search cost items (public, query params)
    GET  /{item_id}   — Get cost item by ID
    PATCH /{item_id}  — Update cost item (auth required)
    DELETE /{item_id} — Delete cost item (auth required)
    POST /bulk        — Bulk import cost items (auth required)
"""

import uuid

from fastapi import APIRouter, Depends, Query

from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.costs.schemas import (
    CostItemCreate,
    CostItemResponse,
    CostItemUpdate,
    CostSearchQuery,
)
from app.modules.costs.service import CostItemService

router = APIRouter()


def _get_service(session: SessionDep) -> CostItemService:
    return CostItemService(session)


# ── Create ────────────────────────────────────────────────────────────────


@router.post(
    "/",
    response_model=CostItemResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("costs.create"))],
)
async def create_cost_item(
    data: CostItemCreate,
    _user_id: CurrentUserId,
    service: CostItemService = Depends(_get_service),
) -> CostItemResponse:
    """Create a new cost item."""
    item = await service.create_cost_item(data)
    return CostItemResponse.model_validate(item)


# ── Search / List ─────────────────────────────────────────────────────────


@router.get("/", response_model=list[CostItemResponse])
async def search_cost_items(
    service: CostItemService = Depends(_get_service),
    q: str | None = Query(default=None, description="Text search on code and description"),
    unit: str | None = Query(default=None, description="Filter by unit"),
    source: str | None = Query(default=None, description="Filter by source"),
    min_rate: float | None = Query(default=None, ge=0, description="Minimum rate"),
    max_rate: float | None = Query(default=None, ge=0, description="Maximum rate"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[CostItemResponse]:
    """Search cost items with optional filters. Public endpoint."""
    query = CostSearchQuery(
        q=q,
        unit=unit,
        source=source,
        min_rate=min_rate,
        max_rate=max_rate,
        limit=limit,
        offset=offset,
    )
    items, _ = await service.search_costs(query)
    return [CostItemResponse.model_validate(i) for i in items]


# ── Get by ID ─────────────────────────────────────────────────────────────


@router.get("/{item_id}", response_model=CostItemResponse)
async def get_cost_item(
    item_id: uuid.UUID,
    service: CostItemService = Depends(_get_service),
) -> CostItemResponse:
    """Get a cost item by ID."""
    item = await service.get_cost_item(item_id)
    return CostItemResponse.model_validate(item)


# ── Update ────────────────────────────────────────────────────────────────


@router.patch(
    "/{item_id}",
    response_model=CostItemResponse,
    dependencies=[Depends(RequirePermission("costs.update"))],
)
async def update_cost_item(
    item_id: uuid.UUID,
    data: CostItemUpdate,
    _user_id: CurrentUserId,
    service: CostItemService = Depends(_get_service),
) -> CostItemResponse:
    """Update a cost item."""
    item = await service.update_cost_item(item_id, data)
    return CostItemResponse.model_validate(item)


# ── Delete ────────────────────────────────────────────────────────────────


@router.delete(
    "/{item_id}",
    status_code=204,
    dependencies=[Depends(RequirePermission("costs.delete"))],
)
async def delete_cost_item(
    item_id: uuid.UUID,
    _user_id: CurrentUserId,
    service: CostItemService = Depends(_get_service),
) -> None:
    """Soft-delete a cost item."""
    await service.delete_cost_item(item_id)


# ── Bulk import ───────────────────────────────────────────────────────────


@router.post(
    "/bulk",
    response_model=list[CostItemResponse],
    status_code=201,
    dependencies=[Depends(RequirePermission("costs.create"))],
)
async def bulk_import_cost_items(
    data: list[CostItemCreate],
    _user_id: CurrentUserId,
    service: CostItemService = Depends(_get_service),
) -> list[CostItemResponse]:
    """Bulk import cost items. Skips duplicates by code."""
    items = await service.bulk_import(data)
    return [CostItemResponse.model_validate(i) for i in items]
