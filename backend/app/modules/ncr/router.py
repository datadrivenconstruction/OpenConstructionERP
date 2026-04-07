"""NCR API routes.

Endpoints:
    GET    /                - List NCRs for a project
    POST   /                - Create NCR
    GET    /{ncr_id}        - Get single NCR
    PATCH  /{ncr_id}        - Update NCR
    DELETE /{ncr_id}        - Delete NCR
    POST   /{ncr_id}/close  - Close NCR
"""

import logging
import uuid

from fastapi import APIRouter, Depends, Query

from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.ncr.schemas import (
    NCRCreate,
    NCRResponse,
    NCRUpdate,
)
from app.modules.ncr.service import NCRService

router = APIRouter()
logger = logging.getLogger(__name__)


def _get_service(session: SessionDep) -> NCRService:
    return NCRService(session)


def _to_response(item: object) -> NCRResponse:
    return NCRResponse(
        id=item.id,  # type: ignore[attr-defined]
        project_id=item.project_id,  # type: ignore[attr-defined]
        ncr_number=item.ncr_number,  # type: ignore[attr-defined]
        title=item.title,  # type: ignore[attr-defined]
        description=item.description,  # type: ignore[attr-defined]
        ncr_type=item.ncr_type,  # type: ignore[attr-defined]
        severity=item.severity,  # type: ignore[attr-defined]
        root_cause=item.root_cause,  # type: ignore[attr-defined]
        root_cause_category=item.root_cause_category,  # type: ignore[attr-defined]
        corrective_action=item.corrective_action,  # type: ignore[attr-defined]
        preventive_action=item.preventive_action,  # type: ignore[attr-defined]
        status=item.status,  # type: ignore[attr-defined]
        cost_impact=item.cost_impact,  # type: ignore[attr-defined]
        schedule_impact_days=item.schedule_impact_days,  # type: ignore[attr-defined]
        location_description=item.location_description,  # type: ignore[attr-defined]
        linked_inspection_id=item.linked_inspection_id,  # type: ignore[attr-defined]
        change_order_id=item.change_order_id,  # type: ignore[attr-defined]
        created_by=item.created_by,  # type: ignore[attr-defined]
        metadata=getattr(item, "metadata_", {}),
        created_at=item.created_at,  # type: ignore[attr-defined]
        updated_at=item.updated_at,  # type: ignore[attr-defined]
    )


@router.get("/", response_model=list[NCRResponse])
async def list_ncrs(
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    type_filter: str | None = Query(default=None, alias="type"),
    status_filter: str | None = Query(default=None, alias="status"),
    severity: str | None = Query(default=None),
    service: NCRService = Depends(_get_service),
) -> list[NCRResponse]:
    ncrs, _ = await service.list_ncrs(
        project_id,
        offset=offset,
        limit=limit,
        ncr_type=type_filter,
        status_filter=status_filter,
        severity=severity,
    )
    return [_to_response(n) for n in ncrs]


@router.post("/", response_model=NCRResponse, status_code=201)
async def create_ncr(
    data: NCRCreate,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("ncr.create")),
    service: NCRService = Depends(_get_service),
) -> NCRResponse:
    ncr = await service.create_ncr(data, user_id=user_id)
    return _to_response(ncr)


@router.get("/{ncr_id}", response_model=NCRResponse)
async def get_ncr(
    ncr_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: NCRService = Depends(_get_service),
) -> NCRResponse:
    ncr = await service.get_ncr(ncr_id)
    return _to_response(ncr)


@router.patch("/{ncr_id}", response_model=NCRResponse)
async def update_ncr(
    ncr_id: uuid.UUID,
    data: NCRUpdate,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("ncr.update")),
    service: NCRService = Depends(_get_service),
) -> NCRResponse:
    ncr = await service.update_ncr(ncr_id, data)
    return _to_response(ncr)


@router.delete("/{ncr_id}", status_code=204)
async def delete_ncr(
    ncr_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("ncr.delete")),
    service: NCRService = Depends(_get_service),
) -> None:
    await service.delete_ncr(ncr_id)


@router.post("/{ncr_id}/close", response_model=NCRResponse)
async def close_ncr(
    ncr_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("ncr.update")),
    service: NCRService = Depends(_get_service),
) -> NCRResponse:
    """Close an NCR after verification."""
    ncr = await service.close_ncr(ncr_id)
    return _to_response(ncr)
