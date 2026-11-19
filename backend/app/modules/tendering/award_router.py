# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Tendering routes for award terms, negotiation rounds and the bidder gate.

Included by ``router.py``. Guarded like the neighbouring package routes:
declared permission plus project access, and a sealed package keeps its bid
figures closed until it is opened. Changing terms or rounds and approving a
final offer are award decisions and need ``tendering.award``.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Response, status

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.tendering.award_schemas import (
    AwardPreview,
    AwardTermsIn,
    AwardTermsOut,
    BidderGate,
    RoundIn,
    RoundListResponse,
    RoundOut,
)
from app.modules.tendering.award_terms import AwardTermsService, bid_party, bidder_gate
from app.modules.tendering.sealed import SealedTenderService
from app.modules.tendering.service import TenderingService

router = APIRouter()


async def _package(session: SessionDep, package_id: uuid.UUID, user_id: str, what: str) -> Any:
    package = await TenderingService(session).get_package(package_id)
    await verify_project_access(package.project_id, user_id, session)
    await SealedTenderService(session).ensure_open(package_id, user_id=user_id, what=what)
    return package


@router.get("/packages/{package_id}/award-terms/", response_model=AwardTermsOut)
async def get_award_terms(
    package_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("tendering.read")),
) -> AwardTermsOut:
    """The stored award terms with the award they make, and the drafted contract's check once awarded."""
    await _package(session, package_id, user_id, "award_terms")
    return await AwardTermsService(session).get(package_id)


@router.put("/packages/{package_id}/award-terms/", response_model=AwardTermsOut)
async def save_award_terms(
    package_id: uuid.UUID,
    body: AwardTermsIn,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("tendering.award")),
) -> AwardTermsOut:
    """Store the award terms. Refused (409) once the package is decided."""
    await _package(session, package_id, user_id, "award_terms")
    return await AwardTermsService(session).save_terms(package_id, body, user_id)


@router.post("/packages/{package_id}/award-terms/preview/", response_model=AwardPreview)
async def preview_award_terms(
    package_id: uuid.UUID,
    body: AwardTermsIn,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("tendering.read")),
) -> AwardPreview:
    """The award these terms would make, without storing them: contract sum, lines, blockers."""
    await _package(session, package_id, user_id, "award_terms")
    return await AwardTermsService(session).preview(package_id, body)


@router.get("/packages/{package_id}/award-preview/", response_model=AwardPreview)
async def preview_bid_award(
    package_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    bid_id: uuid.UUID = Query(...),
    _perm: None = Depends(RequirePermission("tendering.read")),
) -> AwardPreview:
    """The award of a bid as it stands, with no terms agreed."""
    await _package(session, package_id, user_id, "award_terms")
    return await AwardTermsService(session).preview(package_id, None, bid_id=bid_id)


@router.get("/packages/{package_id}/rounds/", response_model=RoundListResponse)
async def list_rounds(
    package_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("tendering.read")),
) -> RoundListResponse:
    """Every negotiation round of the package, per bid in round order."""
    await _package(session, package_id, user_id, "negotiation_rounds")
    rows = await AwardTermsService(session).list_rounds(package_id)
    return RoundListResponse(items=rows, total=len(rows), limit=max(len(rows), 1))


@router.post("/packages/{package_id}/bids/{bid_id}/rounds/", response_model=RoundOut, status_code=201)
async def add_round(
    package_id: uuid.UUID,
    bid_id: uuid.UUID,
    body: RoundIn,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("tendering.award")),
) -> RoundOut:
    """Record a negotiated offer of a bidder as the next round."""
    await _package(session, package_id, user_id, "negotiation_rounds")
    return await AwardTermsService(session).add_round(package_id, bid_id, body, user_id)


@router.post("/packages/{package_id}/rounds/{round_id}/final/", response_model=RoundOut)
async def mark_round_final(
    package_id: uuid.UUID,
    round_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    final: bool = Query(default=True),
    _perm: None = Depends(RequirePermission("tendering.award")),
) -> RoundOut:
    """Mark the round as the bidder's final offer (unmarks its others); ``final=false`` takes the mark off."""
    await _package(session, package_id, user_id, "negotiation_rounds")
    return await AwardTermsService(session).mark_final(package_id, round_id, final=final)


@router.post("/packages/{package_id}/rounds/{round_id}/approve/", response_model=RoundOut)
async def approve_round(
    package_id: uuid.UUID,
    round_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("tendering.award")),
) -> RoundOut:
    """Approve the final offer. The commitment release matrix answers first and may refuse (409)."""
    await _package(session, package_id, user_id, "negotiation_rounds")
    return await AwardTermsService(session).approve_round(package_id, round_id, user_id)


@router.delete("/packages/{package_id}/rounds/{round_id}/", status_code=204)
async def delete_round(
    package_id: uuid.UUID,
    round_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("tendering.award")),
) -> Response:
    """Remove a round recorded by mistake while the package is still open."""
    await _package(session, package_id, user_id, "negotiation_rounds")
    await AwardTermsService(session).delete_round(package_id, round_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/packages/{package_id}/bids/{bid_id}/gate/", response_model=BidderGate)
async def bid_gate(
    package_id: uuid.UUID,
    bid_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("tendering.read")),
) -> BidderGate:
    """What the subcontractor directory says about the bid's firm, against the project's required certificates."""
    package = await _package(session, package_id, user_id, "bid_gate")
    service = AwardTermsService(session)
    bid = await service._bid(package, bid_id)
    sub_id, contact_id = bid_party(package, bid)
    return await bidder_gate(
        session, await service._project(package.project_id), subcontractor_id=sub_id, contact_id=contact_id
    )
