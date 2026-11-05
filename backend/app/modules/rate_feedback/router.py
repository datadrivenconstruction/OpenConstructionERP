# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Rate-feedback API, mounted at ``/api/v1/rate_feedback``.

GET  /proposals?status=pending      proposals awaiting a decision
POST /refresh                       recompute from closed projects
POST /proposals/{id}/confirm        apply to the cost item (estimator decides)
POST /proposals/{id}/reject         dismiss
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies import CurrentUserId, CurrentUserPayload, RequirePermission, SessionDep
from app.modules.rate_feedback.schemas import (
    ConfirmRequest,
    ProposalListResponse,
    ProposalResponse,
    RefreshRequest,
    RefreshResponse,
    RejectRequest,
)
from app.modules.rate_feedback.service import RateFeedbackService
from app.modules.rate_feedback.validators import RateFeedbackError

router = APIRouter()


def _http(exc: RateFeedbackError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message})


@router.get(
    "/proposals",
    response_model=ProposalListResponse,
    dependencies=[Depends(RequirePermission("rate_feedback.read"))],
)
async def list_proposals(
    session: SessionDep,
    status: str | None = Query(default="pending", pattern="^(pending|accepted|rejected|superseded|all)$"),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
) -> ProposalListResponse:
    """Proposals, the largest confidence-weighted change first."""
    return await RateFeedbackService(session).list_proposals(
        None if status == "all" else status, offset=offset, limit=limit
    )


@router.post(
    "/refresh",
    response_model=RefreshResponse,
    dependencies=[Depends(RequirePermission("rate_feedback.refresh"))],
)
async def refresh(
    session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload, body: RefreshRequest | None = None
) -> RefreshResponse:
    """Recompute proposals from the closed projects the caller can see."""
    is_admin = str(payload.get("role", "")) == "admin"
    return await RateFeedbackService(session).refresh(uuid.UUID(user_id), is_admin, body or RefreshRequest())


@router.post(
    "/proposals/{proposal_id}/confirm",
    response_model=ProposalResponse,
    dependencies=[Depends(RequirePermission("rate_feedback.confirm"))],
)
async def confirm(
    proposal_id: uuid.UUID, body: ConfirmRequest, session: SessionDep, user_id: CurrentUserId
) -> ProposalResponse:
    """Apply a proposal to the company cost database."""
    try:
        return await RateFeedbackService(session).confirm(proposal_id, uuid.UUID(user_id), body)
    except RateFeedbackError as exc:
        raise _http(exc) from exc


@router.post(
    "/proposals/{proposal_id}/reject",
    response_model=ProposalResponse,
    dependencies=[Depends(RequirePermission("rate_feedback.confirm"))],
)
async def reject(
    proposal_id: uuid.UUID, body: RejectRequest, session: SessionDep, user_id: CurrentUserId
) -> ProposalResponse:
    """Dismiss a proposal; the cost item stays as it is."""
    try:
        return await RateFeedbackService(session).reject(proposal_id, uuid.UUID(user_id), body.note)
    except RateFeedbackError as exc:
        raise _http(exc) from exc
