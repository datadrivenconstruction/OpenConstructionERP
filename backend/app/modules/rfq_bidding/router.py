"""RFQ Bidding API routes.

Endpoints:
    GET    /                       — List RFQs (requires rfq.read + project access)
    POST   /                       — Create RFQ (requires rfq.create + project access)
    GET    /{id}                   — Get single RFQ (requires rfq.read + project access)
    PATCH  /{id}                   — Update RFQ (requires rfq.update + project access)
    DELETE /{id}                   — Delete RFQ (requires rfq.delete + project access)
    POST   /{id}/issue             — Issue RFQ (requires rfq.update + project access)
    GET    /bids                   — List bids (requires rfq.read + project access via rfq_id)
    POST   /bids                   — Submit bid (requires rfq.create + project access)
    GET    /bids/{id}              — Get single bid (requires rfq.read + project access)
    POST   /bids/{id}/evaluate     — Evaluate bid (requires rfq.update + project access)
    POST   /bids/{id}/award        — Award bid (requires rfq.update + project access)
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import CurrentUserId, CurrentUserPayload, RequirePermission, SessionDep
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


async def _verify_project_access(
    session: SessionDep,
    project_id: uuid.UUID,
    user_id: str,
    payload: dict | None = None,
) -> None:
    """Verify the current user owns (or is admin on) the given project.

    Adapted from ``erp_chat.tools._require_project_access``. Central
    choke-point: every project-scoped RFQ endpoint must call this.
    """
    if payload and payload.get("role") == "admin":
        return

    from app.modules.projects.repository import ProjectRepository

    proj_repo = ProjectRepository(session)
    project = await proj_repo.get_by_id(project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    if str(project.owner_id) != str(user_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )


async def _verify_rfq_access(
    session: SessionDep,
    rfq_id: uuid.UUID,
    user_id: str,
    payload: dict | None = None,
) -> "object":
    """Load an RFQ and verify the user has access to its project.

    Returns the loaded RFQ for reuse by callers.
    """
    if payload and payload.get("role") == "admin":
        # Still need to load the RFQ so we can return it; 404 if missing.
        from app.modules.rfq_bidding.repository import RFQRepository

        rfq = await RFQRepository(session).get(rfq_id)
        if rfq is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="RFQ not found")
        return rfq

    from app.modules.rfq_bidding.repository import RFQRepository

    rfq = await RFQRepository(session).get(rfq_id)
    if rfq is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="RFQ not found")
    await _verify_project_access(session, rfq.project_id, user_id, payload)
    return rfq


async def _verify_bid_access(
    session: SessionDep,
    bid_id: uuid.UUID,
    user_id: str,
    payload: dict | None = None,
) -> "object":
    """Load a bid and verify project access via its parent RFQ."""
    from app.modules.rfq_bidding.repository import RFQBidRepository

    bid = await RFQBidRepository(session).get(bid_id)
    if bid is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bid not found")
    await _verify_rfq_access(session, bid.rfq_id, user_id, payload)
    return bid


# ── RFQs ────────────────────────────────────────────────────────────────────


@router.get(
    "/",
    response_model=RFQListResponse,
    dependencies=[Depends(RequirePermission("rfq.read"))],
)
async def list_rfqs(
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    project_id: uuid.UUID = Query(..., description="Filter by project (required)"),
    status: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    service: RFQService = Depends(_get_service),
) -> RFQListResponse:
    """List RFQs for a project. Project access is enforced."""
    await _verify_project_access(session, project_id, user_id, payload)
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


@router.post(
    "/",
    response_model=RFQResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("rfq.create"))],
)
async def create_rfq(
    data: RFQCreate,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: RFQService = Depends(_get_service),
) -> RFQResponse:
    """Create a new RFQ. Verifies project ownership."""
    await _verify_project_access(session, data.project_id, user_id, payload)
    rfq = await service.create_rfq(data, user_id=user_id)
    return RFQResponse.model_validate(rfq)


@router.get(
    "/{rfq_id}",
    response_model=RFQResponse,
    dependencies=[Depends(RequirePermission("rfq.read"))],
)
async def get_rfq(
    rfq_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: RFQService = Depends(_get_service),
) -> RFQResponse:
    """Get a single RFQ by ID. Verifies project ownership."""
    await _verify_rfq_access(session, rfq_id, user_id, payload)
    rfq = await service.get_rfq(rfq_id)
    return RFQResponse.model_validate(rfq)


@router.patch(
    "/{rfq_id}",
    response_model=RFQResponse,
    dependencies=[Depends(RequirePermission("rfq.update"))],
)
async def update_rfq(
    rfq_id: uuid.UUID,
    data: RFQUpdate,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: RFQService = Depends(_get_service),
) -> RFQResponse:
    """Update an RFQ. Verifies project ownership."""
    await _verify_rfq_access(session, rfq_id, user_id, payload)
    rfq = await service.update_rfq(rfq_id, data)
    return RFQResponse.model_validate(rfq)


@router.delete(
    "/{rfq_id}",
    status_code=204,
    dependencies=[Depends(RequirePermission("rfq.delete"))],
)
async def delete_rfq(
    rfq_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: RFQService = Depends(_get_service),
) -> None:
    """Delete an RFQ and all its bids. Verifies project ownership."""
    await _verify_rfq_access(session, rfq_id, user_id, payload)
    await service.delete_rfq(rfq_id)


@router.post(
    "/{rfq_id}/issue/",
    response_model=RFQResponse,
    dependencies=[Depends(RequirePermission("rfq.update"))],
)
async def issue_rfq(
    rfq_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: RFQService = Depends(_get_service),
) -> RFQResponse:
    """Issue an RFQ to vendors. Verifies project ownership."""
    await _verify_rfq_access(session, rfq_id, user_id, payload)
    rfq = await service.issue_rfq(rfq_id)
    return RFQResponse.model_validate(rfq)


# ── Bids ────────────────────────────────────────────────────────────────────


@router.get(
    "/bids/",
    response_model=BidListResponse,
    dependencies=[Depends(RequirePermission("rfq.read"))],
)
async def list_bids(
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    rfq_id: uuid.UUID = Query(..., description="Filter by RFQ (required)"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    service: RFQService = Depends(_get_service),
) -> BidListResponse:
    """List bids for a specific RFQ. Project access is enforced via the RFQ."""
    await _verify_rfq_access(session, rfq_id, user_id, payload)
    items, total = await service.list_bids(rfq_id=rfq_id, limit=limit, offset=offset)
    return BidListResponse(
        items=[RFQBidResponse.model_validate(b) for b in items],
        total=total,
    )


@router.post(
    "/bids/",
    response_model=RFQBidResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("rfq.create"))],
)
async def submit_bid(
    data: BidCreate,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: RFQService = Depends(_get_service),
) -> RFQBidResponse:
    """Submit a bid against an RFQ. Verifies project access via the RFQ."""
    await _verify_rfq_access(session, data.rfq_id, user_id, payload)
    bid = await service.submit_bid(data, user_id=user_id)
    return RFQBidResponse.model_validate(bid)


@router.get(
    "/bids/{bid_id}",
    response_model=RFQBidResponse,
    dependencies=[Depends(RequirePermission("rfq.read"))],
)
async def get_bid(
    bid_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: RFQService = Depends(_get_service),
) -> RFQBidResponse:
    """Get a single bid by ID. Verifies project access via parent RFQ."""
    await _verify_bid_access(session, bid_id, user_id, payload)
    bid = await service.get_bid(bid_id)
    return RFQBidResponse.model_validate(bid)


@router.post(
    "/bids/{bid_id}/evaluate/",
    response_model=RFQBidResponse,
    dependencies=[Depends(RequirePermission("rfq.update"))],
)
async def evaluate_bid(
    bid_id: uuid.UUID,
    data: BidEvaluation,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: RFQService = Depends(_get_service),
) -> RFQBidResponse:
    """Evaluate a bid. Verifies project access via parent RFQ."""
    await _verify_bid_access(session, bid_id, user_id, payload)
    bid = await service.evaluate_bid(bid_id, data)
    return RFQBidResponse.model_validate(bid)


@router.post(
    "/bids/{bid_id}/award/",
    response_model=RFQBidResponse,
    dependencies=[Depends(RequirePermission("rfq.update"))],
)
async def award_bid(
    bid_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: RFQService = Depends(_get_service),
) -> RFQBidResponse:
    """Award a bid. Verifies project access via parent RFQ."""
    await _verify_bid_access(session, bid_id, user_id, payload)
    bid = await service.award_bid(bid_id)
    return RFQBidResponse.model_validate(bid)
