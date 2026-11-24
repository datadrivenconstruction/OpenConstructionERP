# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Revision control of a document chain and the records that point at a document.

A chain is the root document plus every document whose ``parent_document_id`` is
the root. Exactly one member is the current revision; the others are superseded.
``is_current_revision`` is ``NULL`` on rows that predate revision control and
reads as current, so only an explicit ``False`` marks a superseded revision.

Neighbour modules (plan room, file transmittals) call these helpers instead of
re-deriving the rule, so "superseded" means the same thing everywhere.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.documents.models import Document


def is_superseded(document: Any) -> bool:
    """Whether the document is an earlier revision that a newer one replaced."""
    return getattr(document, "is_current_revision", None) is False


def chain_root_id(document: Document) -> uuid.UUID:
    """Id of the first document of the chain ``document`` belongs to."""
    return document.parent_document_id or document.id


async def chain_members(session: AsyncSession, document: Document) -> list[Document]:
    """Every revision of the document, oldest first."""
    root = chain_root_id(document)
    stmt = (
        select(Document)
        .where((Document.id == root) | (Document.parent_document_id == root))
        .order_by(Document.created_at, Document.id)
    )
    return list((await session.execute(stmt)).scalars().all())


async def current_revision(session: AsyncSession, document: Document) -> Document | None:
    """The current member of the chain (the newest one if the flags disagree)."""
    members = await chain_members(session, document)
    current = [m for m in members if not is_superseded(m)]
    return current[-1] if current else None


async def make_current(session: AsyncSession, document: Document) -> list[uuid.UUID]:
    """Make ``document`` the one current revision of its chain.

    Every other member is marked superseded in the same transaction, so a chain
    never holds two current revisions. Returns the ids that were demoted.
    """
    demoted: list[uuid.UUID] = []
    for member in await chain_members(session, document):
        if member.id == document.id:
            continue
        if not is_superseded(member):
            member.is_current_revision = False
            demoted.append(member.id)
    document.is_current_revision = True
    await session.flush()
    return demoted


async def linked_records(session: AsyncSession, document: Document) -> dict[str, list[dict[str, Any]]]:
    """RFIs, NCRs and change orders that point at the document.

    An RFI points at drawings through ``linked_drawing_ids``, an NCR through
    ``linked_document_ids``. A change order is reached through the RFIs it lists
    (``linked_rfi_ids``) and through NCRs that name it (``change_order_id``).
    Each row says whether it points at a revision that is no longer current, so
    the reader can see work that was raised against an old drawing.
    """
    doc_key = str(document.id)
    superseded = is_superseded(document)
    out: dict[str, list[dict[str, Any]]] = {"rfis": [], "ncrs": [], "change_orders": []}
    rfi_ids: set[str] = set()
    co_ids: set[str] = set()

    try:
        from app.modules.rfi.models import RFI

        rows = (await session.execute(select(RFI).where(RFI.project_id == document.project_id))).scalars().all()
        for r in rows:
            if doc_key in {str(x) for x in (r.linked_drawing_ids or [])}:
                rfi_ids.add(str(r.id))
                out["rfis"].append(
                    {
                        "id": str(r.id),
                        "number": r.rfi_number,
                        "title": r.subject,
                        "status": r.status,
                        "on_superseded_revision": superseded,
                    }
                )
    except Exception:  # noqa: BLE001 - optional module / table absent
        out["rfis"] = []

    try:
        from app.modules.ncr.models import NCR

        rows = (await session.execute(select(NCR).where(NCR.project_id == document.project_id))).scalars().all()
        for n in rows:
            if doc_key in {str(x) for x in (n.linked_document_ids or [])}:
                if n.change_order_id:
                    co_ids.add(str(n.change_order_id))
                out["ncrs"].append(
                    {
                        "id": str(n.id),
                        "number": n.ncr_number,
                        "title": n.title,
                        "status": n.status,
                        "on_superseded_revision": superseded,
                    }
                )
    except Exception:  # noqa: BLE001
        out["ncrs"] = []

    try:
        from app.modules.changeorders.models import ChangeOrder

        rows = (
            (await session.execute(select(ChangeOrder).where(ChangeOrder.project_id == document.project_id)))
            .scalars()
            .all()
        )
        for c in rows:
            via_rfi = bool(rfi_ids & {str(x) for x in (c.linked_rfi_ids or [])})
            if via_rfi or str(c.id) in co_ids:
                out["change_orders"].append(
                    {
                        "id": str(c.id),
                        "number": c.code,
                        "title": c.title,
                        "status": c.status,
                        "on_superseded_revision": superseded,
                    }
                )
    except Exception:  # noqa: BLE001
        out["change_orders"] = []
    return out
