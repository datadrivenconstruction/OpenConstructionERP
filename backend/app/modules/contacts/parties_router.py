# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unified parties: backfill and the human review list.

Mounted by the contacts router under ``/api/v1/contacts/parties/``.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.dependencies import CurrentUserId, RequirePermission, RequireRole, SessionDep
from app.modules.contacts import parties
from app.modules.contacts.lookup import _is_admin, contact_display_name
from app.modules.contacts.models import Contact, PartyLinkReview

router = APIRouter(prefix="/parties", tags=["contacts"])


class BackfillRequest(BaseModel):
    """Which row kinds to process; empty means all of them."""

    entity_types: list[str] = Field(default_factory=list)
    dry_run: bool = False


class BackfillResponse(BaseModel):
    dry_run: bool
    counts: dict[str, dict[str, int]]


class ReviewItem(BaseModel):
    id: uuid.UUID
    entity_type: str
    entity_id: uuid.UUID
    entity_name: str = ""
    entity_email: str = ""
    contact_id: uuid.UUID
    contact_name: str = ""
    contact_email: str = ""
    method: str
    confidence: float
    reason: str
    status: str


class ReviewListResponse(BaseModel):
    items: list[ReviewItem] = Field(default_factory=list)
    total: int = 0


async def _item(session: SessionDep, review: PartyLinkReview) -> ReviewItem:
    entity = await parties._entity(session, review.entity_type, review.entity_id)
    name, email = parties.entity_label(review.entity_type, entity) if entity is not None else ("", "")
    contact = await session.get(Contact, review.contact_id)
    return ReviewItem(
        id=review.id,
        entity_type=review.entity_type,
        entity_id=review.entity_id,
        entity_name=name,
        entity_email=email,
        contact_id=review.contact_id,
        contact_name=contact_display_name(contact) if contact is not None else "",
        contact_email=(contact.primary_email or "") if contact is not None else "",
        method=review.method,
        confidence=review.confidence,
        reason=review.reason,
        status=review.status,
    )


@router.post("/backfill/", response_model=BackfillResponse, dependencies=[Depends(RequireRole("admin"))])
async def backfill_parties(
    body: BackfillRequest,
    user_id: CurrentUserId,
    session: SessionDep,
) -> BackfillResponse:
    """Link tender invitations, bids and portal accounts to contacts. Admin only, idempotent.

    A unique email or VAT match is linked; a name-only or ambiguous match goes to
    the review list. Contacts are never merged, changed or deleted.
    """
    unknown = set(body.entity_types) - set(parties.ENTITY_TYPES)
    if unknown:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"Unknown entity type: {sorted(unknown)}")
    counts = await parties.backfill(
        session, actor_id=str(user_id), entity_types=set(body.entity_types) or None, dry_run=body.dry_run
    )
    return BackfillResponse(dry_run=body.dry_run, counts=counts)


@router.get("/review/", response_model=ReviewListResponse)
async def list_party_reviews(
    user_id: CurrentUserId,
    session: SessionDep,
    review_status: str = Query(default="pending", alias="status", pattern="^(pending|confirmed|rejected)$"),
    _perm: None = Depends(RequirePermission("contacts.read")),
) -> ReviewListResponse:
    """Suggested links waiting for a person (admins see every owner's)."""
    owner = None if await _is_admin(session, str(user_id)) else str(user_id)
    reviews = await parties.list_reviews(session, owner_id=owner, status=review_status)
    items = [await _item(session, r) for r in reviews]
    return ReviewListResponse(items=items, total=len(items))


async def _decide(session: SessionDep, review_id: uuid.UUID, user_id: str, *, confirm: bool) -> ReviewItem:
    review = await session.get(PartyLinkReview, review_id)
    admin = await _is_admin(session, str(user_id))
    if review is None or (not admin and str(review.owner_id or "") != str(user_id)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Review item not found")
    if review.status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Review item already decided")
    await parties.decide_review(session, review, confirm=confirm, actor_id=str(user_id))
    return await _item(session, review)


@router.post("/review/{review_id}/confirm/", response_model=ReviewItem)
async def confirm_party_review(
    review_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("contacts.update")),
) -> ReviewItem:
    """Confirm a suggested link: the row is linked to the contact with confidence 1."""
    return await _decide(session, review_id, str(user_id), confirm=True)


@router.post("/review/{review_id}/reject/", response_model=ReviewItem)
async def reject_party_review(
    review_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("contacts.update")),
) -> ReviewItem:
    """Reject a suggested link; the pair is not offered again."""
    return await _decide(session, review_id, str(user_id), confirm=False)
