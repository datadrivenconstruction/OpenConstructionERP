# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Data access for the e-invoice clearance module.

Plain functions over an ``AsyncSession``, in the style of the cases module.
Every filter is on a real column: nothing here reaches inside ``country_fields``
or ``raw_response``, because a ``.contains()`` on a JSON column compiles to a
string LIKE on PostgreSQL rather than to JSONB containment, and a filter that
quietly means something else is worse than no filter.

The event trail is insert-only. There is no update and no delete for an event,
which is the whole reason the trail can be trusted: the rejection at 02:00 is
still there after the acceptance at 09:00.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.einvoice_clearance.models import (
    STATUS_CANCELLED,
    STATUS_REJECTED,
    EInvoiceDocument,
    EInvoiceEvent,
    EInvoiceProfile,
)

# ── Registrations ────────────────────────────────────────────────────────────


async def list_profiles(
    session: AsyncSession,
    *,
    country: str | None = None,
    company_key: str | None = None,
    active_only: bool = False,
) -> list[EInvoiceProfile]:
    """Registrations, newest first."""
    stmt = select(EInvoiceProfile)
    if country:
        stmt = stmt.where(EInvoiceProfile.country == country.strip().upper())
    if company_key:
        stmt = stmt.where(EInvoiceProfile.company_key == company_key.strip())
    if active_only:
        stmt = stmt.where(EInvoiceProfile.is_active.is_(True))
    stmt = stmt.order_by(EInvoiceProfile.country.asc(), EInvoiceProfile.company_key.asc())
    return list((await session.execute(stmt)).scalars().all())


async def get_profile(session: AsyncSession, profile_id: uuid.UUID) -> EInvoiceProfile | None:
    """One registration by id."""
    return (await session.execute(select(EInvoiceProfile).where(EInvoiceProfile.id == profile_id))).scalar_one_or_none()


async def get_profile_for(session: AsyncSession, *, company_key: str, country: str) -> EInvoiceProfile | None:
    """The registration one entity holds in one country, if any."""
    stmt = select(EInvoiceProfile).where(
        and_(
            EInvoiceProfile.company_key == company_key.strip(),
            EInvoiceProfile.country == country.strip().upper(),
        )
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def add_profile(session: AsyncSession, profile: EInvoiceProfile) -> EInvoiceProfile:
    """Store a new registration."""
    session.add(profile)
    await session.flush()
    return profile


async def count_documents_for_profile(session: AsyncSession, profile_id: uuid.UUID) -> int:
    """How many documents were filed under a registration.

    Read before deleting one: a registration with documents behind it is the
    only record of which identity those submissions were made under.
    """
    stmt = select(func.count()).select_from(EInvoiceDocument).where(EInvoiceDocument.profile_id == profile_id)
    return int((await session.execute(stmt)).scalar_one() or 0)


async def delete_profile(session: AsyncSession, profile: EInvoiceProfile) -> None:
    """Remove a registration. The caller checks it has no documents."""
    await session.delete(profile)
    await session.flush()


# ── Documents ────────────────────────────────────────────────────────────────


async def list_documents(
    session: AsyncSession,
    *,
    project_id: uuid.UUID | None = None,
    country: str | None = None,
    status: str | None = None,
    regime: str | None = None,
    invoice_id: uuid.UUID | None = None,
    limit: int = 200,
) -> list[EInvoiceDocument]:
    """Documents, newest first."""
    stmt = select(EInvoiceDocument)
    if project_id is not None:
        stmt = stmt.where(EInvoiceDocument.project_id == project_id)
    if country:
        stmt = stmt.where(EInvoiceDocument.country == country.strip().upper())
    if status:
        stmt = stmt.where(EInvoiceDocument.status == status.strip().lower())
    if regime:
        stmt = stmt.where(EInvoiceDocument.regime == regime.strip().lower())
    if invoice_id is not None:
        stmt = stmt.where(EInvoiceDocument.invoice_id == invoice_id)
    stmt = stmt.order_by(EInvoiceDocument.created_at.desc()).limit(max(1, min(limit, 1000)))
    return list((await session.execute(stmt)).scalars().all())


async def get_document(session: AsyncSession, document_id: uuid.UUID) -> EInvoiceDocument | None:
    """One document by id."""
    return (
        await session.execute(select(EInvoiceDocument).where(EInvoiceDocument.id == document_id))
    ).scalar_one_or_none()


async def add_document(session: AsyncSession, document: EInvoiceDocument) -> EInvoiceDocument:
    """Store a new document."""
    session.add(document)
    await session.flush()
    return document


async def find_live_duplicate(
    session: AsyncSession,
    *,
    profile_id: uuid.UUID,
    payload_hash: str,
    exclude_id: uuid.UUID | None = None,
) -> EInvoiceDocument | None:
    """An earlier document under the same registration with the same payload.

    Rejected and cancelled documents are not duplicates. A rejection is an
    invitation to send the same thing again once whatever the authority
    complained about has been fixed at their end, and a cancelled document has
    been withdrawn, so neither one blocks the payload from going.
    """
    stmt = select(EInvoiceDocument).where(
        and_(
            EInvoiceDocument.profile_id == profile_id,
            EInvoiceDocument.payload_hash == payload_hash,
            EInvoiceDocument.status.not_in((STATUS_REJECTED, STATUS_CANCELLED)),
        )
    )
    if exclude_id is not None:
        stmt = stmt.where(EInvoiceDocument.id != exclude_id)
    stmt = stmt.order_by(EInvoiceDocument.created_at.asc()).limit(1)
    return (await session.execute(stmt)).scalars().first()


# ── Trail ────────────────────────────────────────────────────────────────────


async def next_sequence(session: AsyncSession, document_id: uuid.UUID) -> int:
    """The next event number for a document, starting at 1."""
    stmt = select(func.max(EInvoiceEvent.sequence)).where(EInvoiceEvent.document_id == document_id)
    highest = (await session.execute(stmt)).scalar_one_or_none()
    return int(highest or 0) + 1


async def append_event(
    session: AsyncSession,
    *,
    document_id: uuid.UUID,
    event_type: str,
    from_status: str = "",
    to_status: str = "",
    message: str = "",
    authority_code: str = "",
    raw_response: dict[str, Any] | None = None,
    actor_id: uuid.UUID | None = None,
) -> EInvoiceEvent:
    """Append one entry to a document's trail. The only write an event gets."""
    event = EInvoiceEvent(
        document_id=document_id,
        sequence=await next_sequence(session, document_id),
        event_type=event_type,
        from_status=from_status,
        to_status=to_status,
        message=message,
        authority_code=authority_code,
        raw_response=dict(raw_response or {}),
        actor_id=actor_id,
    )
    session.add(event)
    await session.flush()
    return event


async def list_events(session: AsyncSession, document_id: uuid.UUID) -> list[EInvoiceEvent]:
    """A document's trail in the order it happened."""
    stmt = select(EInvoiceEvent).where(EInvoiceEvent.document_id == document_id).order_by(EInvoiceEvent.sequence.asc())
    return list((await session.execute(stmt)).scalars().all())


__all__ = [
    "add_document",
    "add_profile",
    "append_event",
    "count_documents_for_profile",
    "delete_profile",
    "find_live_duplicate",
    "get_document",
    "get_profile",
    "get_profile_for",
    "list_documents",
    "list_events",
    "list_profiles",
    "next_sequence",
]
