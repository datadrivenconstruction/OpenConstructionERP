# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""RFQ Bidding API routes.

Endpoints:
    GET    /                       - List RFQs (requires rfq.read + project access)
    POST   /                       - Create RFQ (requires rfq.create + project access)
    GET    /{id}                   - Get single RFQ (requires rfq.read + project access)
    PATCH  /{id}                   - Update RFQ (requires rfq.update + project access)
    DELETE /{id}                   - Delete RFQ (requires rfq.delete + project access)
    POST   /{id}/issue             - Issue RFQ (requires rfq.update + project access)
    GET    /{id}/validate          - Report RFQ findings for the issue or award stage
    GET    /{id}/lines             - List the scope lines quotes are priced against
    POST   /{id}/lines             - Add a scope line (draft RFQs only)
    PATCH  /{id}/lines/{line_id}   - Update a scope line (draft RFQs only)
    DELETE /{id}/lines/{line_id}   - Remove a scope line (draft RFQs only)
    GET    /{id}/comparison        - Quotes restated on one basis and ranked
    GET    /{id}/award             - The award decision record for this RFQ
    GET    /bids                   - List bids (requires rfq.read + project access via rfq_id)
    POST   /bids                   - Submit bid (requires rfq.create + project access)
    GET    /bids/{id}              - Get single bid (requires rfq.read + project access)
    POST   /bids/{id}/evaluate     - Evaluate bid (requires rfq.update + project access)
    POST   /bids/{id}/adjustments  - Record an inclusion, exclusion or allowance
    POST   /bids/{id}/withdraw     - Record that the supplier withdrew the quote
    POST   /bids/{id}/disqualify   - Rule a quote out of the ranking (award roles)
    POST   /bids/{id}/admit-late   - Admit a late quote into the ranking (award roles)
    POST   /bids/{id}/award        - Award bid (requires rfq.update + project access)
"""

import uuid
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status

from app.core.i18n import get_locale
from app.core.validation.messages import translate
from app.dependencies import CurrentUserId, CurrentUserPayload, RequirePermission, SessionDep
from app.modules.rfq_bidding.schemas import (
    BidAdjustmentCreate,
    BidAwardRequest,
    BidCreate,
    BidDecision,
    BidEvaluation,
    BidListResponse,
    ComparisonResponse,
    RFQAwardResponse,
    RFQBidResponse,
    RFQCreate,
    RFQLineCreate,
    RFQLineListResponse,
    RFQLineResponse,
    RFQLineUpdate,
    RFQListResponse,
    RFQResponse,
    RFQUpdate,
)
from app.modules.rfq_bidding.service import RFQService

router = APIRouter(tags=["rfq_bidding"])


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
            detail=translate("errors.project_not_found", locale=get_locale()),
        )
    if str(project.owner_id) != str(user_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=translate("errors.project_not_found", locale=get_locale()),
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
    rfq = await service.issue_rfq(
        rfq_id,
        actor_id=user_id,
        reason=(payload.get("reason") if isinstance(payload, dict) else None),
    )
    return RFQResponse.model_validate(rfq)


@router.get(
    "/{rfq_id}/validate/",
    dependencies=[Depends(RequirePermission("rfq.read"))],
)
async def validate_rfq(
    rfq_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    stage: str = Query(
        default="issue",
        description="Which question to ask: 'issue' (ready to publish) or 'award' (bids comparable)",
    ),
    service: RFQService = Depends(_get_service),
) -> dict[str, Any]:
    """Report what is wrong with an RFQ, before publishing or before awarding.

    Read-only: it changes nothing and refuses nothing. Both lifecycle steps run
    the same checks and record the findings, so this endpoint is where to look
    first rather than where the problem is discovered.
    """
    await _verify_rfq_access(session, rfq_id, user_id, payload)
    return await service.validate_rfq(rfq_id, stage=stage)


# ── Scope lines ─────────────────────────────────────────────────────────────


@router.get(
    "/{rfq_id}/lines/",
    response_model=RFQLineListResponse,
    dependencies=[Depends(RequirePermission("rfq.read"))],
)
async def list_rfq_lines(
    rfq_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: RFQService = Depends(_get_service),
) -> RFQLineListResponse:
    """List the scope lines suppliers are asked to price."""
    await _verify_rfq_access(session, rfq_id, user_id, payload)
    lines = await service.list_lines(rfq_id)
    return RFQLineListResponse(
        items=[RFQLineResponse.model_validate(line) for line in lines],
        total=len(lines),
    )


@router.post(
    "/{rfq_id}/lines/",
    response_model=RFQLineResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("rfq.update"))],
)
async def add_rfq_line(
    rfq_id: uuid.UUID,
    data: RFQLineCreate,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: RFQService = Depends(_get_service),
) -> RFQLineResponse:
    """Add one scope line. Allowed only while the RFQ is still a draft."""
    await _verify_rfq_access(session, rfq_id, user_id, payload)
    line = await service.add_line(rfq_id, data)
    return RFQLineResponse.model_validate(line)


@router.patch(
    "/{rfq_id}/lines/{line_id}",
    response_model=RFQLineResponse,
    dependencies=[Depends(RequirePermission("rfq.update"))],
)
async def update_rfq_line(
    rfq_id: uuid.UUID,
    line_id: uuid.UUID,
    data: RFQLineUpdate,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: RFQService = Depends(_get_service),
) -> RFQLineResponse:
    """Update one scope line. Allowed only while the RFQ is still a draft."""
    await _verify_rfq_access(session, rfq_id, user_id, payload)
    line = await service.update_line(rfq_id, line_id, data)
    return RFQLineResponse.model_validate(line)


@router.delete(
    "/{rfq_id}/lines/{line_id}",
    status_code=204,
    dependencies=[Depends(RequirePermission("rfq.update"))],
)
async def delete_rfq_line(
    rfq_id: uuid.UUID,
    line_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: RFQService = Depends(_get_service),
) -> None:
    """Remove one scope line. Allowed only while the RFQ is still a draft."""
    await _verify_rfq_access(session, rfq_id, user_id, payload)
    await service.delete_line(rfq_id, line_id)


# ── Comparison and award record ─────────────────────────────────────────────


@router.get(
    "/{rfq_id}/comparison/",
    response_model=ComparisonResponse,
    dependencies=[Depends(RequirePermission("rfq.read"))],
)
async def compare_rfq_bids(
    rfq_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: RFQService = Depends(_get_service),
) -> ComparisonResponse:
    """Restate every quote on the RFQ's basis and rank the ones that fit.

    Read-only. A quote that could not be restated - another currency with no
    rate recorded, a unit that does not convert, part of the scope unpriced,
    late and not admitted - appears under ``excluded`` with the reason, never
    silently ranked against quotes it is not comparable with.
    """
    await _verify_rfq_access(session, rfq_id, user_id, payload)
    rfq, result = await service.compare_bids(rfq_id)
    return ComparisonResponse(
        rfq_id=rfq.id,
        rfq_number=rfq.rfq_number,
        quote_gate=service.quote_gate_status(rfq),
        **result.as_dict(),
    )


@router.get(
    "/{rfq_id}/award/",
    response_model=RFQAwardResponse,
    dependencies=[Depends(RequirePermission("rfq.read"))],
)
async def get_rfq_award(
    rfq_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: RFQService = Depends(_get_service),
) -> RFQAwardResponse:
    """The award decision: who won, on what basis, and against which ranking."""
    await _verify_rfq_access(session, rfq_id, user_id, payload)
    award = await service.get_award(rfq_id)
    return RFQAwardResponse.model_validate(award)


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
        offset=offset,
        limit=limit,
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
    "/bids/{bid_id}/adjustments/",
    response_model=RFQBidResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("rfq.update"))],
)
async def add_bid_adjustment(
    bid_id: uuid.UUID,
    data: BidAdjustmentCreate,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: RFQService = Depends(_get_service),
) -> RFQBidResponse:
    """Record an inclusion, an exclusion or a buyer allowance on a quote.

    This is how a quote that left delivery out is brought level with one that
    priced it. Items marked as already included in the quote change nothing
    except what the comparison can show about each price.
    """
    await _verify_bid_access(session, bid_id, user_id, payload)
    bid = await service.add_adjustment(bid_id, data, actor_id=user_id)
    return RFQBidResponse.model_validate(bid)


@router.post(
    "/bids/{bid_id}/withdraw/",
    response_model=RFQBidResponse,
    dependencies=[Depends(RequirePermission("rfq.update"))],
)
async def withdraw_bid(
    bid_id: uuid.UUID,
    data: BidDecision,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: RFQService = Depends(_get_service),
) -> RFQBidResponse:
    """Record that the supplier withdrew its quote, with the reason given."""
    await _verify_bid_access(session, bid_id, user_id, payload)
    bid = await service.withdraw_bid(bid_id, reason=data.reason, actor_id=user_id)
    return RFQBidResponse.model_validate(bid)


@router.post(
    "/bids/{bid_id}/disqualify/",
    response_model=RFQBidResponse,
    dependencies=[Depends(RequirePermission("rfq.update"))],
)
async def disqualify_bid(
    bid_id: uuid.UUID,
    data: BidDecision,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: RFQService = Depends(_get_service),
) -> RFQBidResponse:
    """Rule a quote out of the ranking. Requires an award-level role."""
    await _verify_bid_access(session, bid_id, user_id, payload)
    bid = await service.disqualify_bid(
        bid_id,
        reason=data.reason,
        actor_id=user_id,
        actor_role=(payload.get("role") if isinstance(payload, dict) else None),
    )
    return RFQBidResponse.model_validate(bid)


@router.post(
    "/bids/{bid_id}/admit-late/",
    response_model=RFQBidResponse,
    dependencies=[Depends(RequirePermission("rfq.update"))],
)
async def admit_late_bid(
    bid_id: uuid.UUID,
    data: BidDecision,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    service: RFQService = Depends(_get_service),
) -> RFQBidResponse:
    """Admit a quote that arrived after the deadline into the ranking.

    Requires an award-level role and a written reason: admitting a late quote
    once the other prices are known is the most contestable step in the whole
    process, so it is signed rather than inferred.
    """
    await _verify_bid_access(session, bid_id, user_id, payload)
    bid = await service.admit_late_bid(
        bid_id,
        reason=data.reason,
        actor_id=user_id,
        actor_role=(payload.get("role") if isinstance(payload, dict) else None),
    )
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
    data: BidAwardRequest | None = Body(default=None),
    service: RFQService = Depends(_get_service),
) -> RFQBidResponse:
    """Award a bid. Verifies project access via parent RFQ AND requires
    admin / manager / owner role (matches FSM ``bids_received → awarded``
    ``required_roles=("admin", "manager")``). EDITORs with ``rfq.update``
    permission are intentionally rejected here.

    The quote must be one the comparison could put on the RFQ's basis; the
    ranked table it was taken from is stored with the award, and the reason in
    the optional body is stored beside it.
    """
    await _verify_bid_access(session, bid_id, user_id, payload)
    bid = await service.award_bid(
        bid_id,
        actor_id=user_id,
        actor_role=(payload.get("role") if isinstance(payload, dict) else None),
        reason=data.reason if data else None,
        gate_override_reason=data.gate_override_reason if data else None,
        po_number=data.po_number if data else None,
    )
    return RFQBidResponse.model_validate(bid)
