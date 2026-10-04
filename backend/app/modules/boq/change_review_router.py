# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Routes for BOQ change review.

Included into the BOQ ``router`` via ``router.include_router`` so the routes
mount under ``/api/v1/boq``:

    GET  /boqs/{boq_id}/change-flags/                  - flags of the BOQ
    GET  /boqs/{boq_id}/change-flags/summary/          - open counts for the badge
    POST /boqs/{boq_id}/change-flags/scan/             - work out flags from the data
    POST /boqs/{boq_id}/change-flags/review/           - mark reviewed or reopen
    GET  /boqs/{boq_id}/bim-quantity-proposals/        - old vs new from new model versions
    POST /boqs/{boq_id}/bim-quantity-proposals/apply/  - write the accepted rows

Nothing here changes a quantity except the apply route, and that one only
writes the positions a person named, with figures recomputed on the server.
"""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.boq.change_review import ChangeReviewService
from app.modules.boq.change_review_schemas import (
    BIMQuantityApplyRequest,
    BIMQuantityApplyResponse,
    BIMQuantityProposalResponse,
    ChangeFlagListResponse,
    ChangeFlagReviewRequest,
    ChangeFlagReviewResponse,
    ChangeFlagScanResponse,
    ChangeFlagSummaryResponse,
)
from app.modules.boq.models import BOQ

change_review_router = APIRouter(tags=["boq"])


async def _verify_boq_access(session: SessionDep, boq_id: uuid.UUID, user_id: str) -> None:
    """404 unless the caller may see the BOQ's project (owner, member or admin)."""
    row = (await session.execute(select(BOQ.project_id).where(BOQ.id == boq_id))).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BOQ not found")
    try:
        await verify_project_access(row[0], user_id, session)
    except HTTPException as exc:
        # Same answer for "missing" and "not yours", and named after the BOQ
        # the caller asked for rather than a project they never mentioned.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BOQ not found") from exc


def _user_uuid(user_id: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(user_id))
    except (TypeError, ValueError):
        return None


@change_review_router.get(
    "/boqs/{boq_id}/change-flags/",
    response_model=ChangeFlagListResponse,
    summary="List change flags of a BOQ",
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def list_change_flags(
    boq_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    status_filter: Literal["open", "reviewed", "all"] = Query("all", alias="status"),
) -> ChangeFlagListResponse:
    """Positions whose drawing got a new revision or whose BIM model a new version."""
    await _verify_boq_access(session, boq_id, user_id)
    return await ChangeReviewService(session).list_flags(boq_id, None if status_filter == "all" else status_filter)


@change_review_router.get(
    "/boqs/{boq_id}/change-flags/summary/",
    response_model=ChangeFlagSummaryResponse,
    summary="Open change flag counts of a BOQ",
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def change_flag_summary(
    boq_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> ChangeFlagSummaryResponse:
    """Open flag count for the editor badge, by source."""
    await _verify_boq_access(session, boq_id, user_id)
    return await ChangeReviewService(session).summary(boq_id)


@change_review_router.post(
    "/boqs/{boq_id}/change-flags/scan/",
    response_model=ChangeFlagScanResponse,
    summary="Detect positions affected by new drawing revisions or model versions",
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def scan_change_flags(
    boq_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> ChangeFlagScanResponse:
    """Record flags for what changed since the positions were measured.

    Writes review flags only, never a position, which is why reading the BOQ
    is enough to run it (the same footing as the model-link refresh probe).
    Repeating it over unchanged data creates nothing.
    """
    await _verify_boq_access(session, boq_id, user_id)
    return await ChangeReviewService(session).scan(boq_id)


@change_review_router.post(
    "/boqs/{boq_id}/change-flags/review/",
    response_model=ChangeFlagReviewResponse,
    summary="Mark change flags reviewed, or reopen them",
    dependencies=[Depends(RequirePermission("boq.update"))],
)
async def review_change_flags(
    boq_id: uuid.UUID,
    body: ChangeFlagReviewRequest,
    user_id: CurrentUserId,
    session: SessionDep,
) -> ChangeFlagReviewResponse:
    """Close the named flags (or every open one) after a person looked at them."""
    await _verify_boq_access(session, boq_id, user_id)
    return await ChangeReviewService(session).review_flags(
        boq_id,
        flag_ids=body.flag_ids,
        all_open=body.all_open,
        new_status=body.status,
        note=body.note,
        user_id=_user_uuid(user_id),
    )


@change_review_router.get(
    "/boqs/{boq_id}/bim-quantity-proposals/",
    response_model=BIMQuantityProposalResponse,
    summary="Proposed quantity updates from new BIM model versions",
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def list_bim_quantity_proposals(
    boq_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> BIMQuantityProposalResponse:
    """Old against new quantity for positions linked to elements of a revised model."""
    await _verify_boq_access(session, boq_id, user_id)
    return await ChangeReviewService(session).bim_quantity_proposals(boq_id)


@change_review_router.post(
    "/boqs/{boq_id}/bim-quantity-proposals/apply/",
    response_model=BIMQuantityApplyResponse,
    summary="Accept proposed quantity updates for the chosen positions",
    dependencies=[Depends(RequirePermission("boq.update"))],
)
async def apply_bim_quantity_proposals(
    boq_id: uuid.UUID,
    body: BIMQuantityApplyRequest,
    user_id: CurrentUserId,
    session: SessionDep,
) -> BIMQuantityApplyResponse:
    """The human confirm step: only the listed positions are written."""
    await _verify_boq_access(session, boq_id, user_id)
    return await ChangeReviewService(session).apply_bim_quantity_proposals(
        boq_id, body.position_ids, user_id=_user_uuid(user_id)
    )
