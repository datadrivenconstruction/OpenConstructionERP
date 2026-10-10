# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Transmittals API routes.

A transmittal is a formal record of documents or drawings handed to named
parties: what was sent, when, to whom, and any response that was asked for.

Endpoints:
    GET    /                                              - List a project's transmittals
    POST   /                                              - Create a draft (number assigned automatically)
    GET    /{transmittal_id}                              - Get one transmittal
    PATCH  /{transmittal_id}                              - Edit a draft (blocked once issued)
    DELETE /{transmittal_id}                              - Delete a draft (issued ones are kept for the record)
    POST   /{transmittal_id}/issue                        - Send it: lock the record and mark it issued
    POST   /{transmittal_id}/recipients/{id}/acknowledge  - A recipient confirms they received it
    POST   /{transmittal_id}/recipients/{id}/respond      - A recipient sends their response
"""

import uuid

from fastapi import APIRouter, Depends, Query

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.transmittals.schemas import (
    AcknowledgeRequest,
    RecipientCreate,
    RecipientResponse,
    RespondRequest,
    TransmittalCreate,
    TransmittalListResponse,
    TransmittalResponse,
    TransmittalUpdate,
)
from app.modules.transmittals.service import TransmittalService

router = APIRouter(tags=["transmittals"])

# Register and record exports (workbook and PDF). Included first, so the
# static "export" paths are matched before the "/{id}" routes below.
from app.modules.transmittals.export_routes import export_router  # noqa: E402

router.include_router(export_router)


def _get_service(session: SessionDep) -> TransmittalService:
    return TransmittalService(session)


# ── List ────────────────────────────────────────────────────────────────────


@router.get(
    "/",
    response_model=TransmittalListResponse,
    dependencies=[Depends(RequirePermission("transmittals.read"))],
)
async def list_transmittals(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    status: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: TransmittalService = Depends(_get_service),
) -> TransmittalListResponse:
    """List transmittals for a project."""
    await verify_project_access(project_id, user_id, session)
    items, total = await service.list_transmittals(
        project_id,
        transmittal_status=status,
        offset=offset,
        limit=limit,
    )
    return TransmittalListResponse(
        items=[TransmittalResponse.model_validate(t) for t in items],
        total=total,
        offset=offset,
        limit=limit,
    )


# ── Create ──────────────────────────────────────────────────────────────────


@router.post(
    "/",
    response_model=TransmittalResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("transmittals.create"))],
)
async def create_transmittal(
    data: TransmittalCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: TransmittalService = Depends(_get_service),
) -> TransmittalResponse:
    """Create a new transmittal with auto-generated number."""
    await verify_project_access(data.project_id, user_id, session)
    transmittal = await service.create_transmittal(data, user_id=user_id)
    return TransmittalResponse.model_validate(transmittal)


# ── Get ─────────────────────────────────────────────────────────────────────


@router.get(
    "/{transmittal_id}",
    response_model=TransmittalResponse,
    dependencies=[Depends(RequirePermission("transmittals.read"))],
)
async def get_transmittal(
    transmittal_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: TransmittalService = Depends(_get_service),
) -> TransmittalResponse:
    """Get a single transmittal by ID."""
    transmittal = await service.get_transmittal(transmittal_id)
    await verify_project_access(transmittal.project_id, str(user_id), session)
    return TransmittalResponse.model_validate(transmittal)


# ── Update ──────────────────────────────────────────────────────────────────


@router.patch(
    "/{transmittal_id}",
    response_model=TransmittalResponse,
    dependencies=[Depends(RequirePermission("transmittals.update"))],
)
async def update_transmittal(
    transmittal_id: uuid.UUID,
    data: TransmittalUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
    service: TransmittalService = Depends(_get_service),
) -> TransmittalResponse:
    """Update a transmittal (fails if locked after issue)."""
    existing = await service.get_transmittal(transmittal_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    transmittal = await service.update_transmittal(transmittal_id, data)
    return TransmittalResponse.model_validate(transmittal)


# ── Delete ──────────────────────────────────────────────────────────────────


@router.delete(
    "/{transmittal_id}",
    status_code=204,
    dependencies=[Depends(RequirePermission("transmittals.delete"))],
)
async def delete_transmittal(
    transmittal_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    service: TransmittalService = Depends(_get_service),
) -> None:
    """Delete a draft transmittal. Issued ones return 409."""
    existing = await service.get_transmittal(transmittal_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    await service.delete_transmittal(transmittal_id)


# ── Issue ───────────────────────────────────────────────────────────────────


@router.post(
    "/{transmittal_id}/issue/",
    response_model=TransmittalResponse,
    dependencies=[Depends(RequirePermission("transmittals.update"))],
)
async def issue_transmittal(
    transmittal_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: TransmittalService = Depends(_get_service),
) -> TransmittalResponse:
    """Send the transmittal: lock the record and mark it issued.

    Needs at least one recipient and one document, otherwise returns 422.
    """
    existing = await service.get_transmittal(transmittal_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    transmittal = await service.issue_transmittal(transmittal_id)
    return TransmittalResponse.model_validate(transmittal)


# ── Recipients (add / remove on a draft) ─────────────────────────────────────


@router.post(
    "/{transmittal_id}/recipients/",
    response_model=RecipientResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("transmittals.update"))],
)
async def add_recipient(
    transmittal_id: uuid.UUID,
    data: RecipientCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    service: TransmittalService = Depends(_get_service),
) -> RecipientResponse:
    """Add one recipient to a draft transmittal (blocked once issued)."""
    existing = await service.get_transmittal(transmittal_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    recipient = await service.add_recipient(transmittal_id, data)
    return RecipientResponse.model_validate(recipient)


@router.delete(
    "/{transmittal_id}/recipients/{recipient_id}",
    status_code=204,
    dependencies=[Depends(RequirePermission("transmittals.update"))],
)
async def remove_recipient(
    transmittal_id: uuid.UUID,
    recipient_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    service: TransmittalService = Depends(_get_service),
) -> None:
    """Remove a recipient from a draft transmittal (blocked once issued)."""
    existing = await service.get_transmittal(transmittal_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    await service.remove_recipient(transmittal_id, recipient_id)


# ── Acknowledge ─────────────────────────────────────────────────────────────


@router.post(
    "/{transmittal_id}/recipients/{recipient_id}/acknowledge/",
    response_model=RecipientResponse,
    dependencies=[Depends(RequirePermission("transmittals.update"))],
)
async def acknowledge_receipt(
    transmittal_id: uuid.UUID,
    recipient_id: uuid.UUID,
    _body: AcknowledgeRequest,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: TransmittalService = Depends(_get_service),
) -> RecipientResponse:
    """Acknowledge receipt of a transmittal."""
    existing = await service.get_transmittal(transmittal_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    recipient = await service.acknowledge_receipt(transmittal_id, recipient_id)
    return RecipientResponse.model_validate(recipient)


# ── Respond ─────────────────────────────────────────────────────────────────


@router.post(
    "/{transmittal_id}/recipients/{recipient_id}/respond/",
    response_model=RecipientResponse,
    dependencies=[Depends(RequirePermission("transmittals.update"))],
)
async def submit_response(
    transmittal_id: uuid.UUID,
    recipient_id: uuid.UUID,
    data: RespondRequest,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: TransmittalService = Depends(_get_service),
) -> RecipientResponse:
    """Submit a response to a transmittal."""
    existing = await service.get_transmittal(transmittal_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    recipient = await service.submit_response(transmittal_id, recipient_id, data.response)
    return RecipientResponse.model_validate(recipient)
