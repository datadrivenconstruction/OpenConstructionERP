# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Tendering side of unified parties: link and unlink a bidder, and the validation payload."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.contacts import parties as core
from app.modules.contacts.lookup import assignable_contact, contact_display_name
from app.modules.contacts.models import Contact
from app.modules.tendering.models import TenderBid, TenderBidInvitation
from app.modules.tendering.schemas import PartyLinkResponse


async def _response(session: AsyncSession, entity: Any) -> PartyLinkResponse:
    contact = await session.get(Contact, entity.contact_id) if entity.contact_id else None
    return PartyLinkResponse(
        entity_id=entity.id,
        contact_id=entity.contact_id,
        contact_name=contact_display_name(contact) if contact is not None else "",
        contact_match_method=entity.contact_match_method,
        contact_match_confidence=entity.contact_match_confidence,
    )


async def link(
    session: AsyncSession, entity: TenderBid | TenderBidInvitation, contact_id: uuid.UUID, actor_id: str
) -> PartyLinkResponse:
    """Link a bid or invitation to a contact the caller may use."""
    await assignable_contact(session, contact_id, actor_id)
    await core.link_party(session, entity, contact_id)
    return await _response(session, entity)


async def unlink(session: AsyncSession, entity: TenderBid | TenderBidInvitation) -> PartyLinkResponse:
    """Remove the link; the pair is not suggested again."""
    await core.unlink_party(session, entity)
    return await _response(session, entity)


async def validation_payload(session: AsyncSession, package_id: uuid.UUID) -> dict[str, Any]:
    """Bidders of a package: live invitations (one per firm) and bids."""
    invitations = (
        (
            await session.execute(
                select(TenderBidInvitation)
                .where(TenderBidInvitation.package_id == package_id, TenderBidInvitation.revoked_at.is_(None))
                .order_by(TenderBidInvitation.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    bids = (await session.execute(select(TenderBid).where(TenderBid.package_id == package_id))).scalars().all()
    seen: set[str] = set()
    bidders: list[dict[str, Any]] = []
    for inv in invitations:
        if inv.recipient_id in seen:
            continue
        seen.add(inv.recipient_id)
        bidders.append(
            {
                "id": str(inv.id),
                "kind": "invitation",
                "name": inv.company_name,
                "contact_id": str(inv.contact_id) if inv.contact_id else None,
            }
        )
    bidders.extend(
        {
            "id": str(b.id),
            "kind": "bid",
            "name": b.company_name,
            "contact_id": str(b.contact_id) if b.contact_id else None,
        }
        for b in bids
    )
    return {"bidders": bidders}
