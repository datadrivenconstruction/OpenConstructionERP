"""BOQ API routes.

Endpoints:
    POST   /boqs/                    — Create a new BOQ
    GET    /boqs/?project_id=xxx     — List BOQs for a project
    GET    /boqs/{boq_id}            — Get BOQ with all positions
    PATCH  /boqs/{boq_id}            — Update BOQ metadata
    DELETE /boqs/{boq_id}            — Delete BOQ and all positions
    POST   /boqs/{boq_id}/positions  — Add a position to a BOQ
    PATCH  /positions/{position_id}  — Update a position
    DELETE /positions/{position_id}  — Delete a position
"""

import uuid

from fastapi import APIRouter, Depends, Query

from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.boq.schemas import (
    BOQCreate,
    BOQResponse,
    BOQUpdate,
    BOQWithPositions,
    PositionCreate,
    PositionResponse,
    PositionUpdate,
)
from app.modules.boq.service import BOQService

router = APIRouter()


def _get_service(session: SessionDep) -> BOQService:
    return BOQService(session)


# ── BOQ CRUD ──────────────────────────────────────────────────────────────────


@router.post(
    "/boqs/",
    response_model=BOQResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("boq.create"))],
)
async def create_boq(
    data: BOQCreate,
    _user_id: CurrentUserId,
    service: BOQService = Depends(_get_service),
) -> BOQResponse:
    """Create a new Bill of Quantities."""
    boq = await service.create_boq(data)
    return BOQResponse.model_validate(boq)


@router.get(
    "/boqs/",
    response_model=list[BOQResponse],
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def list_boqs(
    project_id: uuid.UUID = Query(..., description="Filter BOQs by project"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    service: BOQService = Depends(_get_service),
) -> list[BOQResponse]:
    """List all BOQs for a given project."""
    boqs, _ = await service.list_boqs_for_project(
        project_id, offset=offset, limit=limit
    )
    return [BOQResponse.model_validate(b) for b in boqs]


@router.get(
    "/boqs/{boq_id}",
    response_model=BOQWithPositions,
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def get_boq(
    boq_id: uuid.UUID,
    service: BOQService = Depends(_get_service),
) -> BOQWithPositions:
    """Get a BOQ with all its positions and grand total."""
    return await service.get_boq_with_positions(boq_id)


@router.patch(
    "/boqs/{boq_id}",
    response_model=BOQResponse,
    dependencies=[Depends(RequirePermission("boq.update"))],
)
async def update_boq(
    boq_id: uuid.UUID,
    data: BOQUpdate,
    service: BOQService = Depends(_get_service),
) -> BOQResponse:
    """Update BOQ metadata (name, description, status)."""
    boq = await service.update_boq(boq_id, data)
    return BOQResponse.model_validate(boq)


@router.delete(
    "/boqs/{boq_id}",
    status_code=204,
    dependencies=[Depends(RequirePermission("boq.delete"))],
)
async def delete_boq(
    boq_id: uuid.UUID,
    service: BOQService = Depends(_get_service),
) -> None:
    """Delete a BOQ and all its positions."""
    await service.delete_boq(boq_id)


# ── Position CRUD ─────────────────────────────────────────────────────────────


@router.post(
    "/boqs/{boq_id}/positions",
    response_model=PositionResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("boq.update"))],
)
async def add_position(
    boq_id: uuid.UUID,
    data: PositionCreate,
    service: BOQService = Depends(_get_service),
) -> PositionResponse:
    """Add a new position to a BOQ.

    The boq_id in the URL takes precedence over the body field.
    """
    # Override body boq_id with URL path parameter
    data.boq_id = boq_id
    position = await service.add_position(data)

    return PositionResponse(
        id=position.id,
        boq_id=position.boq_id,
        parent_id=position.parent_id,
        ordinal=position.ordinal,
        description=position.description,
        unit=position.unit,
        quantity=float(position.quantity),
        unit_rate=float(position.unit_rate),
        total=float(position.total),
        classification=position.classification,
        source=position.source,
        confidence=float(position.confidence) if position.confidence else None,
        cad_element_ids=position.cad_element_ids,
        validation_status=position.validation_status,
        metadata_=position.metadata_,
        sort_order=position.sort_order,
        created_at=position.created_at,
        updated_at=position.updated_at,
    )


@router.patch(
    "/positions/{position_id}",
    response_model=PositionResponse,
    dependencies=[Depends(RequirePermission("boq.update"))],
)
async def update_position(
    position_id: uuid.UUID,
    data: PositionUpdate,
    service: BOQService = Depends(_get_service),
) -> PositionResponse:
    """Update a BOQ position. Recalculates total if quantity or unit_rate changed."""
    position = await service.update_position(position_id, data)

    return PositionResponse(
        id=position.id,
        boq_id=position.boq_id,
        parent_id=position.parent_id,
        ordinal=position.ordinal,
        description=position.description,
        unit=position.unit,
        quantity=float(position.quantity),
        unit_rate=float(position.unit_rate),
        total=float(position.total),
        classification=position.classification,
        source=position.source,
        confidence=float(position.confidence) if position.confidence else None,
        cad_element_ids=position.cad_element_ids,
        validation_status=position.validation_status,
        metadata_=position.metadata_,
        sort_order=position.sort_order,
        created_at=position.created_at,
        updated_at=position.updated_at,
    )


@router.delete(
    "/positions/{position_id}",
    status_code=204,
    dependencies=[Depends(RequirePermission("boq.delete"))],
)
async def delete_position(
    position_id: uuid.UUID,
    service: BOQService = Depends(_get_service),
) -> None:
    """Delete a single position."""
    await service.delete_position(position_id)
