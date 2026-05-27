"""‌⁠‍Bid Management API routes.

All routes are mounted at ``/api/v1/bid-management/`` and gated by
:class:`RequirePermission` ("bid_management.*"). Internal cross-module
references (project_id, tender_id, contract_template_ref) are plain
UUID / string types — no FK constraints across modules.

Every endpoint enforces :func:`verify_project_access` so users cannot
read/mutate bid data belonging to projects they don't own. The chain is:

    line_item / invitation / bidder / qa / comparison / award / rejection
        → BidPackage.package_id → BidPackage.project_id
    submission → BidInvitation.invitation_id → BidPackage
    submission_line → BidSubmission.submission_id → BidInvitation → BidPackage
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.i18n import get_locale
from app.core.validation.messages import translate
from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.bid_management.models import (
    BidAward,
    BidComparison,
    Bidder,
    BidInvitation,
    BidPackage,
    BidPackageLineItem,
    BidQA,
    BidRejection,
    BidSubmission,
    BidSubmissionLine,
)
from app.modules.bid_management.schemas import (
    BidAwardCreate,
    BidAwardResponse,
    BidAwardUpdate,
    BidComparisonCreate,
    BidComparisonResponse,
    BidComparisonUpdate,
    BidderCreate,
    BidderDisqualify,
    BidderQABoardResponse,
    BidderResponse,
    BidderUpdate,
    BidInvitationCreate,
    BidInvitationResponse,
    BidInvitationUpdate,
    BidLevelingResponse,
    BidPackageCreate,
    BidPackageDashboard,
    BidPackageLineItemBulkCreate,
    BidPackageLineItemCreate,
    BidPackageLineItemResponse,
    BidPackageLineItemUpdate,
    BidPackageResponse,
    BidPackageUpdate,
    BidQAAnswer,
    BidQACreate,
    BidQAResponse,
    BidQAUpdate,
    BidRejectionCreate,
    BidRejectionResponse,
    BidRejectionUpdate,
    BidSubmissionCreate,
    BidSubmissionLineBulkCreate,
    BidSubmissionLineCreate,
    BidSubmissionLineResponse,
    BidSubmissionLineUpdate,
    BidSubmissionResponse,
    BidSubmissionUpdate,
    InvitationEmailDispatchRequest,
    InvitationEmailDispatchResponse,
    LevelingMatrixResponse,
    LevelingTableResponse,
    SubcontractorScorecardCreate,
    SubcontractorScorecardResponse,
    SubmissionAnalyticsResponse,
)
from app.modules.bid_management.service import BidManagementService

router = APIRouter()
logger = logging.getLogger(__name__)


def _get_service(session: SessionDep) -> BidManagementService:
    return BidManagementService(session)


# ── access-guard helpers ──────────────────────────────────────────────────


async def _verify_package_access(
    session,
    package_id: uuid.UUID,
    user_id: str,
) -> BidPackage:
    pkg = await session.get(BidPackage, package_id)
    if pkg is None:
        raise HTTPException(status_code=404, detail="Bid package not found")
    await verify_project_access(pkg.project_id, user_id, session)
    return pkg


async def _verify_invitation_access(
    session,
    invitation_id: uuid.UUID,
    user_id: str,
) -> BidInvitation:
    inv = await session.get(BidInvitation, invitation_id)
    if inv is None:
        raise HTTPException(status_code=404, detail=translate("errors.invitation_not_found", locale=get_locale()))
    await _verify_package_access(session, inv.package_id, user_id)
    return inv


async def _verify_submission_access(
    session,
    submission_id: uuid.UUID,
    user_id: str,
) -> BidSubmission:
    sub = await session.get(BidSubmission, submission_id)
    if sub is None:
        raise HTTPException(status_code=404, detail=translate("errors.submission_not_found", locale=get_locale()))
    await _verify_invitation_access(session, sub.invitation_id, user_id)
    return sub


async def _verify_comparison_access(
    session,
    comparison_id: uuid.UUID,
    user_id: str,
) -> BidComparison:
    cmp_ = await session.get(BidComparison, comparison_id)
    if cmp_ is None:
        raise HTTPException(status_code=404, detail="Comparison not found")
    await _verify_package_access(session, cmp_.package_id, user_id)
    return cmp_


# ── Packages ───────────────────────────────────────────────────────────────


@router.get("/bid-packages/", response_model=list[BidPackageResponse])
async def list_packages(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    status_filter: str | None = Query(default=None, alias="status"),
    _perm: None = Depends(RequirePermission("bid_management.read")),
) -> list[BidPackageResponse]:
    await verify_project_access(project_id, user_id, session)
    svc = BidManagementService(session)
    rows, _total = await svc.list_packages(project_id, offset=offset, limit=limit, status_filter=status_filter)
    return [BidPackageResponse.model_validate(r) for r in rows]


@router.post("/bid-packages/", response_model=BidPackageResponse, status_code=201)
async def create_package(
    data: BidPackageCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("bid_management.create")),
) -> BidPackageResponse:
    await verify_project_access(data.project_id, user_id, session)
    svc = BidManagementService(session)
    pkg = await svc.create_package(data, user_id=user_id)
    return BidPackageResponse.model_validate(pkg)


@router.get("/bid-packages/{package_id}", response_model=BidPackageResponse)
async def get_package(
    package_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bid_management.read")),
) -> BidPackageResponse:
    await _verify_package_access(session, package_id, user_id)
    svc = BidManagementService(session)
    pkg = await svc.get_package(package_id)
    return BidPackageResponse.model_validate(pkg)


@router.patch("/bid-packages/{package_id}", response_model=BidPackageResponse)
async def update_package(
    package_id: uuid.UUID,
    data: BidPackageUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bid_management.update")),
) -> BidPackageResponse:
    await _verify_package_access(session, package_id, user_id)
    svc = BidManagementService(session)
    pkg = await svc.update_package(package_id, data)
    return BidPackageResponse.model_validate(pkg)


@router.delete("/bid-packages/{package_id}", status_code=204)
async def delete_package(
    package_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bid_management.delete")),
) -> None:
    await _verify_package_access(session, package_id, user_id)
    svc = BidManagementService(session)
    await svc.delete_package(package_id)


@router.post("/bid-packages/{package_id}/publish", response_model=BidPackageResponse)
async def publish_package(
    package_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bid_management.publish")),
) -> BidPackageResponse:
    await _verify_package_access(session, package_id, user_id)
    svc = BidManagementService(session)
    pkg = await svc.publish_package(package_id, user_id=user_id)
    return BidPackageResponse.model_validate(pkg)


@router.post("/bid-packages/{package_id}/open-bids", response_model=BidPackageResponse)
async def open_bids(
    package_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bid_management.open_bids")),
) -> BidPackageResponse:
    await _verify_package_access(session, package_id, user_id)
    svc = BidManagementService(session)
    pkg = await svc.open_bids(package_id)
    return BidPackageResponse.model_validate(pkg)


@router.post("/bid-packages/{package_id}/close", response_model=BidPackageResponse)
async def close_package(
    package_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bid_management.update")),
) -> BidPackageResponse:
    await _verify_package_access(session, package_id, user_id)
    svc = BidManagementService(session)
    pkg = await svc.close_package(package_id)
    return BidPackageResponse.model_validate(pkg)


@router.post("/bid-packages/{package_id}/cancel", response_model=BidPackageResponse)
async def cancel_package(
    package_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    reason: str = Query(default=""),
    _perm: None = Depends(RequirePermission("bid_management.cancel")),
) -> BidPackageResponse:
    await _verify_package_access(session, package_id, user_id)
    svc = BidManagementService(session)
    pkg = await svc.cancel_package(package_id, reason=reason)
    return BidPackageResponse.model_validate(pkg)


@router.post("/bid-packages/{package_id}/award", response_model=BidAwardResponse)
async def award_package(
    package_id: uuid.UUID,
    data: BidAwardCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bid_management.award")),
) -> BidAwardResponse:
    await _verify_package_access(session, package_id, user_id)
    svc = BidManagementService(session)
    award = await svc.award_package(package_id, data, user_id=user_id)
    return BidAwardResponse.model_validate(award)


@router.get("/bid-packages/{package_id}/dashboard", response_model=BidPackageDashboard)
async def package_dashboard(
    package_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bid_management.read")),
) -> BidPackageDashboard:
    await _verify_package_access(session, package_id, user_id)
    svc = BidManagementService(session)
    return BidPackageDashboard(**(await svc.package_dashboard(package_id)))


@router.get("/bid-packages/{package_id}/analytics", response_model=SubmissionAnalyticsResponse)
async def package_analytics(
    package_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bid_management.read")),
) -> SubmissionAnalyticsResponse:
    await _verify_package_access(session, package_id, user_id)
    svc = BidManagementService(session)
    return await svc.submission_analytics(package_id)


@router.get(
    "/bid-packages/{package_id}/leveling-matrix",
    response_model=LevelingMatrixResponse,
)
async def package_leveling_matrix(
    package_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bid_management.read")),
) -> LevelingMatrixResponse:
    """‌⁠‍Line-level side-by-side bid leveling matrix for a package."""
    await _verify_package_access(session, package_id, user_id)
    svc = BidManagementService(session)
    matrix = await svc.leveling_matrix(package_id)
    return LevelingMatrixResponse.model_validate(matrix)


@router.get(
    "/bid-packages/{package_id}/qa-board",
    response_model=BidderQABoardResponse,
)
async def package_qa_board(
    package_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    bidder_id: uuid.UUID | None = Query(default=None),
    _perm: None = Depends(RequirePermission("bid_management.read")),
) -> BidderQABoardResponse:
    """‌⁠‍Aconex-style Q&A board filtered to one bidder (or all when owner)."""
    await _verify_package_access(session, package_id, user_id)
    svc = BidManagementService(session)
    board = await svc.qa_board_for_bidder(package_id, bidder_id)
    return BidderQABoardResponse.model_validate(board)


@router.post(
    "/bid-packages/{package_id}/send-invitations",
    response_model=InvitationEmailDispatchResponse,
)
async def dispatch_package_invitations(
    package_id: uuid.UUID,
    payload: InvitationEmailDispatchRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bid_management.update")),
) -> InvitationEmailDispatchResponse:
    """Render and dispatch invitation emails for a bid package."""
    await _verify_package_access(session, package_id, user_id)
    svc = BidManagementService(session)
    templates = [t.model_dump() for t in payload.templates]
    result = await svc.dispatch_invitation_emails(
        package_id,
        templates=templates,
        invitation_ids=payload.invitation_ids,
        sender_name=payload.sender_name,
        sender_email=payload.sender_email,
    )
    return InvitationEmailDispatchResponse.model_validate(result)


@router.post(
    "/bid-packages/{package_id}/scorecards",
    response_model=SubcontractorScorecardResponse,
    status_code=201,
)
async def record_subcontractor_scorecard(
    package_id: uuid.UUID,
    payload: SubcontractorScorecardCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bid_management.record_scorecard")),
) -> SubcontractorScorecardResponse:
    """Capture a post-award subcontractor performance scorecard."""
    await _verify_package_access(session, package_id, user_id)
    svc = BidManagementService(session)
    result = await svc.record_subcontractor_scorecard(
        package_id,
        payload.bidder_id,
        on_time_score=payload.on_time_score,
        quality_score=payload.quality_score,
        safety_score=payload.safety_score,
        commercial_score=payload.commercial_score,
        notes=payload.notes,
    )
    return SubcontractorScorecardResponse.model_validate(result)


# ── Lines ─────────────────────────────────────────────────────────────────


@router.get(
    "/bid-package-line-items/",
    response_model=list[BidPackageLineItemResponse],
)
async def list_line_items(
    session: SessionDep,
    user_id: CurrentUserId,
    package_id: uuid.UUID = Query(...),
    _perm: None = Depends(RequirePermission("bid_management.read")),
) -> list[BidPackageLineItemResponse]:
    await _verify_package_access(session, package_id, user_id)
    svc = BidManagementService(session)
    rows = await svc.line_repo.list_for_package(package_id)
    return [BidPackageLineItemResponse.model_validate(r) for r in rows]


@router.post(
    "/bid-package-line-items/",
    response_model=BidPackageLineItemResponse,
    status_code=201,
)
async def create_line_item(
    data: BidPackageLineItemCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bid_management.create")),
) -> BidPackageLineItemResponse:
    await _verify_package_access(session, data.package_id, user_id)
    svc = BidManagementService(session)
    line = await svc.create_line(data)
    return BidPackageLineItemResponse.model_validate(line)


@router.post(
    "/bid-packages/{package_id}/lines/bulk",
    response_model=list[BidPackageLineItemResponse],
)
async def bulk_create_lines(
    package_id: uuid.UUID,
    data: BidPackageLineItemBulkCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bid_management.create")),
) -> list[BidPackageLineItemResponse]:
    await _verify_package_access(session, package_id, user_id)
    svc = BidManagementService(session)
    rows = await svc.bulk_create_lines(package_id, data.items)
    return [BidPackageLineItemResponse.model_validate(r) for r in rows]


@router.patch("/bid-package-line-items/{line_id}", response_model=BidPackageLineItemResponse)
async def update_line_item(
    line_id: uuid.UUID,
    data: BidPackageLineItemUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bid_management.update")),
) -> BidPackageLineItemResponse:
    line_row = await session.get(BidPackageLineItem, line_id)
    if line_row is None:
        raise HTTPException(status_code=404, detail="Line item not found")
    await _verify_package_access(session, line_row.package_id, user_id)
    svc = BidManagementService(session)
    line = await svc.update_line(line_id, data)
    return BidPackageLineItemResponse.model_validate(line)


@router.delete("/bid-package-line-items/{line_id}", status_code=204)
async def delete_line_item(
    line_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bid_management.delete")),
) -> None:
    line_row = await session.get(BidPackageLineItem, line_id)
    if line_row is None:
        raise HTTPException(status_code=404, detail="Line item not found")
    await _verify_package_access(session, line_row.package_id, user_id)
    svc = BidManagementService(session)
    await svc.delete_line(line_id)


# ── Bidders ───────────────────────────────────────────────────────────────


@router.get("/bidders/", response_model=list[BidderResponse])
async def list_bidders(
    session: SessionDep,
    user_id: CurrentUserId,
    package_id: uuid.UUID = Query(...),
    _perm: None = Depends(RequirePermission("bid_management.read")),
) -> list[BidderResponse]:
    await _verify_package_access(session, package_id, user_id)
    svc = BidManagementService(session)
    rows = await svc.bidder_repo.list_for_package(package_id)
    return [BidderResponse.model_validate(r) for r in rows]


@router.post("/bidders/", response_model=BidderResponse, status_code=201)
async def create_bidder(
    data: BidderCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bid_management.create")),
) -> BidderResponse:
    await _verify_package_access(session, data.package_id, user_id)
    svc = BidManagementService(session)
    bidder = await svc.create_bidder(data)
    return BidderResponse.model_validate(bidder)


@router.patch("/bidders/{bidder_id}", response_model=BidderResponse)
async def update_bidder(
    bidder_id: uuid.UUID,
    data: BidderUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bid_management.update")),
) -> BidderResponse:
    bidder_row = await session.get(Bidder, bidder_id)
    if bidder_row is None:
        raise HTTPException(status_code=404, detail=translate("errors.bidder_not_found", locale=get_locale()))
    await _verify_package_access(session, bidder_row.package_id, user_id)
    svc = BidManagementService(session)
    bidder = await svc.update_bidder(bidder_id, data)
    return BidderResponse.model_validate(bidder)


@router.delete("/bidders/{bidder_id}", status_code=204)
async def delete_bidder(
    bidder_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bid_management.delete")),
) -> None:
    bidder_row = await session.get(Bidder, bidder_id)
    if bidder_row is None:
        raise HTTPException(status_code=404, detail=translate("errors.bidder_not_found", locale=get_locale()))
    await _verify_package_access(session, bidder_row.package_id, user_id)
    svc = BidManagementService(session)
    await svc.delete_bidder(bidder_id)


@router.post("/bidders/{bidder_id}/disqualify", response_model=BidderResponse)
async def disqualify_bidder(
    bidder_id: uuid.UUID,
    data: BidderDisqualify,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bid_management.disqualify_bidder")),
) -> BidderResponse:
    bidder_row = await session.get(Bidder, bidder_id)
    if bidder_row is None:
        raise HTTPException(status_code=404, detail=translate("errors.bidder_not_found", locale=get_locale()))
    await _verify_package_access(session, bidder_row.package_id, user_id)
    svc = BidManagementService(session)
    bidder = await svc.disqualify_bidder(bidder_id, data.reason)
    return BidderResponse.model_validate(bidder)


# ── Invitations ───────────────────────────────────────────────────────────


@router.get("/invitations/", response_model=list[BidInvitationResponse])
async def list_invitations(
    session: SessionDep,
    user_id: CurrentUserId,
    package_id: uuid.UUID = Query(...),
    status_filter: str | None = Query(default=None, alias="status"),
    _perm: None = Depends(RequirePermission("bid_management.read")),
) -> list[BidInvitationResponse]:
    await _verify_package_access(session, package_id, user_id)
    svc = BidManagementService(session)
    rows = await svc.invitation_repo.list_for_package(package_id, status=status_filter)
    return [BidInvitationResponse.model_validate(r) for r in rows]


@router.post("/invitations/", response_model=BidInvitationResponse, status_code=201)
async def create_invitation(
    data: BidInvitationCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bid_management.create")),
) -> BidInvitationResponse:
    await _verify_package_access(session, data.package_id, user_id)
    svc = BidManagementService(session)
    inv = await svc.create_invitation(data)
    return BidInvitationResponse.model_validate(inv)


@router.patch("/invitations/{invitation_id}", response_model=BidInvitationResponse)
async def update_invitation(
    invitation_id: uuid.UUID,
    data: BidInvitationUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bid_management.update")),
) -> BidInvitationResponse:
    await _verify_invitation_access(session, invitation_id, user_id)
    svc = BidManagementService(session)
    inv = await svc.update_invitation(invitation_id, data)
    return BidInvitationResponse.model_validate(inv)


@router.delete("/invitations/{invitation_id}", status_code=204)
async def delete_invitation(
    invitation_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bid_management.delete")),
) -> None:
    await _verify_invitation_access(session, invitation_id, user_id)
    svc = BidManagementService(session)
    await svc.delete_invitation(invitation_id)


@router.post("/invitations/{invitation_id}/resend", response_model=BidInvitationResponse)
async def resend_invitation(
    invitation_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bid_management.update")),
) -> BidInvitationResponse:
    await _verify_invitation_access(session, invitation_id, user_id)
    svc = BidManagementService(session)
    inv = await svc.resend_invitation(invitation_id)
    return BidInvitationResponse.model_validate(inv)


@router.post("/invitations/{invitation_id}/mark-opened", response_model=BidInvitationResponse)
async def mark_invitation_opened(
    invitation_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bid_management.update")),
) -> BidInvitationResponse:
    await _verify_invitation_access(session, invitation_id, user_id)
    svc = BidManagementService(session)
    inv = await svc.mark_invitation_opened(invitation_id)
    return BidInvitationResponse.model_validate(inv)


@router.post("/invitations/{invitation_id}/decline", response_model=BidInvitationResponse)
async def decline_invitation(
    invitation_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    reason: str = Query(default=""),
    _perm: None = Depends(RequirePermission("bid_management.update")),
) -> BidInvitationResponse:
    await _verify_invitation_access(session, invitation_id, user_id)
    svc = BidManagementService(session)
    inv = await svc.decline_invitation(invitation_id, reason=reason)
    return BidInvitationResponse.model_validate(inv)


# ── Submissions ───────────────────────────────────────────────────────────


@router.get("/submissions/", response_model=list[BidSubmissionResponse])
async def list_submissions(
    session: SessionDep,
    user_id: CurrentUserId,
    package_id: uuid.UUID = Query(...),
    _perm: None = Depends(RequirePermission("bid_management.read")),
) -> list[BidSubmissionResponse]:
    await _verify_package_access(session, package_id, user_id)
    svc = BidManagementService(session)
    rows = await svc.submission_repo.submissions_for_package(package_id)
    return [BidSubmissionResponse.model_validate(r) for r in rows]


@router.post("/submissions/", response_model=BidSubmissionResponse, status_code=201)
async def create_submission(
    data: BidSubmissionCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bid_management.create")),
) -> BidSubmissionResponse:
    await _verify_invitation_access(session, data.invitation_id, user_id)
    svc = BidManagementService(session)
    sub = await svc.record_submission(data)
    return BidSubmissionResponse.model_validate(sub)


@router.patch("/submissions/{submission_id}", response_model=BidSubmissionResponse)
async def update_submission(
    submission_id: uuid.UUID,
    data: BidSubmissionUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bid_management.update")),
) -> BidSubmissionResponse:
    await _verify_submission_access(session, submission_id, user_id)
    svc = BidManagementService(session)
    sub = await svc.update_submission(submission_id, data)
    return BidSubmissionResponse.model_validate(sub)


@router.delete("/submissions/{submission_id}", status_code=204)
async def delete_submission(
    submission_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bid_management.delete")),
) -> None:
    await _verify_submission_access(session, submission_id, user_id)
    svc = BidManagementService(session)
    await svc.delete_submission(submission_id)


@router.post("/submissions/{submission_id}/withdraw", response_model=BidSubmissionResponse)
async def withdraw_submission(
    submission_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bid_management.update")),
) -> BidSubmissionResponse:
    await _verify_submission_access(session, submission_id, user_id)
    svc = BidManagementService(session)
    sub = await svc.withdraw_submission(submission_id)
    return BidSubmissionResponse.model_validate(sub)


# ── Submission lines ──────────────────────────────────────────────────────


@router.get("/submission-lines/", response_model=list[BidSubmissionLineResponse])
async def list_submission_lines(
    session: SessionDep,
    user_id: CurrentUserId,
    submission_id: uuid.UUID = Query(...),
    _perm: None = Depends(RequirePermission("bid_management.read")),
) -> list[BidSubmissionLineResponse]:
    await _verify_submission_access(session, submission_id, user_id)
    svc = BidManagementService(session)
    rows = await svc.submission_line_repo.list_for_submission(submission_id)
    return [BidSubmissionLineResponse.model_validate(r) for r in rows]


@router.post("/submission-lines/", response_model=BidSubmissionLineResponse, status_code=201)
async def create_submission_line(
    data: BidSubmissionLineCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bid_management.create")),
) -> BidSubmissionLineResponse:
    await _verify_submission_access(session, data.submission_id, user_id)
    svc = BidManagementService(session)
    line = await svc.create_submission_line(data)
    return BidSubmissionLineResponse.model_validate(line)


@router.post(
    "/submissions/{submission_id}/lines/bulk",
    response_model=list[BidSubmissionLineResponse],
)
async def bulk_create_submission_lines(
    submission_id: uuid.UUID,
    data: BidSubmissionLineBulkCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bid_management.create")),
) -> list[BidSubmissionLineResponse]:
    await _verify_submission_access(session, submission_id, user_id)
    svc = BidManagementService(session)
    rows = await svc.bulk_create_submission_lines(submission_id, data.items)
    return [BidSubmissionLineResponse.model_validate(r) for r in rows]


@router.patch("/submission-lines/{line_id}", response_model=BidSubmissionLineResponse)
async def update_submission_line(
    line_id: uuid.UUID,
    data: BidSubmissionLineUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bid_management.update")),
) -> BidSubmissionLineResponse:
    line_row = await session.get(BidSubmissionLine, line_id)
    if line_row is None:
        raise HTTPException(status_code=404, detail="Submission line not found")
    await _verify_submission_access(session, line_row.submission_id, user_id)
    svc = BidManagementService(session)
    line = await svc.update_submission_line(line_id, data)
    return BidSubmissionLineResponse.model_validate(line)


@router.delete("/submission-lines/{line_id}", status_code=204)
async def delete_submission_line(
    line_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bid_management.delete")),
) -> None:
    line_row = await session.get(BidSubmissionLine, line_id)
    if line_row is None:
        raise HTTPException(status_code=404, detail="Submission line not found")
    await _verify_submission_access(session, line_row.submission_id, user_id)
    svc = BidManagementService(session)
    await svc.delete_submission_line(line_id)


# ── Q & A ─────────────────────────────────────────────────────────────────


@router.get("/q-and-a/", response_model=list[BidQAResponse])
async def list_qa(
    session: SessionDep,
    user_id: CurrentUserId,
    package_id: uuid.UUID = Query(...),
    _perm: None = Depends(RequirePermission("bid_management.read")),
) -> list[BidQAResponse]:
    await _verify_package_access(session, package_id, user_id)
    svc = BidManagementService(session)
    rows = await svc.qa_repo.q_and_a_for_package(package_id)
    return [BidQAResponse.model_validate(r) for r in rows]


@router.post("/q-and-a/", response_model=BidQAResponse, status_code=201)
async def create_qa(
    data: BidQACreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bid_management.create")),
) -> BidQAResponse:
    await _verify_package_access(session, data.package_id, user_id)
    svc = BidManagementService(session)
    qa = await svc.create_qa(data)
    return BidQAResponse.model_validate(qa)


@router.patch("/q-and-a/{qa_id}", response_model=BidQAResponse)
async def update_qa(
    qa_id: uuid.UUID,
    data: BidQAUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bid_management.update")),
) -> BidQAResponse:
    qa_row = await session.get(BidQA, qa_id)
    if qa_row is None:
        raise HTTPException(status_code=404, detail="Q&A not found")
    await _verify_package_access(session, qa_row.package_id, user_id)
    svc = BidManagementService(session)
    qa = await svc.update_qa(qa_id, data)
    return BidQAResponse.model_validate(qa)


@router.delete("/q-and-a/{qa_id}", status_code=204)
async def delete_qa(
    qa_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bid_management.delete")),
) -> None:
    qa_row = await session.get(BidQA, qa_id)
    if qa_row is None:
        raise HTTPException(status_code=404, detail="Q&A not found")
    await _verify_package_access(session, qa_row.package_id, user_id)
    svc = BidManagementService(session)
    await svc.delete_qa(qa_id)


@router.post("/q-and-a/{qa_id}/answer", response_model=BidQAResponse)
async def answer_qa(
    qa_id: uuid.UUID,
    data: BidQAAnswer,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bid_management.update")),
) -> BidQAResponse:
    qa_row = await session.get(BidQA, qa_id)
    if qa_row is None:
        raise HTTPException(status_code=404, detail="Q&A not found")
    await _verify_package_access(session, qa_row.package_id, user_id)
    svc = BidManagementService(session)
    qa = await svc.answer_qa(qa_id, data)
    return BidQAResponse.model_validate(qa)


# ── Comparisons ───────────────────────────────────────────────────────────


@router.post("/comparisons/", response_model=BidComparisonResponse, status_code=201)
async def create_comparison(
    data: BidComparisonCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bid_management.create")),
) -> BidComparisonResponse:
    await _verify_package_access(session, data.package_id, user_id)
    svc = BidManagementService(session)
    comparison = await svc.create_comparison(data)
    return BidComparisonResponse.model_validate(comparison)


@router.patch("/comparisons/{comparison_id}", response_model=BidComparisonResponse)
async def update_comparison(
    comparison_id: uuid.UUID,
    data: BidComparisonUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bid_management.update")),
) -> BidComparisonResponse:
    await _verify_comparison_access(session, comparison_id, user_id)
    svc = BidManagementService(session)
    comparison = await svc.update_comparison(comparison_id, data)
    return BidComparisonResponse.model_validate(comparison)


@router.delete("/comparisons/{comparison_id}", status_code=204)
async def delete_comparison(
    comparison_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bid_management.delete")),
) -> None:
    await _verify_comparison_access(session, comparison_id, user_id)
    svc = BidManagementService(session)
    await svc.delete_comparison(comparison_id)


@router.post(
    "/comparisons/{comparison_id}/compute-leveling",
    response_model=list[BidLevelingResponse],
)
async def compute_leveling(
    comparison_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bid_management.compute_leveling")),
) -> list[BidLevelingResponse]:
    await _verify_comparison_access(session, comparison_id, user_id)
    svc = BidManagementService(session)
    rows = await svc.compute_leveling(comparison_id)
    return [BidLevelingResponse.model_validate(r) for r in rows]


@router.get(
    "/comparisons/{comparison_id}/leveling-table",
    response_model=LevelingTableResponse,
)
async def leveling_table(
    comparison_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bid_management.read")),
) -> LevelingTableResponse:
    await _verify_comparison_access(session, comparison_id, user_id)
    svc = BidManagementService(session)
    comparison = await svc.comparison_repo.get_by_id(comparison_id)
    rows = await svc.leveling_table(comparison_id)
    return LevelingTableResponse(
        comparison_id=comparison_id,
        package_id=comparison.package_id if comparison else uuid.UUID(int=0),
        computed_at=comparison.computed_at if comparison else None,
        rows=[BidLevelingResponse.model_validate(r) for r in rows],
        recommended_bidder_id=comparison.recommended_bidder_id if comparison else None,
        recommended_reason=comparison.recommended_reason if comparison else "",
    )


# ── Awards ────────────────────────────────────────────────────────────────


@router.patch("/awards/{award_id}", response_model=BidAwardResponse)
async def update_award(
    award_id: uuid.UUID,
    data: BidAwardUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bid_management.award")),
) -> BidAwardResponse:
    award_row = await session.get(BidAward, award_id)
    if award_row is None:
        raise HTTPException(status_code=404, detail="Award not found")
    await _verify_package_access(session, award_row.package_id, user_id)
    svc = BidManagementService(session)
    award = await svc.update_award(award_id, data)
    return BidAwardResponse.model_validate(award)


@router.delete("/awards/{award_id}", status_code=204)
async def delete_award(
    award_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bid_management.delete")),
) -> None:
    award_row = await session.get(BidAward, award_id)
    if award_row is None:
        raise HTTPException(status_code=404, detail="Award not found")
    await _verify_package_access(session, award_row.package_id, user_id)
    svc = BidManagementService(session)
    await svc.delete_award(award_id)


# ── Rejections ────────────────────────────────────────────────────────────


@router.post("/rejections/", response_model=BidRejectionResponse, status_code=201)
async def create_rejection(
    data: BidRejectionCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bid_management.create")),
) -> BidRejectionResponse:
    await _verify_package_access(session, data.package_id, user_id)
    svc = BidManagementService(session)
    rej = await svc.create_rejection(data)
    return BidRejectionResponse.model_validate(rej)


@router.patch("/rejections/{rejection_id}", response_model=BidRejectionResponse)
async def update_rejection(
    rejection_id: uuid.UUID,
    data: BidRejectionUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bid_management.update")),
) -> BidRejectionResponse:
    rej_row = await session.get(BidRejection, rejection_id)
    if rej_row is None:
        raise HTTPException(status_code=404, detail=translate("errors.rejection_not_found", locale=get_locale()))
    await _verify_package_access(session, rej_row.package_id, user_id)
    svc = BidManagementService(session)
    rej = await svc.update_rejection(rejection_id, data)
    return BidRejectionResponse.model_validate(rej)


@router.delete("/rejections/{rejection_id}", status_code=204)
async def delete_rejection(
    rejection_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bid_management.delete")),
) -> None:
    rej_row = await session.get(BidRejection, rejection_id)
    if rej_row is None:
        raise HTTPException(status_code=404, detail=translate("errors.rejection_not_found", locale=get_locale()))
    await _verify_package_access(session, rej_row.package_id, user_id)
    svc = BidManagementService(session)
    await svc.delete_rejection(rejection_id)


@router.post("/rejections/{rejection_id}/notify", response_model=BidRejectionResponse)
async def notify_rejection(
    rejection_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bid_management.update")),
) -> BidRejectionResponse:
    rej_row = await session.get(BidRejection, rejection_id)
    if rej_row is None:
        raise HTTPException(status_code=404, detail=translate("errors.rejection_not_found", locale=get_locale()))
    await _verify_package_access(session, rej_row.package_id, user_id)
    svc = BidManagementService(session)
    rej = await svc.notify_rejection(rejection_id)
    return BidRejectionResponse.model_validate(rej)
