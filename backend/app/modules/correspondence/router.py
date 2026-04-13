"""Correspondence API routes.

Endpoints:
    GET    /                             - List correspondence for a project
    POST   /                             - Create correspondence
    GET    /{correspondence_id}          - Get single correspondence
    PATCH  /{correspondence_id}          - Update correspondence
    DELETE /{correspondence_id}          - Delete correspondence
"""

import logging
import uuid

from fastapi import APIRouter, Depends, Query

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.correspondence.schemas import (
    CorrespondenceCreate,
    CorrespondenceResponse,
    CorrespondenceUpdate,
)
from app.modules.correspondence.service import CorrespondenceService

router = APIRouter()
logger = logging.getLogger(__name__)


def _get_service(session: SessionDep) -> CorrespondenceService:
    return CorrespondenceService(session)


def _to_response(item: object) -> CorrespondenceResponse:
    return CorrespondenceResponse(
        id=item.id,  # type: ignore[attr-defined]
        project_id=item.project_id,  # type: ignore[attr-defined]
        reference_number=item.reference_number,  # type: ignore[attr-defined]
        direction=item.direction,  # type: ignore[attr-defined]
        subject=item.subject,  # type: ignore[attr-defined]
        from_contact_id=item.from_contact_id,  # type: ignore[attr-defined]
        to_contact_ids=item.to_contact_ids or [],  # type: ignore[attr-defined]
        date_sent=item.date_sent,  # type: ignore[attr-defined]
        date_received=item.date_received,  # type: ignore[attr-defined]
        correspondence_type=item.correspondence_type,  # type: ignore[attr-defined]
        linked_document_ids=item.linked_document_ids or [],  # type: ignore[attr-defined]
        linked_transmittal_id=item.linked_transmittal_id,  # type: ignore[attr-defined]
        linked_rfi_id=item.linked_rfi_id,  # type: ignore[attr-defined]
        notes=item.notes,  # type: ignore[attr-defined]
        created_by=item.created_by,  # type: ignore[attr-defined]
        metadata=getattr(item, "metadata_", {}),
        created_at=item.created_at,  # type: ignore[attr-defined]
        updated_at=item.updated_at,  # type: ignore[attr-defined]
    )


@router.get("/", response_model=list[CorrespondenceResponse])
async def list_correspondences(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    direction: str | None = Query(default=None),
    type_filter: str | None = Query(default=None, alias="type"),
    service: CorrespondenceService = Depends(_get_service),
) -> list[CorrespondenceResponse]:
    await verify_project_access(project_id, user_id, session)
    items, _ = await service.list_correspondences(
        project_id,
        offset=offset,
        limit=limit,
        direction=direction,
        correspondence_type=type_filter,
    )
    return [_to_response(c) for c in items]


@router.post("/", response_model=CorrespondenceResponse, status_code=201)
async def create_correspondence(
    data: CorrespondenceCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("correspondence.create")),
    service: CorrespondenceService = Depends(_get_service),
) -> CorrespondenceResponse:
    await verify_project_access(data.project_id, user_id, session)
    correspondence = await service.create_correspondence(data, user_id=user_id)
    return _to_response(correspondence)


@router.get("/{correspondence_id}", response_model=CorrespondenceResponse)
async def get_correspondence(
    correspondence_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: CorrespondenceService = Depends(_get_service),
) -> CorrespondenceResponse:
    correspondence = await service.get_correspondence(correspondence_id)
    return _to_response(correspondence)


@router.patch("/{correspondence_id}", response_model=CorrespondenceResponse)
async def update_correspondence(
    correspondence_id: uuid.UUID,
    data: CorrespondenceUpdate,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("correspondence.update")),
    service: CorrespondenceService = Depends(_get_service),
) -> CorrespondenceResponse:
    correspondence = await service.update_correspondence(correspondence_id, data)
    return _to_response(correspondence)


@router.delete("/{correspondence_id}", status_code=204)
async def delete_correspondence(
    correspondence_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("correspondence.delete")),
    service: CorrespondenceService = Depends(_get_service),
) -> None:
    await service.delete_correspondence(correspondence_id)
