# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Outlook Bridge API routes (mounted at ``/api/v1/outlook-bridge/``).

Endpoints (OUTBOUND only - this build does not read a mailbox):
    GET  /                                    - module ping + platform capability
    POST /preview/{correspondence_id}         - render the email (NO side effects)
    POST /draft/{correspondence_id}           - open the SAME payload as an Outlook draft
    POST /eml/{correspondence_id}             - download the SAME payload as an editable .eml
"""

from __future__ import annotations

import sys
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.outlook_bridge import service
from app.modules.outlook_bridge.ps import OutlookUnavailable

router = APIRouter(tags=["outlook_bridge"])


class EmailOptions(BaseModel):
    """Preview/draft options - both endpoints take the SAME shape, because
    both go through the same builder."""

    subject_override: str | None = Field(default=None, max_length=500)
    body_override: str | None = Field(default=None, max_length=50_000)
    extra_to: list[str] = Field(default_factory=list, max_length=20)


@router.get("/")
async def module_info() -> dict[str, object]:
    return {
        "module": "oe_outlook_bridge",
        "status": "active",
        # COM needs desktop Outlook on THIS machine; the .eml download is the
        # path that survives a move to a server. Inbound capture (reading a
        # mailbox) is deliberately not part of this build.
        "outlook_possible": sys.platform == "win32",
    }


@router.post("/preview/{correspondence_id}")
async def preview_email(
    correspondence_id: uuid.UUID,
    payload: EmailOptions,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("outlook_bridge.read")),
) -> dict[str, object]:
    """Render the register email in-app. No ticket burned, nothing opened -
    and byte-for-byte what /draft would put in Outlook."""
    try:
        built = await service.build_email_payload(
            session,
            str(correspondence_id),
            subject_override=payload.subject_override,
            body_override=payload.body_override,
            extra_to=payload.extra_to,
        )
    except service.BridgeError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    from app.modules.correspondence.models import Correspondence

    row = (
        await session.execute(select(Correspondence.project_id).where(Correspondence.id == correspondence_id))
    ).scalar_one_or_none()
    if row is not None:
        await verify_project_access(row, user_id, session)
    return built


@router.post("/draft/{correspondence_id}")
async def open_draft(
    correspondence_id: uuid.UUID,
    payload: EmailOptions,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("outlook_bridge.draft")),
) -> dict[str, object]:
    """Open the Outlook draft. Send stays human - the bridge never sends."""
    from app.modules.correspondence.models import Correspondence

    project_id = (
        await session.execute(select(Correspondence.project_id).where(Correspondence.id == correspondence_id))
    ).scalar_one_or_none()
    if project_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Correspondence not found")
    await verify_project_access(project_id, user_id, session)
    try:
        built = await service.build_email_payload(
            session,
            str(correspondence_id),
            subject_override=payload.subject_override,
            body_override=payload.body_override,
            extra_to=payload.extra_to,
        )
        result = await service.open_payload_in_outlook(session, built, user_id=str(user_id))
    except service.BridgeError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    except OutlookUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from None
    await session.commit()
    return result


@router.post("/eml/{correspondence_id}")
async def download_eml(
    correspondence_id: uuid.UUID,
    payload: EmailOptions,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("outlook_bridge.draft")),
):
    """The browser/server path: the SAME email as a .eml download that
    Outlook opens as an editable unsent draft (X-Unsent: 1). Works from
    any browser against a self-hosted server - no COM needed."""
    from fastapi.responses import Response

    from app.modules.correspondence.models import Correspondence
    from app.modules.outlook_bridge.eml import build_eml

    project_id = (
        await session.execute(select(Correspondence.project_id).where(Correspondence.id == correspondence_id))
    ).scalar_one_or_none()
    if project_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Correspondence not found")
    await verify_project_access(project_id, user_id, session)
    try:
        built = await service.build_email_payload(
            session,
            str(correspondence_id),
            subject_override=payload.subject_override,
            body_override=payload.body_override,
            extra_to=payload.extra_to,
        )
    except service.BridgeError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    filename = f"{built['reference_number'] or 'draft'}.eml".replace("/", "-")
    return Response(
        content=build_eml(built),
        media_type="message/rfc822",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
