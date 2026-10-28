# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Plan Room API routes.

Route prefix (mounted by the module loader): ``/api/v1/plan-room``.

Endpoints:
    GET    /{document_id}/pages/{page}/overlays  - read-only overlay composite
    POST   /{document_id}/pages/{page}/pins       - drop a positioned pin
    DELETE /pins/{pin_id}                          - remove a positioned pin

Reads require ``plan_room.read`` (VIEWER); the two pin mutations require
``plan_room.write`` (EDITOR). Every handler resolves the target document (or,
for delete, the pin's own ``project_id``) and calls ``verify_project_access``
before returning or changing anything, so a caller only ever sees or edits
overlays on a project they can access. Mutating handlers commit before
returning so the write is durable.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.plan_room.schemas import (
    OverlaysResponse,
    PlanPinCreate,
    PlanPinResponse,
)
from app.modules.plan_room.service import PlanRoomService

router = APIRouter(tags=["plan-room"])

_READ = Depends(RequirePermission("plan_room.read"))
_WRITE = Depends(RequirePermission("plan_room.write"))


def _get_service(session: SessionDep) -> PlanRoomService:
    return PlanRoomService(session)


@router.get(
    "/{document_id}/pages/{page}/overlays",
    response_model=OverlaysResponse,
    dependencies=[_READ],
)
async def get_overlays(
    document_id: str,
    page: int,
    user_id: CurrentUserId,
    session: SessionDep,
    service: PlanRoomService = Depends(_get_service),
) -> OverlaysResponse:
    """Composite the defect pins, markups, measurements and photos on a page."""
    document = await service.resolve_document(document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    await verify_project_access(document.project_id, user_id, session)
    return await service.get_overlays(document, page)


@router.post(
    "/{document_id}/pages/{page}/pins",
    response_model=PlanPinResponse,
    status_code=201,
    dependencies=[_WRITE],
)
async def create_pin(
    document_id: str,
    page: int,
    data: PlanPinCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: PlanRoomService = Depends(_get_service),
) -> PlanPinResponse:
    """Drop a positioned photo / note pin on a document page."""
    document = await service.resolve_document(document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    await verify_project_access(document.project_id, user_id, session)
    if data.page != page:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Body page does not match the URL page",
        )
    pin = await service.create_pin(
        project_id=document.project_id,
        document_id=str(document.id),
        page=page,
        data=data,
        user_id=user_id,
    )
    await session.commit()
    return PlanPinResponse.model_validate(pin)


@router.delete("/pins/{pin_id}", status_code=204, dependencies=[_WRITE])
async def delete_pin(
    pin_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: PlanRoomService = Depends(_get_service),
) -> None:
    """Remove a positioned pin (project access via the pin's own project)."""
    pin = await service.get_pin(pin_id)
    await verify_project_access(pin.project_id, user_id, session)
    await service.delete_pin(pin_id)
    await session.commit()
