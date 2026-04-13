"""Submittals API routes.

Endpoints:
    GET    /                          - List submittals for a project
    POST   /                          - Create submittal
    GET    /{submittal_id}            - Get single submittal
    PATCH  /{submittal_id}            - Update submittal
    DELETE /{submittal_id}            - Delete submittal
    POST   /{submittal_id}/submit     - Move to submitted status
    POST   /{submittal_id}/review     - Review (approve/reject/revise)
    POST   /{submittal_id}/approve    - Final approval
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.rate_limiter import approval_limiter
from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.submittals.schemas import (
    SubmittalCreate,
    SubmittalResponse,
    SubmittalReviewRequest,
    SubmittalUpdate,
)
from app.modules.submittals.service import SubmittalService

router = APIRouter()
logger = logging.getLogger(__name__)


def _get_service(session: SessionDep) -> SubmittalService:
    return SubmittalService(session)


def _to_response(item: object) -> SubmittalResponse:
    return SubmittalResponse(
        id=item.id,  # type: ignore[attr-defined]
        project_id=item.project_id,  # type: ignore[attr-defined]
        submittal_number=item.submittal_number,  # type: ignore[attr-defined]
        title=item.title,  # type: ignore[attr-defined]
        spec_section=item.spec_section,  # type: ignore[attr-defined]
        submittal_type=item.submittal_type,  # type: ignore[attr-defined]
        status=item.status,  # type: ignore[attr-defined]
        ball_in_court=str(item.ball_in_court) if item.ball_in_court else None,  # type: ignore[attr-defined]
        current_revision=item.current_revision,  # type: ignore[attr-defined]
        submitted_by_org=item.submitted_by_org,  # type: ignore[attr-defined]
        reviewer_id=str(item.reviewer_id) if item.reviewer_id else None,  # type: ignore[attr-defined]
        approver_id=str(item.approver_id) if item.approver_id else None,  # type: ignore[attr-defined]
        date_submitted=item.date_submitted,  # type: ignore[attr-defined]
        date_required=item.date_required,  # type: ignore[attr-defined]
        date_returned=item.date_returned,  # type: ignore[attr-defined]
        linked_boq_item_ids=item.linked_boq_item_ids or [],  # type: ignore[attr-defined]
        created_by=item.created_by,  # type: ignore[attr-defined]
        metadata=getattr(item, "metadata_", {}),
        created_at=item.created_at,  # type: ignore[attr-defined]
        updated_at=item.updated_at,  # type: ignore[attr-defined]
    )


@router.get(
    "/",
    response_model=list[SubmittalResponse],
    dependencies=[Depends(RequirePermission("submittals.read"))],
)
async def list_submittals(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status"),
    type_filter: str | None = Query(default=None, alias="type"),
    service: SubmittalService = Depends(_get_service),
) -> list[SubmittalResponse]:
    await verify_project_access(project_id, user_id, session)
    submittals, _ = await service.list_submittals(
        project_id,
        offset=offset,
        limit=limit,
        status_filter=status_filter,
        submittal_type=type_filter,
    )
    return [_to_response(s) for s in submittals]


@router.post("/", response_model=SubmittalResponse, status_code=201)
async def create_submittal(
    data: SubmittalCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("submittals.create")),
    service: SubmittalService = Depends(_get_service),
) -> SubmittalResponse:
    await verify_project_access(data.project_id, user_id, session)
    submittal = await service.create_submittal(data, user_id=user_id)
    return _to_response(submittal)


@router.get(
    "/{submittal_id}",
    response_model=SubmittalResponse,
    dependencies=[Depends(RequirePermission("submittals.read"))],
)
async def get_submittal(
    submittal_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: SubmittalService = Depends(_get_service),
) -> SubmittalResponse:
    submittal = await service.get_submittal(submittal_id)
    return _to_response(submittal)


@router.patch("/{submittal_id}", response_model=SubmittalResponse)
async def update_submittal(
    submittal_id: uuid.UUID,
    data: SubmittalUpdate,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("submittals.update")),
    service: SubmittalService = Depends(_get_service),
) -> SubmittalResponse:
    submittal = await service.update_submittal(submittal_id, data)
    return _to_response(submittal)


@router.delete("/{submittal_id}", status_code=204)
async def delete_submittal(
    submittal_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("submittals.delete")),
    service: SubmittalService = Depends(_get_service),
) -> None:
    await service.delete_submittal(submittal_id)


@router.post("/{submittal_id}/submit/", response_model=SubmittalResponse)
async def submit_submittal(
    submittal_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("submittals.update")),
    service: SubmittalService = Depends(_get_service),
) -> SubmittalResponse:
    """Move a submittal from draft to submitted."""
    submittal = await service.submit_submittal(submittal_id)
    return _to_response(submittal)


@router.post("/{submittal_id}/review/", response_model=SubmittalResponse)
async def review_submittal(
    submittal_id: uuid.UUID,
    body: SubmittalReviewRequest,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("submittals.update")),
    service: SubmittalService = Depends(_get_service),
) -> SubmittalResponse:
    """Review a submittal (approve, reject, revise and resubmit, etc.)."""
    submittal = await service.review_submittal(submittal_id, body.status, reviewer_id=user_id)
    return _to_response(submittal)


@router.post("/{submittal_id}/approve/", response_model=SubmittalResponse)
async def approve_submittal(
    submittal_id: uuid.UUID,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("submittals.update")),
    service: SubmittalService = Depends(_get_service),
) -> SubmittalResponse:
    """Final approval of a submittal."""
    allowed, _ = approval_limiter.is_allowed(str(user_id))
    if not allowed:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Rate limit exceeded. Try again later.")
    submittal = await service.approve_submittal(submittal_id, approver_id=user_id)
    return _to_response(submittal)
