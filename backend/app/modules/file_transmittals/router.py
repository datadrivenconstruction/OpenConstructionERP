# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""File Transmittals (W7) API routes.

Mounted by the module loader at ``/api/v1/file-transmittals``.

Endpoints
~~~~~~~~~
* ``GET    /``                 - list transmittals (filtered by project_id)
* ``POST   /``                 - create draft + optional items/recipients
* ``GET    /{id}``             - full transmittal
* ``POST   /{id}/send/``       - flip draft to sent, mint tokens, gen cover
* ``POST   /{id}/items/``      - append an item
* ``DELETE /{id}/items/{iid}`` - remove an item
* ``POST   /{id}/recipients/`` - append a recipient
* ``POST   /ack/{token}/``     - recipient ack (public, no auth)
* ``GET    /{id}/cover/``      - download cover sheet bytes

All authenticated routes go through a per-project IDOR guard so a
viewer of one project can never read another's transmittals.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.content_disposition import attachment_disposition
from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.file_transmittals.models import FileTransmittal
from app.modules.file_transmittals.schemas import (
    TransmittalAcknowledgeResponse,
    TransmittalCreate,
    TransmittalItemCreate,
    TransmittalItemResponse,
    TransmittalListItem,
    TransmittalRecipientCreate,
    TransmittalRecipientResponse,
    TransmittalResponse,
)
from app.modules.file_transmittals.service import TransmittalService
from app.modules.teams.party_access import party_read_clause, verify_record_access

logger = logging.getLogger(__name__)

router = APIRouter(tags=["File Transmittals"])


def _get_service(session: SessionDep) -> TransmittalService:
    return TransmittalService(session)


async def _require_project_access(session: AsyncSession, project_id: uuid.UUID, user_id: str) -> None:
    """Verify the caller may access ``project_id`` (owner, admin, or team member).

    RBAC fix: the previous owner-only check excluded legitimate project team
    members from every transmittals endpoint. Delegate to the canonical
    team-inclusive policy :func:`app.dependencies.verify_project_access`
    (owner + global admin + team member), which raises HTTPException(404) on
    denial to avoid leaking project existence (IDOR defence).
    """
    # Closes owner-only RBAC gap: team members were denied all transmittal access.
    from app.dependencies import verify_project_access

    await verify_project_access(project_id, user_id, session)


async def _require_record_access(
    session: AsyncSession,
    transmittal,  # noqa: ANN001
    user_id: str,
    *,
    write: bool = False,
) -> None:
    """Project access plus party visibility for one transmittal (404 when hidden).

    ``write=True`` answers 403 to a party that holds the transmittal through a
    view-only share.
    """
    await verify_record_access(
        session,
        entity_type="file_transmittal",
        project_id=transmittal.project_id,
        entity_id=transmittal.id,
        user_id=user_id,
        write=write,
    )


def _to_list_item(transmittal) -> TransmittalListItem:  # noqa: ANN001
    """Map a fully-loaded :class:`Transmittal` to the compact list shape."""
    return TransmittalListItem(
        id=transmittal.id,
        project_id=transmittal.project_id,
        number=transmittal.number,
        subject=transmittal.subject,
        reason_code=transmittal.reason_code,
        sender_id=transmittal.sender_id,
        sent_at=transmittal.sent_at,
        status=transmittal.status,
        item_count=len(transmittal.items),
        recipient_count=len(transmittal.recipients),
        acknowledged_count=sum(1 for r in transmittal.recipients if r.acknowledged_at is not None),
        created_at=transmittal.created_at,
        updated_at=transmittal.updated_at,
    )


def _to_response(transmittal, *, mask_tokens: bool = True) -> TransmittalResponse:  # noqa: ANN001
    """Map ORM → response, optionally masking ack tokens.

    Tokens are returned ONLY by the ``send`` endpoint (so the caller
    can forward them by email). All other reads mask them to prevent
    accidental harvesting by a project owner.
    """
    items = [TransmittalItemResponse.model_validate(i) for i in transmittal.items]
    recipients = [
        TransmittalRecipientResponse(
            id=r.id,
            transmittal_id=r.transmittal_id,
            email=r.email,
            display_name=r.display_name,
            role=r.role,
            acknowledged_at=r.acknowledged_at,
            acknowledge_token=None if mask_tokens else r.acknowledge_token,
        )
        for r in transmittal.recipients
    ]
    return TransmittalResponse(
        id=transmittal.id,
        project_id=transmittal.project_id,
        number=transmittal.number,
        subject=transmittal.subject,
        reason_code=transmittal.reason_code,
        sender_id=transmittal.sender_id,
        sent_at=transmittal.sent_at,
        status=transmittal.status,
        notes=transmittal.notes,
        cover_sheet_path=transmittal.cover_sheet_path,
        items=items,
        recipients=recipients,
        created_at=transmittal.created_at,
        updated_at=transmittal.updated_at,
    )


# ── List ──────────────────────────────────────────────────────────────────


@router.get(
    "/",
    response_model=list[TransmittalListItem],
    dependencies=[Depends(RequirePermission("file_transmittals.read"))],
)
async def list_transmittals(
    user_id: CurrentUserId,
    session: SessionDep,
    service: TransmittalService = Depends(_get_service),
    project_id: uuid.UUID = Query(...),
) -> list[TransmittalListItem]:
    """List transmittals for one project, newest first."""
    await _require_project_access(session, project_id, user_id)
    party_clause = await party_read_clause(
        session,
        user_id=user_id,
        entity_type="file_transmittal",
        id_column=FileTransmittal.id,
        project_id_column=FileTransmittal.project_id,
    )
    rows = await service.list_for_project(project_id, party_clause=party_clause)
    return [_to_list_item(t) for t in rows]


# ── Create draft ──────────────────────────────────────────────────────────


@router.post(
    "/",
    response_model=TransmittalResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("file_transmittals.write"))],
)
async def create_transmittal(
    data: TransmittalCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: TransmittalService = Depends(_get_service),
) -> TransmittalResponse:
    """Create a draft transmittal (auto-allocates ``T-NNNN``)."""
    await _require_project_access(session, data.project_id, user_id)
    transmittal = await service.create_draft(data, sender_id=user_id)
    return _to_response(transmittal)


# ── Get ───────────────────────────────────────────────────────────────────


@router.get(
    "/{transmittal_id}",
    response_model=TransmittalResponse,
    dependencies=[Depends(RequirePermission("file_transmittals.read"))],
)
async def get_transmittal(
    transmittal_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: TransmittalService = Depends(_get_service),
) -> TransmittalResponse:
    """Load full transmittal payload (items + recipients)."""
    transmittal = await service.get(transmittal_id)
    await _require_record_access(session, transmittal, user_id)
    return _to_response(transmittal)


# ── Send ──────────────────────────────────────────────────────────────────


@router.post(
    "/{transmittal_id}/send/",
    response_model=TransmittalResponse,
    dependencies=[Depends(RequirePermission("file_transmittals.send"))],
)
async def send_transmittal(
    transmittal_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: TransmittalService = Depends(_get_service),
) -> TransmittalResponse:
    """Flip draft → sent, mint ack tokens, generate cover sheet.

    The returned payload includes ``acknowledge_token`` on each recipient
    so the caller can forward the ack link by email; the regular GET
    endpoint masks the token.
    """
    transmittal = await service.get(transmittal_id)
    await _require_record_access(session, transmittal, user_id, write=True)
    transmittal = await service.send(transmittal_id)
    return _to_response(transmittal, mask_tokens=False)


# ── Items ─────────────────────────────────────────────────────────────────


@router.post(
    "/{transmittal_id}/items/",
    response_model=TransmittalItemResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("file_transmittals.write"))],
)
async def add_item(
    transmittal_id: uuid.UUID,
    data: TransmittalItemCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: TransmittalService = Depends(_get_service),
) -> TransmittalItemResponse:
    """Append an item to a transmittal."""
    transmittal = await service.get(transmittal_id)
    await _require_record_access(session, transmittal, user_id, write=True)
    row = await service.add_item(transmittal_id, data)
    return TransmittalItemResponse.model_validate(row)


@router.delete(
    "/{transmittal_id}/items/{item_id}/",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(RequirePermission("file_transmittals.write"))],
)
async def remove_item(
    transmittal_id: uuid.UUID,
    item_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: TransmittalService = Depends(_get_service),
) -> Response:
    """Remove an item from a transmittal."""
    transmittal = await service.get(transmittal_id)
    await _require_record_access(session, transmittal, user_id, write=True)
    await service.remove_item(transmittal_id, item_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Recipients ────────────────────────────────────────────────────────────


@router.post(
    "/{transmittal_id}/recipients/",
    response_model=TransmittalRecipientResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RequirePermission("file_transmittals.write"))],
)
async def add_recipient(
    transmittal_id: uuid.UUID,
    data: TransmittalRecipientCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: TransmittalService = Depends(_get_service),
) -> TransmittalRecipientResponse:
    """Append a recipient (idempotent on email)."""
    transmittal = await service.get(transmittal_id)
    await _require_record_access(session, transmittal, user_id, write=True)
    row = await service.add_recipient(transmittal_id, data)
    return TransmittalRecipientResponse(
        id=row.id,
        transmittal_id=row.transmittal_id,
        email=row.email,
        display_name=row.display_name,
        role=row.role,
        acknowledged_at=row.acknowledged_at,
        # Token only surfaces via send/ - not on the recipient-add path.
        acknowledge_token=None,
    )


# ── Public ack endpoint ───────────────────────────────────────────────────


@router.post(
    "/ack/{token}/",
    response_model=TransmittalAcknowledgeResponse,
)
async def acknowledge(
    token: str,
    service: TransmittalService = Depends(_get_service),
) -> TransmittalAcknowledgeResponse:
    """Public recipient ack endpoint - no auth required, token-gated.

    Token is matched against ``oe_file_transmittal_recipient.acknowledge_token``.
    Idempotent: a second call returns the same payload without re-stamping.
    """
    transmittal, recipient = await service.acknowledge_by_token(token)
    # ``acknowledged_at`` is set by the service; non-None invariant holds.
    assert recipient.acknowledged_at is not None  # noqa: S101 - invariant
    return TransmittalAcknowledgeResponse(
        transmittal_number=transmittal.number,
        subject=transmittal.subject,
        acknowledged_at=recipient.acknowledged_at,
        recipient_email=recipient.email,
    )


# ── Cover sheet download ──────────────────────────────────────────────────


@router.get(
    "/{transmittal_id}/cover/",
    dependencies=[Depends(RequirePermission("file_transmittals.read"))],
)
async def download_cover(
    transmittal_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: TransmittalService = Depends(_get_service),
) -> Response:
    """Return the cover sheet bytes (PDF or TXT depending on availability)."""
    transmittal = await service.get(transmittal_id)
    await _require_record_access(session, transmittal, user_id)
    data, media_type = await service.read_cover(transmittal_id)
    ext = "pdf" if media_type == "application/pdf" else "txt"
    safe_number = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in (transmittal.number or "transmittal"))
    filename = f"transmittal_{safe_number}.{ext}"
    return Response(
        content=data,
        media_type=media_type,
        headers={
            "Content-Disposition": attachment_disposition(filename),
        },
    )
