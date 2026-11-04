# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Bid / no-bid API routes (mounted at ``/api/v1/bid-no-bid``).

Every handler checks project access first, then the module permission. Every edit answers with the whole
recomputed scorecard.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.bid_no_bid.models import BidNoBidScorecard
from app.modules.bid_no_bid.schemas import DecideRequest, LedgerOut, OutcomeRequest, ScorecardOut, ScorecardUpdate
from app.modules.bid_no_bid.service import BidNoBidService

router = APIRouter(tags=["bid_no_bid"])
_READ = Depends(RequirePermission("bid_no_bid.read"))
_WRITE = Depends(RequirePermission("bid_no_bid.write"))
_DECIDE = Depends(RequirePermission("bid_no_bid.decide"))


async def _load(card_id: uuid.UUID, session: SessionDep, user_id: str) -> tuple[BidNoBidService, BidNoBidScorecard]:
    svc = BidNoBidService(session)
    card = await svc.card(card_id)
    await verify_project_access(card.project_id, user_id, session)
    return svc, card


async def _out(svc: BidNoBidService, card: BidNoBidScorecard) -> ScorecardOut:
    await svc.session.flush()
    return ScorecardOut.model_validate(await svc.view(card))


@router.get("/tenders/{tender_id}/scorecard", response_model=ScorecardOut, dependencies=[_READ])
async def open_scorecard(tender_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> ScorecardOut:
    svc = BidNoBidService(session)
    tender = await svc.tender(tender_id)
    await verify_project_access(tender.project_id, user_id, session)
    return await _out(svc, await svc.open_card(tender_id, user_id))


@router.patch("/scorecards/{card_id}", response_model=ScorecardOut, dependencies=[_WRITE])
async def update_scorecard(
    card_id: uuid.UUID, body: ScorecardUpdate, session: SessionDep, user_id: CurrentUserId
) -> ScorecardOut:
    svc, card = await _load(card_id, session, user_id)
    await svc.update(card, body, user_id)
    return await _out(svc, card)


@router.post("/scorecards/{card_id}/decision", response_model=ScorecardOut, dependencies=[_DECIDE])
async def record_decision(
    card_id: uuid.UUID, body: DecideRequest, session: SessionDep, user_id: CurrentUserId
) -> ScorecardOut:
    svc, card = await _load(card_id, session, user_id)
    await svc.decide(card, body, user_id)
    return await _out(svc, card)


@router.put("/scorecards/{card_id}/outcome", response_model=ScorecardOut, dependencies=[_DECIDE])
async def record_outcome(
    card_id: uuid.UUID, body: OutcomeRequest, session: SessionDep, user_id: CurrentUserId
) -> ScorecardOut:
    svc, card = await _load(card_id, session, user_id)
    await svc.set_outcome(card, body, user_id)
    return await _out(svc, card)


@router.get("/ledger", response_model=LedgerOut, dependencies=[_READ])
async def win_loss_ledger(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> LedgerOut:
    await verify_project_access(project_id, user_id, session)
    return LedgerOut.model_validate(await BidNoBidService(session).ledger(project_id))
