# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Plan Room API routes.

Route prefix (mounted by the module loader): ``/api/v1/plan-room``.

Endpoints:
    GET    /{document_id}/pages/{page}/overlays  - read-only overlay composite
    POST   /{document_id}/pages/{page}/pins       - drop a positioned pin
    DELETE /pins/{pin_id}                          - remove a positioned pin
    GET    /pins/                                  - list pins of a project (envelope)
    POST   /pins/                                  - create a pin on a drawing page or a BIM element
    PATCH  /pins/{pin_id}                          - move, relink or review a pin
    GET    /pins/by-target/{kind}/{target_id}      - the pins of one record (envelope)
    POST   /pins/carry-forward/                    - carry a superseded sheet's pins to its replacement
    GET    /bim/{model_id}/pins                    - the pins on a BIM model's elements (envelope)

Reads require ``plan_room.read`` (VIEWER); the two pin mutations require
``plan_room.write`` (EDITOR). Every handler resolves the target document (or,
for delete, the pin's own ``project_id``) and calls ``verify_project_access``
before returning or changing anything, so a caller only ever sees or edits
overlays on a project they can access. Mutating handlers commit before
returning so the write is durable.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.plan_room.pin_service import PinService
from app.modules.plan_room.schemas import (
    PIN_REVISION_STATES,
    PIN_TARGET_KINDS,
    OverlaysResponse,
    PinCreate,
    PinListResponse,
    PinUpdate,
    PlanPinCreate,
    PlanPinResponse,
)
from app.modules.plan_room.service import PlanRoomService

router = APIRouter(tags=["plan-room"])

_READ = Depends(RequirePermission("plan_room.read"))
_WRITE = Depends(RequirePermission("plan_room.write"))


def _get_service(session: SessionDep) -> PlanRoomService:
    return PlanRoomService(session)


def _get_pin_service(session: SessionDep) -> PinService:
    return PinService(session)


async def _respond(pins: list, svc: PinService) -> list[PlanPinResponse]:
    """Pin responses carrying the label of the record each pin points at."""
    labels = await svc.labels(pins)
    out = []
    for pin in pins:
        resp = PlanPinResponse.model_validate(pin)
        info = labels.get(f"{pin.target_kind}:{pin.target_id}")
        resp.target_label = info.label if info else None
        out.append(resp)
    return out


async def _respond_one(pin, svc: PinService) -> PlanPinResponse:
    return (await _respond([pin], svc))[0]


@router.get("/pins/", response_model=PinListResponse, dependencies=[_READ])
async def list_pins(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    document_id: str | None = Query(default=None, max_length=255),
    sheet_id: str | None = Query(default=None, max_length=36),
    page: int | None = Query(default=None, ge=1),
    target_kind: str | None = Query(default=None, pattern=f"^({'|'.join(PIN_TARGET_KINDS)})$"),
    status_filter: str | None = Query(default=None, alias="status", max_length=40),
    revision_state: str | None = Query(default=None, pattern=f"^({'|'.join(PIN_REVISION_STATES)})$"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=1000),
    svc: PinService = Depends(_get_pin_service),
) -> PinListResponse:
    """The pins of a project, filterable by sheet, page, record kind, status and revision state."""
    await verify_project_access(project_id, user_id, session)
    rows, total = await svc.list_pins(
        project_id,
        document_id=document_id,
        sheet_id=sheet_id,
        page=page,
        target_kind=target_kind,
        status_=status_filter,
        revision_state=revision_state,
        offset=offset,
        limit=limit,
    )
    return PinListResponse(items=await _respond(rows, svc), total=total, offset=offset, limit=limit)


@router.post("/pins/", response_model=PlanPinResponse, status_code=201, dependencies=[_WRITE])
async def create_registry_pin(
    data: PinCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    svc: PinService = Depends(_get_pin_service),
) -> PlanPinResponse:
    """Create a pin on a drawing page or a BIM element; idempotent on ``client_op_id``."""
    await verify_project_access(data.project_id, user_id, session)
    pin = await svc.create(data, user_id)
    resp = await _respond_one(pin, svc)
    resp.validation_warnings = getattr(pin, "validation_warnings", [])
    await session.commit()
    return resp


@router.get("/pins/by-target/{kind}/{target_id}", response_model=PinListResponse, dependencies=[_READ])
async def pins_by_target(
    kind: str,
    target_id: str,
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    svc: PinService = Depends(_get_pin_service),
) -> PinListResponse:
    """The pins of one record, so its page can show where it is."""
    if kind not in PIN_TARGET_KINDS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown record kind")
    await verify_project_access(project_id, user_id, session)
    rows, total = await svc.list_pins(project_id, target_kind=kind, target_id=target_id, limit=1000)
    return PinListResponse(items=await _respond(rows, svc), total=total, offset=0, limit=1000)


@router.get("/bim/{model_id}/pins", response_model=PinListResponse, dependencies=[_READ])
async def pins_on_bim_model(
    model_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    svc: PinService = Depends(_get_pin_service),
) -> PinListResponse:
    """The pins on the elements of one BIM model."""
    from app.modules.bim_hub.models import BIMModel

    model = await session.get(BIMModel, model_id)
    if model is None or model.project_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model not found")
    await verify_project_access(model.project_id, user_id, session)
    rows, total = await svc.list_pins(model.project_id, bim_model_id=str(model_id), limit=1000)
    return PinListResponse(items=await _respond(rows, svc), total=total, offset=0, limit=1000)


@router.patch("/pins/{pin_id}", response_model=PlanPinResponse, dependencies=[_WRITE])
async def update_registry_pin(
    pin_id: uuid.UUID,
    data: PinUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    svc: PinService = Depends(_get_pin_service),
) -> PlanPinResponse:
    """Move, relink or review a pin."""
    pin = await svc.get(pin_id)
    await verify_project_access(pin.project_id, user_id, session)
    pin = await svc.update(pin, data)
    resp = await _respond_one(pin, svc)
    resp.validation_warnings = getattr(pin, "validation_warnings", [])
    await session.commit()
    return resp


@router.post("/pins/carry-forward/", response_model=PinListResponse, status_code=201, dependencies=[_WRITE])
async def carry_pins_forward(
    project_id: uuid.UUID,
    from_sheet_id: str,
    to_document_id: str,
    user_id: CurrentUserId,
    session: SessionDep,
    svc: PinService = Depends(_get_pin_service),
) -> PinListResponse:
    """Copy the pins of a superseded sheet onto its replacement, marked for review."""
    await verify_project_access(project_id, user_id, session)
    rows = await svc.carry_forward(project_id, from_sheet_id, to_document_id, user_id)
    await session.commit()
    return PinListResponse(items=await _respond(rows, svc), total=len(rows), offset=0, limit=len(rows) or 1)


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
    pin = await _get_pin_service(session).create(
        PinCreate(
            project_id=document.project_id,
            target_kind="note",
            document_id=str(document.id),
            page=page,
            x=data.x,
            y=data.y,
            note=data.note,
            photo_ref=data.photo_ref,
            file_version_id=data.file_version_id,
            metadata=data.metadata,
        ),
        user_id,
    )
    await session.commit()
    return PlanPinResponse.model_validate(pin)


@router.delete("/pins/{pin_id}", status_code=204, dependencies=[_WRITE])
async def delete_pin(
    pin_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    svc: PinService = Depends(_get_pin_service),
) -> None:
    """Remove a positioned pin (project access via the pin's own project)."""
    pin = await svc.get(pin_id)
    await verify_project_access(pin.project_id, user_id, session)
    await svc.delete(pin)
    await session.commit()
