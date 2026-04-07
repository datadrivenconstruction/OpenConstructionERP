"""RFI API routes.

Endpoints:
    GET    /                    - List RFIs for a project
    POST   /                    - Create RFI
    GET    /{rfi_id}            - Get single RFI
    PATCH  /{rfi_id}            - Update RFI
    DELETE /{rfi_id}            - Delete RFI
    POST   /{rfi_id}/respond    - Record official response
    POST   /{rfi_id}/close      - Close RFI
"""

import logging
import uuid

from fastapi import APIRouter, Depends, Query

from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.rfi.schemas import (
    RFICreate,
    RFIRespondRequest,
    RFIResponse,
    RFIUpdate,
)
from app.modules.rfi.service import RFIService

router = APIRouter()
logger = logging.getLogger(__name__)


def _get_service(session: SessionDep) -> RFIService:
    return RFIService(session)


def _to_response(item: object) -> RFIResponse:
    return RFIResponse(
        id=item.id,  # type: ignore[attr-defined]
        project_id=item.project_id,  # type: ignore[attr-defined]
        rfi_number=item.rfi_number,  # type: ignore[attr-defined]
        subject=item.subject,  # type: ignore[attr-defined]
        question=item.question,  # type: ignore[attr-defined]
        raised_by=item.raised_by,  # type: ignore[attr-defined]
        assigned_to=str(item.assigned_to) if item.assigned_to else None,  # type: ignore[attr-defined]
        status=item.status,  # type: ignore[attr-defined]
        ball_in_court=str(item.ball_in_court) if item.ball_in_court else None,  # type: ignore[attr-defined]
        official_response=item.official_response,  # type: ignore[attr-defined]
        responded_by=str(item.responded_by) if item.responded_by else None,  # type: ignore[attr-defined]
        responded_at=item.responded_at,  # type: ignore[attr-defined]
        cost_impact=item.cost_impact,  # type: ignore[attr-defined]
        cost_impact_value=item.cost_impact_value,  # type: ignore[attr-defined]
        schedule_impact=item.schedule_impact,  # type: ignore[attr-defined]
        schedule_impact_days=item.schedule_impact_days,  # type: ignore[attr-defined]
        date_required=item.date_required,  # type: ignore[attr-defined]
        response_due_date=item.response_due_date,  # type: ignore[attr-defined]
        linked_drawing_ids=item.linked_drawing_ids or [],  # type: ignore[attr-defined]
        change_order_id=item.change_order_id,  # type: ignore[attr-defined]
        created_by=item.created_by,  # type: ignore[attr-defined]
        metadata=getattr(item, "metadata_", {}),
        created_at=item.created_at,  # type: ignore[attr-defined]
        updated_at=item.updated_at,  # type: ignore[attr-defined]
    )


@router.get("/", response_model=list[RFIResponse])
async def list_rfis(
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status"),
    service: RFIService = Depends(_get_service),
) -> list[RFIResponse]:
    rfis, _ = await service.list_rfis(
        project_id,
        offset=offset,
        limit=limit,
        status_filter=status_filter,
    )
    return [_to_response(r) for r in rfis]


@router.post("/", response_model=RFIResponse, status_code=201)
async def create_rfi(
    data: RFICreate,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("rfi.create")),
    service: RFIService = Depends(_get_service),
) -> RFIResponse:
    rfi = await service.create_rfi(data, user_id=user_id)
    return _to_response(rfi)


@router.get("/{rfi_id}", response_model=RFIResponse)
async def get_rfi(
    rfi_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: RFIService = Depends(_get_service),
) -> RFIResponse:
    rfi = await service.get_rfi(rfi_id)
    return _to_response(rfi)


@router.patch("/{rfi_id}", response_model=RFIResponse)
async def update_rfi(
    rfi_id: uuid.UUID,
    data: RFIUpdate,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("rfi.update")),
    service: RFIService = Depends(_get_service),
) -> RFIResponse:
    rfi = await service.update_rfi(rfi_id, data)
    return _to_response(rfi)


@router.delete("/{rfi_id}", status_code=204)
async def delete_rfi(
    rfi_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("rfi.delete")),
    service: RFIService = Depends(_get_service),
) -> None:
    await service.delete_rfi(rfi_id)


@router.post("/{rfi_id}/respond", response_model=RFIResponse)
async def respond_to_rfi(
    rfi_id: uuid.UUID,
    body: RFIRespondRequest,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("rfi.update")),
    service: RFIService = Depends(_get_service),
) -> RFIResponse:
    """Record an official response to an RFI."""
    rfi = await service.respond_to_rfi(rfi_id, body.official_response, responded_by=user_id)
    return _to_response(rfi)


@router.post("/{rfi_id}/close", response_model=RFIResponse)
async def close_rfi(
    rfi_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("rfi.update")),
    service: RFIService = Depends(_get_service),
) -> RFIResponse:
    """Close an RFI."""
    rfi = await service.close_rfi(rfi_id)
    return _to_response(rfi)
