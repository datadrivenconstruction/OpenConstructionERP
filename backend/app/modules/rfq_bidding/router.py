"""RFQ Bidding API routes.

Endpoints:
    GET    /                       — List RFQs
    POST   /                       — Create RFQ (auth required)
    GET    /{id}                   — Get single RFQ
    PATCH  /{id}                   — Update RFQ (auth required)
    DELETE /{id}                   — Delete RFQ (auth required)
    POST   /{id}/issue             — Issue RFQ (auth required)
    GET    /bids                   — List bids
    POST   /bids                   — Submit bid (auth required)
    GET    /bids/{id}              — Get single bid
    POST   /bids/{id}/evaluate     — Evaluate bid (auth required)
    POST   /bids/{id}/award        — Award bid (auth required)
"""

import uuid

from fastapi import APIRouter, Depends, Query

from app.dependencies import CurrentUserId, SessionDep
from app.modules.rfq_bidding.schemas import (
    BidCreate,
    BidEvaluation,
    BidListResponse,
    RFQBidResponse,
    RFQCreate,
    RFQListResponse,
    RFQResponse,
    RFQUpdate,
)
from app.modules.rfq_bidding.service import RFQService

router = APIRouter()


def _get_service(session: SessionDep) -> RFQService:
    return RFQService(session)


# ── RFQs ────────────────────────────────────────────────────────────────────


@router.get("/", response_model=RFQListResponse)
async def list_rfqs(
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    project_id: uuid.UUID | None = Query(default=None),
    status: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    service: RFQService = Depends(_get_service),
) -> RFQListResponse:
    """List RFQs with optional filters."""
    items, total = await service.list_rfqs(
        project_id=project_id,
        rfq_status=status,
        offset=offset,
        limit=limit,
    )
    return RFQListResponse(
        items=[RFQResponse.model_validate(r) for r in items],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post("/", response_model=RFQResponse, status_code=201)
async def create_rfq(
    data: RFQCreate,
    user_id: CurrentUserId,
    service: RFQService = Depends(_get_service),
) -> RFQResponse:
    """Create a new RFQ."""
    rfq = await service.create_rfq(data, user_id=user_id)
    return RFQResponse.model_validate(rfq)


@router.get("/{rfq_id}", response_model=RFQResponse)
async def get_rfq(
    rfq_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: RFQService = Depends(_get_service),
) -> RFQResponse:
    """Get a single RFQ by ID."""
    rfq = await service.get_rfq(rfq_id)
    return RFQResponse.model_validate(rfq)


@router.patch("/{rfq_id}", response_model=RFQResponse)
async def update_rfq(
    rfq_id: uuid.UUID,
    data: RFQUpdate,
    user_id: CurrentUserId,
    service: RFQService = Depends(_get_service),
) -> RFQResponse:
    """Update an RFQ."""
    rfq = await service.update_rfq(rfq_id, data)
    return RFQResponse.model_validate(rfq)


@router.delete("/{rfq_id}", status_code=204)
async def delete_rfq(
    rfq_id: uuid.UUID,
    user_id: CurrentUserId,
    service: RFQService = Depends(_get_service),
) -> None:
    """Delete an RFQ and all its bids."""
    await service.delete_rfq(rfq_id)


@router.post("/{rfq_id}/issue", response_model=RFQResponse)
async def issue_rfq(
    rfq_id: uuid.UUID,
    user_id: CurrentUserId,
    service: RFQService = Depends(_get_service),
) -> RFQResponse:
    """Issue an RFQ to vendors."""
    rfq = await service.issue_rfq(rfq_id)
    return RFQResponse.model_validate(rfq)


# ── Bids ────────────────────────────────────────────────────────────────────


@router.get("/bids", response_model=BidListResponse)
async def list_bids(
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    rfq_id: uuid.UUID | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    service: RFQService = Depends(_get_service),
) -> BidListResponse:
    """List bids with optional RFQ filter."""
    items, total = await service.list_bids(rfq_id=rfq_id, limit=limit, offset=offset)
    return BidListResponse(
        items=[RFQBidResponse.model_validate(b) for b in items],
        total=total,
    )


@router.post("/bids", response_model=RFQBidResponse, status_code=201)
async def submit_bid(
    data: BidCreate,
    user_id: CurrentUserId,
    service: RFQService = Depends(_get_service),
) -> RFQBidResponse:
    """Submit a bid against an RFQ."""
    bid = await service.submit_bid(data, user_id=user_id)
    return RFQBidResponse.model_validate(bid)


@router.get("/bids/{bid_id}", response_model=RFQBidResponse)
async def get_bid(
    bid_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: RFQService = Depends(_get_service),
) -> RFQBidResponse:
    """Get a single bid by ID."""
    bid = await service.get_bid(bid_id)
    return RFQBidResponse.model_validate(bid)


@router.post("/bids/{bid_id}/evaluate", response_model=RFQBidResponse)
async def evaluate_bid(
    bid_id: uuid.UUID,
    data: BidEvaluation,
    user_id: CurrentUserId,
    service: RFQService = Depends(_get_service),
) -> RFQBidResponse:
    """Evaluate a bid (technical + commercial scoring)."""
    bid = await service.evaluate_bid(bid_id, data)
    return RFQBidResponse.model_validate(bid)


@router.post("/bids/{bid_id}/award", response_model=RFQBidResponse)
async def award_bid(
    bid_id: uuid.UUID,
    user_id: CurrentUserId,
    service: RFQService = Depends(_get_service),
) -> RFQBidResponse:
    """Award a bid and mark the RFQ as awarded."""
    bid = await service.award_bid(bid_id)
    return RFQBidResponse.model_validate(bid)
