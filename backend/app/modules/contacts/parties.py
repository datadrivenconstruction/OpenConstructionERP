# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""One identity for a person or firm across contacts, tenders and the portal.

Tender invitations, tender bids and portal accounts each carry a name and an
email of their own. This module links such a row to the directory contact it
is the same party as, without ever merging or deleting a contact.

Matching goes email, then VAT or tax id, then exact company name, all
normalised. Only a unique email or VAT hit is linked on its own. A name-only
hit, or any signal that points at several contacts (or two signals that
disagree), is written to ``oe_contacts_party_review`` for a person to confirm
or reject. Every link records how it was made (``contact_match_method``) and
how sure the matcher was (``contact_match_confidence``).
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.contacts.models import Contact, PartyLinkReview

logger = logging.getLogger(__name__)

METHOD_EMAIL = "email"
METHOD_VAT = "vat"
METHOD_NAME = "name"
METHOD_RECIPIENT = "recipient"
METHOD_INVITATION = "invitation"
METHOD_MANUAL = "manual"

CONFIDENCE = {METHOD_EMAIL: 0.95, METHOD_VAT: 0.9, METHOD_NAME: 0.6}
AMBIGUOUS_CONFIDENCE = 0.4

ENTITY_TENDER_INVITATION = "tender_invitation"
ENTITY_TENDER_BID = "tender_bid"
ENTITY_PORTAL_USER = "portal_user"
ENTITY_TYPES = (ENTITY_TENDER_INVITATION, ENTITY_TENDER_BID, ENTITY_PORTAL_USER)

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_SPACES = re.compile(r"\s+")


def normalise_email(value: str | None) -> str:
    """Lower-cased, trimmed email; empty when it cannot be one."""
    text = (value or "").strip().lower()
    return text if "@" in text else ""


def normalise_vat(value: str | None) -> str:
    """VAT or tax id reduced to upper-case letters and digits."""
    return re.sub(r"[^0-9A-Z]", "", (value or "").upper())


def normalise_name(value: str | None) -> str:
    """Case-folded name with punctuation dropped and whitespace collapsed."""
    text = _PUNCT.sub(" ", (value or "").casefold())
    return _SPACES.sub(" ", text).strip()


@dataclass
class PartyIndex:
    """Lookup tables over one tenant's active contacts."""

    by_email: dict[str, list[uuid.UUID]] = field(default_factory=dict)
    by_vat: dict[str, list[uuid.UUID]] = field(default_factory=dict)
    by_name: dict[str, list[uuid.UUID]] = field(default_factory=dict)
    ids: set[uuid.UUID] = field(default_factory=set)

    def _add(self, table: dict[str, list[uuid.UUID]], key: str, contact_id: uuid.UUID) -> None:
        if key and contact_id not in table.setdefault(key, []):
            table[key].append(contact_id)

    def add(self, contact: Contact) -> None:
        """Index one contact under its email, VAT id and names."""
        self.ids.add(contact.id)
        self._add(self.by_email, normalise_email(contact.primary_email), contact.id)
        self._add(self.by_vat, normalise_vat(contact.vat_number), contact.id)
        for name in (contact.company_name, contact.legal_name):
            self._add(self.by_name, normalise_name(name), contact.id)
        person = " ".join(p for p in (contact.first_name, contact.last_name) if p)
        self._add(self.by_name, normalise_name(person), contact.id)


def build_index(contacts: list[Contact]) -> PartyIndex:
    """Index ``contacts`` (already filtered to one tenant and active)."""
    index = PartyIndex()
    for contact in contacts:
        index.add(contact)
    return index


@dataclass(frozen=True)
class MatchResult:
    """What the matcher decided for one row.

    ``decision`` is ``link`` (one contact, strong signal), ``review`` (a person
    must choose; ``contact_ids`` lists the candidates) or ``none``.
    """

    decision: str
    method: str | None = None
    confidence: float = 0.0
    contact_ids: tuple[uuid.UUID, ...] = ()
    reason: str = ""


NO_MATCH = MatchResult(decision="none")


def match_party(index: PartyIndex, *, name: str | None, email: str | None, vat: str | None = None) -> MatchResult:
    """Match one name, email and VAT id against the index. Pure, no database."""
    email_hits = index.by_email.get(normalise_email(email), [])
    vat_key = normalise_vat(vat)
    vat_hits = index.by_vat.get(vat_key, []) if vat_key else []

    if email_hits:
        everyone = tuple(dict.fromkeys([*email_hits, *vat_hits]))
        if len(email_hits) == 1 and (not vat_hits or vat_hits == email_hits):
            return MatchResult("link", METHOD_EMAIL, CONFIDENCE[METHOD_EMAIL], tuple(email_hits))
        return MatchResult("review", METHOD_EMAIL, AMBIGUOUS_CONFIDENCE, everyone, "ambiguous")
    if vat_hits:
        if len(vat_hits) == 1:
            return MatchResult("link", METHOD_VAT, CONFIDENCE[METHOD_VAT], tuple(vat_hits))
        return MatchResult("review", METHOD_VAT, AMBIGUOUS_CONFIDENCE, tuple(vat_hits), "ambiguous")
    name_hits = index.by_name.get(normalise_name(name), [])
    if len(name_hits) == 1:
        return MatchResult("review", METHOD_NAME, CONFIDENCE[METHOD_NAME], tuple(name_hits), "weak")
    if name_hits:
        return MatchResult("review", METHOD_NAME, AMBIGUOUS_CONFIDENCE, tuple(name_hits), "ambiguous")
    return NO_MATCH


def recipient_party(recipient: Mapping[str, Any]) -> dict[str, Any]:
    """Link columns for a row made from a package recipient entry.

    The recipient already carries the directory contact it was resolved to
    (picked, or found by email when it was added), so the row inherits it.
    """
    raw = recipient.get("contact_id")
    try:
        contact_id = uuid.UUID(str(raw)) if raw else None
    except ValueError:
        contact_id = None
    if contact_id is None:
        return {}
    return {
        "contact_id": contact_id,
        "contact_match_method": METHOD_RECIPIENT,
        "contact_match_confidence": CONFIDENCE[METHOD_EMAIL],
    }


# ── Database side ───────────────────────────────────────────────────────────


async def load_index(session: AsyncSession, owner_id: str | None) -> PartyIndex:
    """Index the active contacts of ``owner_id`` (tenant, else creator); ``None`` means all."""
    stmt = select(Contact).where(Contact.is_active.is_(True))
    if owner_id is not None:
        owner = str(owner_id)
        stmt = stmt.where(or_(Contact.tenant_id == owner, Contact.created_by == owner))
    return build_index(list((await session.execute(stmt)).scalars().all()))


@dataclass
class _Row:
    """One unlinked row, flattened to what the matcher needs."""

    entity_type: str
    entity: Any
    name: str
    email: str
    vat: str
    owner_id: str | None
    recipient_contact_id: uuid.UUID | None = None


async def _owner_of_projects(session: AsyncSession, project_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not project_ids:
        return {}
    from app.modules.projects.models import Project  # noqa: PLC0415

    rows = await session.execute(select(Project.id, Project.owner_id).where(Project.id.in_(project_ids)))
    return {pid: str(owner) for pid, owner in rows.all()}


async def _unlinked_rows(session: AsyncSession, actor_id: str | None, only: set[str]) -> list[_Row]:
    """Rows of the linkable tables that have no contact yet."""
    from app.modules.portal.models import PortalUser  # noqa: PLC0415
    from app.modules.tendering.models import TenderBid, TenderBidInvitation, TenderPackage  # noqa: PLC0415

    rows: list[_Row] = []
    packages: dict[uuid.UUID, TenderPackage] = {}

    async def package_of(package_id: uuid.UUID) -> TenderPackage | None:
        if package_id not in packages:
            packages[package_id] = await session.get(TenderPackage, package_id)  # type: ignore[assignment]
        return packages[package_id]

    if ENTITY_TENDER_INVITATION in only:
        invitations = (
            (await session.execute(select(TenderBidInvitation).where(TenderBidInvitation.contact_id.is_(None))))
            .scalars()
            .all()
        )
        projects = {}
        for inv in invitations:
            package = await package_of(inv.package_id)
            if package is not None:
                projects[inv.id] = package.project_id
        owners = await _owner_of_projects(session, set(projects.values()))
        for inv in invitations:
            package = await package_of(inv.package_id)
            recipients = (package.metadata_ or {}).get("recipients") if package is not None else None
            entry = next(
                (r for r in recipients or [] if isinstance(r, dict) and str(r.get("id")) == inv.recipient_id), {}
            )
            raw = entry.get("contact_id")
            try:
                recipient_contact = uuid.UUID(str(raw)) if raw else None
            except ValueError:
                recipient_contact = None
            rows.append(
                _Row(
                    ENTITY_TENDER_INVITATION,
                    inv,
                    inv.company_name,
                    inv.email,
                    str(entry.get("vat_id") or ""),
                    inv.created_by or owners.get(projects.get(inv.id, uuid.UUID(int=0))),
                    recipient_contact,
                )
            )
    if ENTITY_TENDER_BID in only:
        bids = (await session.execute(select(TenderBid).where(TenderBid.contact_id.is_(None)))).scalars().all()
        packages_for_bids = {b.package_id: await package_of(b.package_id) for b in bids}
        owners = await _owner_of_projects(session, {p.project_id for p in packages_for_bids.values() if p is not None})
        for bid in bids:
            package = packages_for_bids.get(bid.package_id)
            owner = owners.get(package.project_id) if package is not None else None
            rows.append(_Row(ENTITY_TENDER_BID, bid, bid.company_name, bid.contact_email, "", owner))
    if ENTITY_PORTAL_USER in only:
        users = (await session.execute(select(PortalUser).where(PortalUser.contact_id.is_(None)))).scalars().all()
        # Portal accounts have no owner of their own: they are matched in the
        # scope of the person who runs the backfill.
        rows.extend(_Row(ENTITY_PORTAL_USER, u, u.full_name, u.email, "", actor_id) for u in users)
    return rows


def _set_link(entity: Any, contact_id: uuid.UUID | None, method: str | None, confidence: float | None) -> None:
    entity.contact_id = contact_id
    entity.contact_match_method = method
    entity.contact_match_confidence = confidence


async def _upsert_review(
    session: AsyncSession, row: _Row, contact_id: uuid.UUID, result: MatchResult
) -> PartyLinkReview | None:
    """Record one candidate; a rejected pair is not offered again."""
    existing = (
        await session.execute(
            select(PartyLinkReview).where(
                PartyLinkReview.entity_type == row.entity_type,
                PartyLinkReview.entity_id == row.entity.id,
                PartyLinkReview.contact_id == contact_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return None
    review = PartyLinkReview(
        entity_type=row.entity_type,
        entity_id=row.entity.id,
        contact_id=contact_id,
        method=result.method or METHOD_NAME,
        confidence=result.confidence,
        reason=result.reason or "weak",
        status="pending",
        owner_id=row.owner_id,
    )
    session.add(review)
    return review


async def backfill(
    session: AsyncSession,
    *,
    actor_id: str | None,
    entity_types: set[str] | None = None,
    dry_run: bool = False,
) -> dict[str, dict[str, int]]:
    """Link every unlinked row that has one clear match; queue the rest for review.

    Idempotent: a linked row is skipped, a candidate already on the review list
    (pending, confirmed or rejected) is not added twice, so a second run changes
    nothing. Nothing is deleted and no contact is modified.

    Returns:
        ``{entity_type: {"linked", "queued", "unmatched"}}`` counts.
    """
    only = set(entity_types) if entity_types else set(ENTITY_TYPES)
    counts = {t: {"linked": 0, "queued": 0, "unmatched": 0} for t in sorted(only)}
    indexes: dict[str | None, PartyIndex] = {}
    rejected = {
        (r.entity_type, r.entity_id, r.contact_id)
        for r in (await session.execute(select(PartyLinkReview).where(PartyLinkReview.status == "rejected")))
        .scalars()
        .all()
    }
    for row in await _unlinked_rows(session, actor_id, only):
        if row.owner_id not in indexes:
            indexes[row.owner_id] = await load_index(session, row.owner_id)
        index = indexes[row.owner_id]
        bucket = counts[row.entity_type]

        def allowed(contact_id: uuid.UUID, row: _Row = row) -> bool:
            return (row.entity_type, row.entity.id, contact_id) not in rejected

        if (
            row.recipient_contact_id is not None
            and row.recipient_contact_id in index.ids
            and allowed(row.recipient_contact_id)
        ):
            if not dry_run:
                _set_link(row.entity, row.recipient_contact_id, METHOD_RECIPIENT, CONFIDENCE[METHOD_EMAIL])
            bucket["linked"] += 1
            continue
        result = match_party(index, name=row.name, email=row.email, vat=row.vat)
        candidates = tuple(c for c in result.contact_ids if allowed(c))
        if result.decision == "link" and candidates:
            if not dry_run:
                _set_link(row.entity, candidates[0], result.method, result.confidence)
            bucket["linked"] += 1
        elif result.decision == "review" and candidates:
            if not dry_run:
                for contact_id in candidates:
                    await _upsert_review(session, row, contact_id, result)
            bucket["queued"] += 1
        else:
            bucket["unmatched"] += 1
    if not dry_run:
        await session.flush()
    return counts


async def _entity(session: AsyncSession, entity_type: str, entity_id: uuid.UUID) -> Any:
    from app.modules.portal.models import PortalUser  # noqa: PLC0415
    from app.modules.tendering.models import TenderBid, TenderBidInvitation  # noqa: PLC0415

    model = {
        ENTITY_TENDER_INVITATION: TenderBidInvitation,
        ENTITY_TENDER_BID: TenderBid,
        ENTITY_PORTAL_USER: PortalUser,
    }.get(entity_type)
    return await session.get(model, entity_id) if model is not None else None


async def link_party(session: AsyncSession, entity: Any, contact_id: uuid.UUID) -> None:
    """Link a row to a contact by a person's decision (confidence 1.0)."""
    _set_link(entity, contact_id, METHOD_MANUAL, 1.0)
    await session.flush()


async def unlink_party(session: AsyncSession, entity: Any) -> None:
    """Remove a row's link. The contact is untouched; the link stays out of the review list."""
    previous = entity.contact_id
    _set_link(entity, None, None, None)
    if previous is not None:
        entity_type = {
            "TenderBidInvitation": ENTITY_TENDER_INVITATION,
            "TenderBid": ENTITY_TENDER_BID,
            "PortalUser": ENTITY_PORTAL_USER,
        }.get(type(entity).__name__)
        if entity_type is not None:
            await _reject_pair(session, entity_type, entity.id, previous)
    await session.flush()


async def _reject_pair(session: AsyncSession, entity_type: str, entity_id: uuid.UUID, contact_id: uuid.UUID) -> None:
    """Remember that a person said this pair is not the same party."""
    existing = (
        await session.execute(
            select(PartyLinkReview).where(
                PartyLinkReview.entity_type == entity_type,
                PartyLinkReview.entity_id == entity_id,
                PartyLinkReview.contact_id == contact_id,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        session.add(
            PartyLinkReview(
                entity_type=entity_type,
                entity_id=entity_id,
                contact_id=contact_id,
                method=METHOD_MANUAL,
                confidence=0.0,
                reason="weak",
                status="rejected",
            )
        )
    else:
        existing.status = "rejected"


async def list_reviews(
    session: AsyncSession, *, owner_id: str | None, status: str = "pending", limit: int = 200
) -> list[PartyLinkReview]:
    """Pending (by default) candidates; ``owner_id=None`` lists every owner's."""
    stmt = select(PartyLinkReview).where(PartyLinkReview.status == status)
    if owner_id is not None:
        stmt = stmt.where(PartyLinkReview.owner_id == str(owner_id))
    stmt = stmt.order_by(PartyLinkReview.confidence.desc(), PartyLinkReview.created_at).limit(limit)
    return list((await session.execute(stmt)).scalars().all())


async def decide_review(
    session: AsyncSession, review: PartyLinkReview, *, confirm: bool, actor_id: str | None
) -> PartyLinkReview:
    """Confirm (links the row, confidence 1.0, method kept as ``manual``) or reject a candidate.

    Confirming closes the other pending candidates of the same row.
    """
    review.reviewed_by = actor_id
    if not confirm:
        review.status = "rejected"
        await session.flush()
        return review
    entity = await _entity(session, review.entity_type, review.entity_id)
    if entity is None:
        review.status = "rejected"
        await session.flush()
        return review
    _set_link(entity, review.contact_id, METHOD_MANUAL, 1.0)
    review.status = "confirmed"
    others = (
        (
            await session.execute(
                select(PartyLinkReview).where(
                    PartyLinkReview.entity_type == review.entity_type,
                    PartyLinkReview.entity_id == review.entity_id,
                    PartyLinkReview.id != review.id,
                    PartyLinkReview.status == "pending",
                )
            )
        )
        .scalars()
        .all()
    )
    for other in others:
        other.status = "rejected"
        other.reviewed_by = actor_id
    await session.flush()
    return review


def entity_label(entity_type: str, entity: Any) -> tuple[str, str]:
    """Name and email of a linkable row, for the review list."""
    if entity_type == ENTITY_TENDER_BID:
        return entity.company_name or "", entity.contact_email or ""
    if entity_type == ENTITY_PORTAL_USER:
        return entity.full_name or "", entity.email or ""
    return entity.company_name or "", entity.email or ""
