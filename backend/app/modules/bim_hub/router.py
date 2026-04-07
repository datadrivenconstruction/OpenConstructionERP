"""BIM Hub API routes.

Endpoints:
    Models:
        GET    /                                — List models for a project
        POST   /                                — Create model
        GET    /{model_id}                      — Get single model
        PATCH  /{model_id}                      — Update model
        DELETE /{model_id}                      — Delete model

    Elements:
        GET    /models/{model_id}/elements      — List elements (paginated, filterable)
        POST   /models/{model_id}/elements      — Bulk import elements
        GET    /elements/{element_id}            — Get single element

    BOQ Links:
        GET    /links                            — List links for a BOQ position
        POST   /links                            — Create link
        DELETE /links/{link_id}                  — Delete link

    Quantity Maps:
        GET    /quantity-maps                    — List quantity map rules
        POST   /quantity-maps                    — Create quantity map rule
        PATCH  /quantity-maps/{map_id}           — Update quantity map rule
        POST   /quantity-maps/apply              — Apply rules on model

    Diffs:
        POST   /models/{model_id}/diff/{old_id}  — Compute diff
        GET    /diffs/{diff_id}                   — Get diff
"""

import uuid

from fastapi import APIRouter, Depends, Query

from app.dependencies import CurrentUserId, SessionDep
from app.modules.bim_hub.schemas import (
    BIMElementBulkImport,
    BIMElementListResponse,
    BIMElementResponse,
    BIMModelCreate,
    BIMModelDiffResponse,
    BIMModelListResponse,
    BIMModelResponse,
    BIMModelUpdate,
    BIMQuantityMapCreate,
    BIMQuantityMapListResponse,
    BIMQuantityMapResponse,
    BIMQuantityMapUpdate,
    BOQElementLinkCreate,
    BOQElementLinkListResponse,
    BOQElementLinkResponse,
    QuantityMapApplyRequest,
    QuantityMapApplyResult,
)
from app.modules.bim_hub.service import BIMHubService

router = APIRouter()


def _get_service(session: SessionDep) -> BIMHubService:
    return BIMHubService(session)


# ═══════════════════════════════════════════════════════════════════════════════
# Models
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/", response_model=BIMModelListResponse)
async def list_models(
    project_id: uuid.UUID = Query(...),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: BIMHubService = Depends(_get_service),
) -> BIMModelListResponse:
    """List BIM models for a project."""
    items, total = await service.list_models(project_id, offset=offset, limit=limit)
    return BIMModelListResponse(
        items=[BIMModelResponse.model_validate(m) for m in items],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post("/", response_model=BIMModelResponse, status_code=201)
async def create_model(
    data: BIMModelCreate,
    user_id: CurrentUserId,
    service: BIMHubService = Depends(_get_service),
) -> BIMModelResponse:
    """Create a new BIM model record."""
    model = await service.create_model(data, user_id=user_id)
    return BIMModelResponse.model_validate(model)


@router.get("/{model_id}", response_model=BIMModelResponse)
async def get_model(
    model_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: BIMHubService = Depends(_get_service),
) -> BIMModelResponse:
    """Get a single BIM model by ID."""
    model = await service.get_model(model_id)
    return BIMModelResponse.model_validate(model)


@router.patch("/{model_id}", response_model=BIMModelResponse)
async def update_model(
    model_id: uuid.UUID,
    data: BIMModelUpdate,
    user_id: CurrentUserId,
    service: BIMHubService = Depends(_get_service),
) -> BIMModelResponse:
    """Update a BIM model."""
    model = await service.update_model(model_id, data)
    return BIMModelResponse.model_validate(model)


@router.delete("/{model_id}", status_code=204)
async def delete_model(
    model_id: uuid.UUID,
    user_id: CurrentUserId,
    service: BIMHubService = Depends(_get_service),
) -> None:
    """Delete a BIM model and all its elements."""
    await service.delete_model(model_id)


# ═══════════════════════════════════════════════════════════════════════════════
# Elements
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/models/{model_id}/elements", response_model=BIMElementListResponse)
async def list_elements(
    model_id: uuid.UUID,
    element_type: str | None = Query(default=None),
    storey: str | None = Query(default=None),
    discipline: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=5000),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: BIMHubService = Depends(_get_service),
) -> BIMElementListResponse:
    """List elements for a BIM model (paginated, filterable)."""
    items, total = await service.list_elements(
        model_id,
        element_type=element_type,
        storey=storey,
        discipline=discipline,
        offset=offset,
        limit=limit,
    )
    return BIMElementListResponse(
        items=[BIMElementResponse.model_validate(e) for e in items],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post(
    "/models/{model_id}/elements",
    response_model=BIMElementListResponse,
    status_code=201,
)
async def bulk_import_elements(
    model_id: uuid.UUID,
    data: BIMElementBulkImport,
    user_id: CurrentUserId,
    service: BIMHubService = Depends(_get_service),
) -> BIMElementListResponse:
    """Bulk import elements for a model (replaces existing)."""
    elements = await service.bulk_import_elements(model_id, data.elements)
    return BIMElementListResponse(
        items=[BIMElementResponse.model_validate(e) for e in elements],
        total=len(elements),
        offset=0,
        limit=len(elements),
    )


@router.get("/elements/{element_id}", response_model=BIMElementResponse)
async def get_element(
    element_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: BIMHubService = Depends(_get_service),
) -> BIMElementResponse:
    """Get a single BIM element by ID."""
    element = await service.get_element(element_id)
    return BIMElementResponse.model_validate(element)


# ═══════════════════════════════════════════════════════════════════════════════
# BOQ Links
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/links", response_model=BOQElementLinkListResponse)
async def list_links(
    boq_position_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: BIMHubService = Depends(_get_service),
) -> BOQElementLinkListResponse:
    """List BIM element links for a BOQ position."""
    items = await service.list_links_for_position(boq_position_id)
    return BOQElementLinkListResponse(
        items=[BOQElementLinkResponse.model_validate(lnk) for lnk in items],
        total=len(items),
    )


@router.post("/links", response_model=BOQElementLinkResponse, status_code=201)
async def create_link(
    data: BOQElementLinkCreate,
    user_id: CurrentUserId,
    service: BIMHubService = Depends(_get_service),
) -> BOQElementLinkResponse:
    """Create a link between a BOQ position and a BIM element."""
    link = await service.create_link(data, user_id=user_id)
    return BOQElementLinkResponse.model_validate(link)


@router.delete("/links/{link_id}", status_code=204)
async def delete_link(
    link_id: uuid.UUID,
    user_id: CurrentUserId,
    service: BIMHubService = Depends(_get_service),
) -> None:
    """Delete a BOQ-BIM link."""
    await service.delete_link(link_id)


# ═══════════════════════════════════════════════════════════════════════════════
# Quantity Maps
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/quantity-maps", response_model=BIMQuantityMapListResponse)
async def list_quantity_maps(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: BIMHubService = Depends(_get_service),
) -> BIMQuantityMapListResponse:
    """List quantity mapping rules."""
    items, total = await service.list_quantity_maps(offset=offset, limit=limit)
    return BIMQuantityMapListResponse(
        items=[BIMQuantityMapResponse.model_validate(m) for m in items],
        total=total,
    )


@router.post("/quantity-maps", response_model=BIMQuantityMapResponse, status_code=201)
async def create_quantity_map(
    data: BIMQuantityMapCreate,
    user_id: CurrentUserId,
    service: BIMHubService = Depends(_get_service),
) -> BIMQuantityMapResponse:
    """Create a new quantity mapping rule."""
    qmap = await service.create_quantity_map(data)
    return BIMQuantityMapResponse.model_validate(qmap)


@router.patch("/quantity-maps/{map_id}", response_model=BIMQuantityMapResponse)
async def update_quantity_map(
    map_id: uuid.UUID,
    data: BIMQuantityMapUpdate,
    user_id: CurrentUserId,
    service: BIMHubService = Depends(_get_service),
) -> BIMQuantityMapResponse:
    """Update a quantity mapping rule."""
    qmap = await service.update_quantity_map(map_id, data)
    return BIMQuantityMapResponse.model_validate(qmap)


@router.post("/quantity-maps/apply", response_model=QuantityMapApplyResult)
async def apply_quantity_maps(
    data: QuantityMapApplyRequest,
    user_id: CurrentUserId,
    service: BIMHubService = Depends(_get_service),
) -> QuantityMapApplyResult:
    """Apply quantity mapping rules to all elements in a model."""
    return await service.apply_quantity_maps(data)


# ═══════════════════════════════════════════════════════════════════════════════
# Diffs
# ═══════════════════════════════════════════════════════════════════════════════


@router.post("/models/{model_id}/diff/{old_id}", response_model=BIMModelDiffResponse, status_code=201)
async def compute_diff(
    model_id: uuid.UUID,
    old_id: uuid.UUID,
    user_id: CurrentUserId,
    service: BIMHubService = Depends(_get_service),
) -> BIMModelDiffResponse:
    """Compute diff between two model versions."""
    diff = await service.compute_diff(new_model_id=model_id, old_model_id=old_id)
    return BIMModelDiffResponse.model_validate(diff)


@router.get("/diffs/{diff_id}", response_model=BIMModelDiffResponse)
async def get_diff(
    diff_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: BIMHubService = Depends(_get_service),
) -> BIMModelDiffResponse:
    """Get a model diff by ID."""
    diff = await service.get_diff(diff_id)
    return BIMModelDiffResponse.model_validate(diff)
