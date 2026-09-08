# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Variations API routes - mounted at /api/v1/variations/."""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Body, Depends, Query
from pydantic import BaseModel, Field

from app.dependencies import (
    CurrentUserId,
    CurrentUserPayload,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.boq.schemas import BOQResponse
from app.modules.variations.schemas import (
    DayworkSheetCreate,
    DayworkSheetLineCreate,
    DayworkSheetLineResponse,
    DayworkSheetLineUpdate,
    DayworkSheetListResponse,
    DayworkSheetResponse,
    DayworkSheetUpdate,
    DisruptionClaimCreate,
    DisruptionClaimListResponse,
    DisruptionClaimResponse,
    DisruptionClaimUpdate,
    EOTTIARecordRequest,
    ExtensionOfTimeClaimCreate,
    ExtensionOfTimeClaimListResponse,
    ExtensionOfTimeClaimResponse,
    ExtensionOfTimeClaimUpdate,
    FinalAccountCreate,
    FinalAccountResponse,
    FinalAccountUpdate,
    NEC4TimerStatusResponse,
    NoticeCreate,
    NoticeListResponse,
    NoticeResponse,
    NoticeUpdate,
    SiteMeasurementCreate,
    SiteMeasurementListResponse,
    SiteMeasurementResponse,
    SiteMeasurementUpdate,
    VariationBOQCreate,
    VariationBOQLineTraceUpdate,
    VariationBOQResponse,
    VariationBOQTraceResponse,
    VariationCostImpactCreate,
    VariationCostImpactResponse,
    VariationCostImpactUpdate,
    VariationDashboardResponse,
    VariationOrderCreate,
    VariationOrderListResponse,
    VariationOrderResponse,
    VariationOrderUpdate,
    VariationRequestCreate,
    VariationRequestListResponse,
    VariationRequestResponse,
    VariationRequestUpdate,
    VariationScheduleImpactCreate,
    VariationScheduleImpactResponse,
    VariationScheduleImpactUpdate,
)
from app.modules.variations.service import (
    VariationsService,
    ensure_high_value_authorised,
    is_nec4_overdue,
    supported_contract_standards,
)

router = APIRouter(tags=["variations"])
logger = logging.getLogger(__name__)


def _get_service(session: SessionDep) -> VariationsService:
    return VariationsService(session)


# ── Generic transition body schemas ─────────────────────────────────────────


class _ResponseBody(BaseModel):
    response_summary: str | None = None


class _DecisionBody(BaseModel):
    decision_notes: str | None = None
    decided_amount: Decimal | None = None
    granted_days: int | None = Field(default=None, ge=0, le=3650)
    #: Why an approved amount departs from the pricing state it was agreed
    #: against (Issue #435). Approving a variation at an amount that differs
    #: from the submitted bill total is refused without it.
    agreed_variance_note: str | None = None


class _ConvertVOBody(BaseModel):
    title: str = ""
    # The two figures are nullable where the two strings are not, because nil
    # is a real answer for both of them and for neither of the others: a
    # variation can be agreed at no cost, or add no time, and either has to
    # stick rather than be read as "say nothing and inherit the estimate".
    # An empty title or currency is not an answer in that sense, so those keep
    # the falsy fallback the route has always used.
    final_cost_impact: Decimal | None = None
    final_schedule_days: int | None = None
    currency: str = ""
    agreed_at: str | None = None
    # The contract this order amends. Completing an order that names one is
    # what moves the contract sum, and a promotion is the moment somebody
    # knows which contract it lands on, so it can be named here rather than
    # only patched on afterwards.
    affected_contract_id: uuid.UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Notices ────────────────────────────────────────────────────────────────


@router.get("/notices/", response_model=NoticeListResponse)
async def list_notices(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    status: str | None = Query(default=None),
    _perm: None = Depends(RequirePermission("variations.read")),
    service: VariationsService = Depends(_get_service),
) -> NoticeListResponse:
    """A page of the project's variation notices, and how many there are.

    ``total`` counts the notices matching ``status``, not the page, so a
    filtered register reports the size of what it filtered to.
    """
    await verify_project_access(project_id, user_id, session)
    rows, total = await service.notice_repo.list_for_project(
        project_id,
        offset=offset,
        limit=limit,
        status=status,
    )
    return NoticeListResponse(
        items=[NoticeResponse.model_validate(r) for r in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post("/notices/", response_model=NoticeResponse, status_code=201)
async def create_notice(
    data: NoticeCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("variations.create")),
    service: VariationsService = Depends(_get_service),
) -> NoticeResponse:
    await verify_project_access(data.project_id, user_id, session)
    notice = await service.create_notice(data, user_id=user_id)
    return NoticeResponse.model_validate(notice)


@router.get("/notices/{notice_id}", response_model=NoticeResponse)
async def get_notice(
    notice_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("variations.read")),
    service: VariationsService = Depends(_get_service),
) -> NoticeResponse:
    notice = await service.get_notice(notice_id)
    await verify_project_access(notice.project_id, str(user_id), session)
    return NoticeResponse.model_validate(notice)


@router.patch("/notices/{notice_id}", response_model=NoticeResponse)
async def update_notice(
    notice_id: uuid.UUID,
    data: NoticeUpdate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("variations.update")),
    service: VariationsService = Depends(_get_service),
) -> NoticeResponse:
    existing = await service.get_notice(notice_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    notice = await service.update_notice(notice_id, data, user_id=str(user_id) if user_id else None)
    return NoticeResponse.model_validate(notice)


@router.delete("/notices/{notice_id}", status_code=204)
async def delete_notice(
    notice_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("variations.delete")),
    service: VariationsService = Depends(_get_service),
) -> None:
    existing = await service.get_notice(notice_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    await service.notice_repo.delete(notice_id)


@router.post("/notices/{notice_id}/acknowledge", response_model=NoticeResponse)
async def acknowledge_notice(
    notice_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("variations.update")),
    service: VariationsService = Depends(_get_service),
) -> NoticeResponse:
    existing = await service.get_notice(notice_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    notice = await service.transition_notice(notice_id, "acknowledged", user_id=user_id)
    return NoticeResponse.model_validate(notice)


@router.post("/notices/{notice_id}/respond", response_model=NoticeResponse)
async def respond_notice(
    notice_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    body: _ResponseBody = Body(default=_ResponseBody()),
    _perm: None = Depends(RequirePermission("variations.update")),
    service: VariationsService = Depends(_get_service),
) -> NoticeResponse:
    existing = await service.get_notice(notice_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    notice = await service.transition_notice(
        notice_id,
        "responded",
        user_id=user_id,
        response_summary=body.response_summary,
    )
    return NoticeResponse.model_validate(notice)


@router.post("/notices/{notice_id}/close", response_model=NoticeResponse)
async def close_notice(
    notice_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("variations.update")),
    service: VariationsService = Depends(_get_service),
) -> NoticeResponse:
    existing = await service.get_notice(notice_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    notice = await service.transition_notice(notice_id, "closed", user_id=user_id)
    return NoticeResponse.model_validate(notice)


# ── Variation requests ─────────────────────────────────────────────────────


@router.get("/variation-requests/", response_model=VariationRequestListResponse)
async def list_variation_requests(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    status: str | None = Query(default=None),
    _perm: None = Depends(RequirePermission("variations.read")),
    service: VariationsService = Depends(_get_service),
) -> VariationRequestListResponse:
    """A page of the project's variation requests, and how many there are.

    ``total`` counts the requests matching ``status``, not the page.
    """
    await verify_project_access(project_id, user_id, session)
    rows, total = await service.vr_repo.list_for_project(
        project_id,
        offset=offset,
        limit=limit,
        status=status,
    )
    return VariationRequestListResponse(
        items=[VariationRequestResponse.model_validate(r) for r in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post("/variation-requests/", response_model=VariationRequestResponse, status_code=201)
async def create_variation_request(
    data: VariationRequestCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("variations.create")),
    service: VariationsService = Depends(_get_service),
) -> VariationRequestResponse:
    await verify_project_access(data.project_id, user_id, session)
    vr = await service.create_request(data, user_id=user_id)
    return VariationRequestResponse.model_validate(vr)


@router.get("/variation-requests/{vr_id}", response_model=VariationRequestResponse)
async def get_variation_request(
    vr_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("variations.read")),
    service: VariationsService = Depends(_get_service),
) -> VariationRequestResponse:
    vr = await service.get_request(vr_id)
    await verify_project_access(vr.project_id, str(user_id), session)
    return VariationRequestResponse.model_validate(vr)


@router.patch("/variation-requests/{vr_id}", response_model=VariationRequestResponse)
async def update_variation_request(
    vr_id: uuid.UUID,
    data: VariationRequestUpdate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("variations.update")),
    service: VariationsService = Depends(_get_service),
) -> VariationRequestResponse:
    existing = await service.get_request(vr_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    vr = await service.update_request(vr_id, data, user_id=str(user_id) if user_id else None)
    return VariationRequestResponse.model_validate(vr)


@router.delete("/variation-requests/{vr_id}", status_code=204)
async def delete_variation_request(
    vr_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("variations.delete")),
    service: VariationsService = Depends(_get_service),
) -> None:
    existing = await service.get_request(vr_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    await service.delete_request(vr_id)


@router.post("/variation-requests/{vr_id}/submit", response_model=VariationRequestResponse)
async def submit_variation_request(
    vr_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("variations.submit_request")),
    service: VariationsService = Depends(_get_service),
) -> VariationRequestResponse:
    existing = await service.get_request(vr_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    vr = await service.transition_variation_request(vr_id, "submitted", user_id=user_id)
    return VariationRequestResponse.model_validate(vr)


@router.post("/variation-requests/{vr_id}/approve", response_model=VariationRequestResponse)
async def approve_variation_request(
    vr_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    body: _DecisionBody = Body(default=_DecisionBody()),
    _perm: None = Depends(RequirePermission("variations.approve_request")),
    service: VariationsService = Depends(_get_service),
) -> VariationRequestResponse:
    existing = await service.get_request(vr_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    # RBAC: enforce the high-value approval tier - a Manager holding only
    # variations.approve_request must not wave through a variation whose cost
    # impact exceeds HIGH_VALUE_APPROVAL_THRESHOLD without the admin-only
    # variations.approve_high_value permission (closes the dead-gate finding).
    # The gate is applied to the LARGER of the request's own figure and the
    # amount actually being approved. Checking only the stored figure would
    # let a Manager approve a small variation at a large number, which is the
    # same authorisation hole the gate was added to close, reopened by the
    # field that lets the approver name a different amount.
    ensure_high_value_authorised(
        max(existing.estimated_cost_impact, body.decided_amount)
        if body.decided_amount is not None
        else existing.estimated_cost_impact,
        payload=payload,
    )
    vr = await service.transition_variation_request(
        vr_id,
        "approved",
        user_id=user_id,
        decision_notes=body.decision_notes,
        agreed_cost_impact=body.decided_amount,
        agreed_variance_note=body.agreed_variance_note,
    )
    return VariationRequestResponse.model_validate(vr)


@router.post("/variation-requests/{vr_id}/reject", response_model=VariationRequestResponse)
async def reject_variation_request(
    vr_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    body: _DecisionBody = Body(default=_DecisionBody()),
    _perm: None = Depends(RequirePermission("variations.approve_request")),
    service: VariationsService = Depends(_get_service),
) -> VariationRequestResponse:
    existing = await service.get_request(vr_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    vr = await service.transition_variation_request(
        vr_id,
        "rejected",
        user_id=user_id,
        decision_notes=body.decision_notes,
    )
    return VariationRequestResponse.model_validate(vr)


@router.post("/variation-requests/{vr_id}/convert-to-vo", response_model=VariationOrderResponse)
async def convert_vr_to_vo(
    vr_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    user_payload: CurrentUserPayload,
    body: _ConvertVOBody = Body(default=_ConvertVOBody()),
    _perm: None = Depends(RequirePermission("variations.convert_to_vo")),
    service: VariationsService = Depends(_get_service),
) -> VariationOrderResponse:
    vr = await service.get_request(vr_id)
    await verify_project_access(vr.project_id, str(user_id), session)
    # RBAC: convert-to-VO commits the variation's money into a VariationOrder
    # (and a mirrored ChangeOrder), so it is symmetric with approval - gate
    # high-value conversions behind variations.approve_high_value too. Use the
    # effective committed amount (body override else the source VR estimate).
    effective_amount = body.final_cost_impact if body.final_cost_impact is not None else vr.estimated_cost_impact
    ensure_high_value_authorised(effective_amount, payload=user_payload)
    payload = VariationOrderCreate(
        project_id=vr.project_id,
        variation_request_id=vr_id,
        title=body.title or vr.title,
        # The amount the gate above was applied to is the amount the order has
        # to carry. Passing the body's own field here instead let a conversion
        # that named no figure - which is what the variations page sends - be
        # authorised against the request's estimate and then commit zero, so
        # every order promoted through the interface lost its money and its
        # mirrored change order was priced off the same nothing.
        final_cost_impact=effective_amount,
        final_schedule_days=(
            body.final_schedule_days if body.final_schedule_days is not None else vr.estimated_schedule_days
        ),
        currency=body.currency or vr.currency,
        agreed_at=body.agreed_at,
        affected_contract_id=body.affected_contract_id,
        metadata=body.metadata,
    )
    vo = await service.convert_vr_to_vo(vr_id, payload, user_id=user_id)
    return VariationOrderResponse.model_validate(vo)


# ── Variation request BOQ (Issue #435) ────────────────────────
#
# A variation request may own a dedicated bill of quantities holding only the
# scope that variation changes. The bill itself is served by the BOQ module -
# everything at /api/v1/boq/boqs/{boq_id}/... works on it unchanged, which is
# the point of making it an ordinary bill. These three routes cover only what
# the BOQ module cannot answer: open one for a request, read it back with its
# provenance, and let the priced total become the request's headline figure.


@router.post(
    "/variation-requests/{vr_id}/boq/",
    response_model=BOQResponse,
    status_code=201,
    summary="Open a dedicated bill for a variation request",
)
async def create_variation_request_boq(
    vr_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    body: VariationBOQCreate = Body(default=VariationBOQCreate()),
    _perm: None = Depends(RequirePermission("variations.create")),
    service: VariationsService = Depends(_get_service),
) -> BOQResponse:
    """Open the request's own bill, optionally seeded from existing scope.

    ``source_positions`` names positions on the project's estimating bills and
    ``source_contract_lines`` names schedule-of-values lines of the project's
    contracts; each seeded line records where it came from. Both are optional,
    and an empty body opens an empty bill.
    """
    vr = await service.get_request(vr_id)
    await verify_project_access(vr.project_id, str(user_id), session)
    boq = await service.create_request_boq(vr_id, body, user_id=str(user_id) if user_id else None)
    return BOQResponse.model_validate(boq)


@router.get(
    "/variation-requests/{vr_id}/boq/",
    response_model=VariationBOQResponse,
    summary="The request's bill, priced and traced",
)
async def get_variation_request_boq(
    vr_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("variations.read")),
    service: VariationsService = Depends(_get_service),
) -> VariationBOQResponse:
    """Read the request's bill with its totals, provenance and checks.

    A request that has no bill answers ``has_boq`` false with its headline
    estimate and no money fields - the state every request was in before this
    existed, and still the state of most of them.
    """
    vr = await service.get_request(vr_id)
    await verify_project_access(vr.project_id, str(user_id), session)
    view = await service.get_request_boq_view(vr_id)
    return VariationBOQResponse.model_validate(view)


@router.post(
    "/variation-requests/{vr_id}/boq/adopt",
    response_model=VariationRequestResponse,
    summary="Adopt the bill's priced total as the request's estimate",
)
async def adopt_variation_request_boq(
    vr_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("variations.update")),
    service: VariationsService = Depends(_get_service),
) -> VariationRequestResponse:
    """Replace the headline estimate with what the bill actually prices.

    Deliberately explicit. Every other module reads the headline off the
    request, so moving it is a decision somebody takes rather than something
    that happens while a bill is still being edited.
    """
    vr = await service.get_request(vr_id)
    await verify_project_access(vr.project_id, str(user_id), session)
    updated = await service.adopt_request_boq_total(vr_id, user_id=str(user_id) if user_id else None)
    return VariationRequestResponse.model_validate(updated)


@router.put(
    "/variation-requests/{vr_id}/boq/lines/{position_id}/trace",
    response_model=VariationBOQTraceResponse,
    summary="Record where one line of the bill came from",
)
async def set_variation_boq_line_trace(
    vr_id: uuid.UUID,
    position_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    body: VariationBOQLineTraceUpdate = Body(default=VariationBOQLineTraceUpdate()),
    _perm: None = Depends(RequirePermission("variations.update")),
    service: VariationsService = Depends(_get_service),
) -> VariationBOQTraceResponse:
    """Trace a line of the bill to the contracted scope it changes.

    Seeding a bill records this for the lines it copies. This is the route for
    every line that arrived afterwards, which is most of them: the bill is an
    ordinary bill and is edited through the BOQ module's own position routes,
    so a line typed in there had no way to acquire provenance at all.

    Naming a schedule-of-values line of another project's contract is refused
    rather than stored, so the trace table cannot come to hold a reference
    that points out of the project it belongs to.
    """
    vr = await service.get_request(vr_id)
    await verify_project_access(vr.project_id, str(user_id), session)
    trace = await service.set_boq_line_trace(vr_id, position_id, body, user_id=str(user_id) if user_id else None)
    return VariationBOQTraceResponse.model_validate(trace)


@router.delete(
    "/variation-requests/{vr_id}/boq/lines/{position_id}/trace",
    response_model=VariationBOQTraceResponse,
    summary="Withdraw a line's recorded provenance",
)
async def clear_variation_boq_line_trace(
    vr_id: uuid.UUID,
    position_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("variations.update")),
    service: VariationsService = Depends(_get_service),
) -> VariationBOQTraceResponse:
    """Say that this line derives from nothing after all.

    The row stays, holding ``origin='manual'`` and no references, because a
    line nobody has answered for and a line answered for as originating scope
    are different states and the bill should not report them as the same
    silence.
    """
    vr = await service.get_request(vr_id)
    await verify_project_access(vr.project_id, str(user_id), session)
    trace = await service.clear_boq_line_trace(vr_id, position_id, user_id=str(user_id) if user_id else None)
    return VariationBOQTraceResponse.model_validate(trace)


# ── Variation orders ───────────────────────────────────────────────────────


@router.get("/variation-orders/", response_model=VariationOrderListResponse)
async def list_variation_orders(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    status: str | None = Query(default=None),
    _perm: None = Depends(RequirePermission("variations.read")),
    service: VariationsService = Depends(_get_service),
) -> VariationOrderListResponse:
    """A page of the project's variation orders, and how many there are.

    ``total`` counts the orders matching ``status``, not the page.
    """
    await verify_project_access(project_id, user_id, session)
    rows, total = await service.vo_repo.list_for_project(
        project_id,
        offset=offset,
        limit=limit,
        status=status,
    )
    return VariationOrderListResponse(
        items=[VariationOrderResponse.model_validate(r) for r in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post("/variation-orders/", response_model=VariationOrderResponse, status_code=201)
async def create_variation_order(
    data: VariationOrderCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("variations.create")),
    service: VariationsService = Depends(_get_service),
) -> VariationOrderResponse:
    await verify_project_access(data.project_id, user_id, session)
    vo = await service.create_order(data, user_id=user_id)
    return VariationOrderResponse.model_validate(vo)


@router.get("/variation-orders/{vo_id}", response_model=VariationOrderResponse)
async def get_variation_order(
    vo_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("variations.read")),
    service: VariationsService = Depends(_get_service),
) -> VariationOrderResponse:
    vo = await service.get_order(vo_id)
    await verify_project_access(vo.project_id, str(user_id), session)
    return VariationOrderResponse.model_validate(vo)


@router.patch("/variation-orders/{vo_id}", response_model=VariationOrderResponse)
async def update_variation_order(
    vo_id: uuid.UUID,
    data: VariationOrderUpdate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    user_payload: CurrentUserPayload = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("variations.update")),
    service: VariationsService = Depends(_get_service),
) -> VariationOrderResponse:
    existing = await service.get_order(vo_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    # A VariationOrder's final_cost_impact is the committed money. Changing it is
    # symmetric with approval and convert-to-VO, so a high-value value must clear
    # the same variations.approve_high_value gate. Without this an editor holding
    # only variations.update could inflate an issued VO's cost past the threshold
    # with no authorisation.
    if data.final_cost_impact is not None:
        ensure_high_value_authorised(data.final_cost_impact, payload=user_payload)
    vo = await service.update_order(vo_id, data, user_id=str(user_id) if user_id else None)
    return VariationOrderResponse.model_validate(vo)


@router.delete("/variation-orders/{vo_id}", status_code=204)
async def delete_variation_order(
    vo_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("variations.delete")),
    service: VariationsService = Depends(_get_service),
) -> None:
    existing = await service.get_order(vo_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    await service.delete_order(vo_id)


@router.post("/variation-orders/{vo_id}/start", response_model=VariationOrderResponse)
async def start_variation_order(
    vo_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("variations.update")),
    service: VariationsService = Depends(_get_service),
) -> VariationOrderResponse:
    existing = await service.get_order(vo_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    vo = await service.transition_variation_order(vo_id, "in_progress", user_id=user_id)
    return VariationOrderResponse.model_validate(vo)


@router.post("/variation-orders/{vo_id}/complete", response_model=VariationOrderResponse)
async def complete_variation_order(
    vo_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("variations.complete_vo")),
    service: VariationsService = Depends(_get_service),
) -> VariationOrderResponse:
    existing = await service.get_order(vo_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    vo = await service.transition_variation_order(vo_id, "completed", user_id=user_id)
    return VariationOrderResponse.model_validate(vo)


@router.post("/variation-orders/{vo_id}/void", response_model=VariationOrderResponse)
async def void_variation_order(
    vo_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("variations.delete")),
    service: VariationsService = Depends(_get_service),
) -> VariationOrderResponse:
    existing = await service.get_order(vo_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    vo = await service.transition_variation_order(vo_id, "voided", user_id=user_id)
    return VariationOrderResponse.model_validate(vo)


# ── Cost impacts ───────────────────────────────────────────────────────────


@router.post(
    "/variation-cost-impacts/",
    response_model=VariationCostImpactResponse,
    status_code=201,
)
async def create_cost_impact(
    data: VariationCostImpactCreate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("variations.update")),
    service: VariationsService = Depends(_get_service),
) -> VariationCostImpactResponse:
    vo = await service.get_order(data.variation_order_id)
    await verify_project_access(vo.project_id, str(user_id), session)
    row = await service.add_cost_impact(data)
    return VariationCostImpactResponse.model_validate(row)


@router.patch(
    "/variation-cost-impacts/{line_id}",
    response_model=VariationCostImpactResponse,
)
async def update_cost_impact(
    line_id: uuid.UUID,
    data: VariationCostImpactUpdate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("variations.update")),
    service: VariationsService = Depends(_get_service),
) -> VariationCostImpactResponse:
    project_id = await service.cost_impact_project_id(line_id)
    await verify_project_access(project_id, str(user_id), session)
    row = await service.update_cost_impact(line_id, data)
    return VariationCostImpactResponse.model_validate(row)


@router.delete("/variation-cost-impacts/{line_id}", status_code=204)
async def delete_cost_impact(
    line_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("variations.update")),
    service: VariationsService = Depends(_get_service),
) -> None:
    project_id = await service.cost_impact_project_id(line_id)
    await verify_project_access(project_id, str(user_id), session)
    await service.delete_cost_impact(line_id)


@router.post(
    "/variation-orders/{vo_id}/cost-impacts/bulk",
    response_model=list[VariationCostImpactResponse],
    status_code=201,
)
async def bulk_cost_impacts(
    vo_id: uuid.UUID,
    lines: list[VariationCostImpactCreate],
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("variations.update")),
    service: VariationsService = Depends(_get_service),
) -> list[VariationCostImpactResponse]:
    vo = await service.get_order(vo_id)
    await verify_project_access(vo.project_id, str(user_id), session)
    rows = await service.bulk_cost_impacts(vo_id, lines)
    return [VariationCostImpactResponse.model_validate(r) for r in rows]


# ── Schedule impacts ───────────────────────────────────────────────────────


@router.post(
    "/variation-schedule-impacts/",
    response_model=VariationScheduleImpactResponse,
    status_code=201,
)
async def create_schedule_impact(
    data: VariationScheduleImpactCreate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("variations.update")),
    service: VariationsService = Depends(_get_service),
) -> VariationScheduleImpactResponse:
    vo = await service.get_order(data.variation_order_id)
    await verify_project_access(vo.project_id, str(user_id), session)
    row = await service.add_schedule_impact(data)
    return VariationScheduleImpactResponse.model_validate(row)


@router.patch(
    "/variation-schedule-impacts/{line_id}",
    response_model=VariationScheduleImpactResponse,
)
async def update_schedule_impact(
    line_id: uuid.UUID,
    data: VariationScheduleImpactUpdate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("variations.update")),
    service: VariationsService = Depends(_get_service),
) -> VariationScheduleImpactResponse:
    project_id = await service.schedule_impact_project_id(line_id)
    await verify_project_access(project_id, str(user_id), session)
    row = await service.update_schedule_impact(line_id, data)
    return VariationScheduleImpactResponse.model_validate(row)


@router.delete("/variation-schedule-impacts/{line_id}", status_code=204)
async def delete_schedule_impact(
    line_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("variations.update")),
    service: VariationsService = Depends(_get_service),
) -> None:
    project_id = await service.schedule_impact_project_id(line_id)
    await verify_project_access(project_id, str(user_id), session)
    await service.delete_schedule_impact(line_id)


# ── Site measurements ─────────────────────────────────────────────────────


@router.get("/site-measurements/", response_model=SiteMeasurementListResponse)
async def list_site_measurements(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    _perm: None = Depends(RequirePermission("variations.read")),
    service: VariationsService = Depends(_get_service),
) -> SiteMeasurementListResponse:
    """A page of the project's site measurements, and how many there are.

    This route takes no status filter, so ``total`` is the project's whole
    measurement count.
    """
    await verify_project_access(project_id, user_id, session)
    rows, total = await service.site_measurement_repo.list_for_project(
        project_id,
        offset=offset,
        limit=limit,
    )
    return SiteMeasurementListResponse(
        items=[SiteMeasurementResponse.model_validate(r) for r in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post(
    "/site-measurements/",
    response_model=SiteMeasurementResponse,
    status_code=201,
)
async def create_site_measurement(
    data: SiteMeasurementCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("variations.create")),
    service: VariationsService = Depends(_get_service),
) -> SiteMeasurementResponse:
    await verify_project_access(data.project_id, user_id, session)
    sm = await service.record_site_measurement(data, user_id=user_id)
    return SiteMeasurementResponse.model_validate(sm)


@router.patch(
    "/site-measurements/{sm_id}",
    response_model=SiteMeasurementResponse,
)
async def update_site_measurement(
    sm_id: uuid.UUID,
    data: SiteMeasurementUpdate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("variations.update")),
    service: VariationsService = Depends(_get_service),
) -> SiteMeasurementResponse:
    existing = await service.get_site_measurement(sm_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    sm = await service.update_site_measurement(sm_id, data)
    return SiteMeasurementResponse.model_validate(sm)


@router.delete("/site-measurements/{sm_id}", status_code=204)
async def delete_site_measurement(
    sm_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("variations.delete")),
    service: VariationsService = Depends(_get_service),
) -> None:
    existing = await service.get_site_measurement(sm_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    await service.delete_site_measurement(sm_id)


@router.post(
    "/site-measurements/{sm_id}/agree",
    response_model=SiteMeasurementResponse,
)
async def agree_site_measurement(
    sm_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("variations.update")),
    service: VariationsService = Depends(_get_service),
) -> SiteMeasurementResponse:
    existing = await service.get_site_measurement(sm_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    sm = await service.agree_site_measurement(sm_id)
    return SiteMeasurementResponse.model_validate(sm)


# ── Daywork sheets ────────────────────────────────────────────────────────


@router.get("/daywork-sheets/", response_model=DayworkSheetListResponse)
async def list_daywork_sheets(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    status: str | None = Query(default=None),
    _perm: None = Depends(RequirePermission("variations.read")),
    service: VariationsService = Depends(_get_service),
) -> DayworkSheetListResponse:
    """A page of the project's daywork sheets, and how many there are.

    ``total`` counts the sheets matching ``status``, not the page.
    """
    await verify_project_access(project_id, user_id, session)
    rows, total = await service.daywork_repo.list_for_project(
        project_id,
        offset=offset,
        limit=limit,
        status=status,
    )
    return DayworkSheetListResponse(
        items=[DayworkSheetResponse.model_validate(r) for r in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post("/daywork-sheets/", response_model=DayworkSheetResponse, status_code=201)
async def create_daywork_sheet(
    data: DayworkSheetCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("variations.create")),
    service: VariationsService = Depends(_get_service),
) -> DayworkSheetResponse:
    await verify_project_access(data.project_id, user_id, session)
    ds = await service.create_daywork_sheet(data, user_id=user_id)
    return DayworkSheetResponse.model_validate(ds)


@router.patch("/daywork-sheets/{sheet_id}", response_model=DayworkSheetResponse)
async def update_daywork_sheet(
    sheet_id: uuid.UUID,
    data: DayworkSheetUpdate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("variations.update")),
    service: VariationsService = Depends(_get_service),
) -> DayworkSheetResponse:
    existing = await service.get_daywork_sheet(sheet_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    ds = await service.update_daywork_sheet(sheet_id, data)
    return DayworkSheetResponse.model_validate(ds)


@router.delete("/daywork-sheets/{sheet_id}", status_code=204)
async def delete_daywork_sheet(
    sheet_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("variations.delete")),
    service: VariationsService = Depends(_get_service),
) -> None:
    existing = await service.get_daywork_sheet(sheet_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    await service.delete_daywork_sheet(sheet_id)


@router.post("/daywork-sheets/{sheet_id}/sign", response_model=DayworkSheetResponse)
async def sign_daywork_sheet(
    sheet_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("variations.sign_daywork")),
    service: VariationsService = Depends(_get_service),
) -> DayworkSheetResponse:
    existing = await service.get_daywork_sheet(sheet_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    ds = await service.sign_daywork_sheet(sheet_id, signer_id=user_id)
    return DayworkSheetResponse.model_validate(ds)


@router.post("/daywork-sheets/{sheet_id}/dispute", response_model=DayworkSheetResponse)
async def dispute_daywork_sheet(
    sheet_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("variations.update")),
    service: VariationsService = Depends(_get_service),
) -> DayworkSheetResponse:
    existing = await service.get_daywork_sheet(sheet_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    ds = await service.transition_daywork(sheet_id, "disputed")
    return DayworkSheetResponse.model_validate(ds)


@router.post("/daywork-sheets/{sheet_id}/bill", response_model=DayworkSheetResponse)
async def bill_daywork_sheet(
    sheet_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("variations.update")),
    service: VariationsService = Depends(_get_service),
) -> DayworkSheetResponse:
    existing = await service.get_daywork_sheet(sheet_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    ds = await service.transition_daywork(sheet_id, "billed")
    return DayworkSheetResponse.model_validate(ds)


@router.post(
    "/daywork-sheet-lines/",
    response_model=DayworkSheetLineResponse,
    status_code=201,
)
async def create_daywork_line(
    data: DayworkSheetLineCreate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("variations.update")),
    service: VariationsService = Depends(_get_service),
) -> DayworkSheetLineResponse:
    sheet = await service.get_daywork_sheet(data.sheet_id)
    await verify_project_access(sheet.project_id, str(user_id), session)
    row = await service.add_daywork_line(data)
    return DayworkSheetLineResponse.model_validate(row)


@router.patch(
    "/daywork-sheet-lines/{line_id}",
    response_model=DayworkSheetLineResponse,
)
async def update_daywork_line(
    line_id: uuid.UUID,
    data: DayworkSheetLineUpdate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("variations.update")),
    service: VariationsService = Depends(_get_service),
) -> DayworkSheetLineResponse:
    project_id = await service.daywork_line_project_id(line_id)
    await verify_project_access(project_id, str(user_id), session)
    row = await service.update_daywork_line(line_id, data)
    return DayworkSheetLineResponse.model_validate(row)


@router.delete("/daywork-sheet-lines/{line_id}", status_code=204)
async def delete_daywork_line(
    line_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("variations.update")),
    service: VariationsService = Depends(_get_service),
) -> None:
    project_id = await service.daywork_line_project_id(line_id)
    await verify_project_access(project_id, str(user_id), session)
    await service.delete_daywork_line(line_id)


@router.post(
    "/daywork-sheets/{sheet_id}/lines/bulk",
    response_model=list[DayworkSheetLineResponse],
    status_code=201,
)
async def bulk_daywork_lines(
    sheet_id: uuid.UUID,
    lines: list[DayworkSheetLineCreate],
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("variations.update")),
    service: VariationsService = Depends(_get_service),
) -> list[DayworkSheetLineResponse]:
    sheet = await service.get_daywork_sheet(sheet_id)
    await verify_project_access(sheet.project_id, str(user_id), session)
    rows = await service.bulk_daywork_lines(sheet_id, lines)
    return [DayworkSheetLineResponse.model_validate(r) for r in rows]


# ── Disruption claims ─────────────────────────────────────────────────────


@router.get("/disruption-claims/", response_model=DisruptionClaimListResponse)
async def list_disruption_claims(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    status: str | None = Query(default=None),
    _perm: None = Depends(RequirePermission("variations.read")),
    service: VariationsService = Depends(_get_service),
) -> DisruptionClaimListResponse:
    """A page of the project's disruption claims, and how many there are.

    ``total`` counts the claims matching ``status``, not the page.
    """
    await verify_project_access(project_id, user_id, session)
    rows, total = await service.disruption_repo.list_for_project(
        project_id,
        offset=offset,
        limit=limit,
        status=status,
    )
    return DisruptionClaimListResponse(
        items=[DisruptionClaimResponse.model_validate(r) for r in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post(
    "/disruption-claims/",
    response_model=DisruptionClaimResponse,
    status_code=201,
)
async def create_disruption_claim(
    data: DisruptionClaimCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("variations.create")),
    service: VariationsService = Depends(_get_service),
) -> DisruptionClaimResponse:
    await verify_project_access(data.project_id, user_id, session)
    claim = await service.submit_disruption_claim(data, user_id=user_id)
    return DisruptionClaimResponse.model_validate(claim)


@router.patch(
    "/disruption-claims/{claim_id}",
    response_model=DisruptionClaimResponse,
)
async def update_disruption_claim(
    claim_id: uuid.UUID,
    data: DisruptionClaimUpdate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("variations.update")),
    service: VariationsService = Depends(_get_service),
) -> DisruptionClaimResponse:
    existing = await service.get_disruption_claim(claim_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    claim = await service.update_disruption_claim(claim_id, data)
    return DisruptionClaimResponse.model_validate(claim)


@router.delete("/disruption-claims/{claim_id}", status_code=204)
async def delete_disruption_claim(
    claim_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("variations.delete")),
    service: VariationsService = Depends(_get_service),
) -> None:
    existing = await service.get_disruption_claim(claim_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    await service.delete_disruption_claim(claim_id)


@router.post(
    "/disruption-claims/{claim_id}/submit",
    response_model=DisruptionClaimResponse,
)
async def submit_disruption_claim(
    claim_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("variations.submit_request")),
    service: VariationsService = Depends(_get_service),
) -> DisruptionClaimResponse:
    existing = await service.get_disruption_claim(claim_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    claim = await service.transition_disruption(claim_id, "submitted")
    return DisruptionClaimResponse.model_validate(claim)


@router.post(
    "/disruption-claims/{claim_id}/review",
    response_model=DisruptionClaimResponse,
)
async def review_disruption_claim(
    claim_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("variations.decide_claim")),
    service: VariationsService = Depends(_get_service),
) -> DisruptionClaimResponse:
    existing = await service.get_disruption_claim(claim_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    claim = await service.transition_disruption(claim_id, "under_review")
    return DisruptionClaimResponse.model_validate(claim)


@router.post(
    "/disruption-claims/{claim_id}/decide",
    response_model=DisruptionClaimResponse,
)
async def decide_disruption_claim(
    claim_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    body: _DecisionBody = Body(default=_DecisionBody()),
    decision: str = Query(default="agreed", pattern=r"^(agreed|rejected)$"),
    _perm: None = Depends(RequirePermission("variations.decide_claim")),
    service: VariationsService = Depends(_get_service),
) -> DisruptionClaimResponse:
    existing = await service.get_disruption_claim(claim_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    claim = await service.transition_disruption(
        claim_id,
        decision,
        decided_amount=body.decided_amount,
    )
    return DisruptionClaimResponse.model_validate(claim)


# ── EOT claims ────────────────────────────────────────────────────────────


@router.get("/eot-claims/", response_model=ExtensionOfTimeClaimListResponse)
async def list_eot_claims(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    status: str | None = Query(default=None),
    _perm: None = Depends(RequirePermission("variations.read")),
    service: VariationsService = Depends(_get_service),
) -> ExtensionOfTimeClaimListResponse:
    """A page of the project's EOT claims, and how many there are.

    ``total`` counts the claims matching ``status``, not the page.
    """
    await verify_project_access(project_id, user_id, session)
    rows, total = await service.eot_repo.list_for_project(
        project_id,
        offset=offset,
        limit=limit,
        status=status,
    )
    return ExtensionOfTimeClaimListResponse(
        items=[ExtensionOfTimeClaimResponse.model_validate(r) for r in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post(
    "/eot-claims/",
    response_model=ExtensionOfTimeClaimResponse,
    status_code=201,
)
async def create_eot_claim(
    data: ExtensionOfTimeClaimCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("variations.create")),
    service: VariationsService = Depends(_get_service),
) -> ExtensionOfTimeClaimResponse:
    await verify_project_access(data.project_id, user_id, session)
    claim = await service.submit_eot_claim(data, user_id=user_id)
    return ExtensionOfTimeClaimResponse.model_validate(claim)


@router.patch(
    "/eot-claims/{claim_id}",
    response_model=ExtensionOfTimeClaimResponse,
)
async def update_eot_claim(
    claim_id: uuid.UUID,
    data: ExtensionOfTimeClaimUpdate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("variations.update")),
    service: VariationsService = Depends(_get_service),
) -> ExtensionOfTimeClaimResponse:
    existing = await service.get_eot_claim(claim_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    claim = await service.update_eot_claim(claim_id, data)
    return ExtensionOfTimeClaimResponse.model_validate(claim)


@router.delete("/eot-claims/{claim_id}", status_code=204)
async def delete_eot_claim(
    claim_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("variations.delete")),
    service: VariationsService = Depends(_get_service),
) -> None:
    existing = await service.get_eot_claim(claim_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    await service.delete_eot_claim(claim_id)


@router.post(
    "/eot-claims/{claim_id}/submit",
    response_model=ExtensionOfTimeClaimResponse,
)
async def submit_eot_claim(
    claim_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("variations.submit_request")),
    service: VariationsService = Depends(_get_service),
) -> ExtensionOfTimeClaimResponse:
    existing = await service.get_eot_claim(claim_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    claim = await service.transition_eot(claim_id, "submitted")
    return ExtensionOfTimeClaimResponse.model_validate(claim)


@router.post(
    "/eot-claims/{claim_id}/review",
    response_model=ExtensionOfTimeClaimResponse,
)
async def review_eot_claim(
    claim_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("variations.decide_claim")),
    service: VariationsService = Depends(_get_service),
) -> ExtensionOfTimeClaimResponse:
    existing = await service.get_eot_claim(claim_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    claim = await service.transition_eot(claim_id, "under_review")
    return ExtensionOfTimeClaimResponse.model_validate(claim)


@router.post(
    "/eot-claims/{claim_id}/grant",
    response_model=ExtensionOfTimeClaimResponse,
)
async def grant_eot_claim(
    claim_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    body: _DecisionBody = Body(default=_DecisionBody()),
    _perm: None = Depends(RequirePermission("variations.decide_claim")),
    service: VariationsService = Depends(_get_service),
) -> ExtensionOfTimeClaimResponse:
    existing = await service.get_eot_claim(claim_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    claim = await service.transition_eot(
        claim_id,
        "granted",
        granted_days=body.granted_days,
        decision_notes=body.decision_notes,
    )
    return ExtensionOfTimeClaimResponse.model_validate(claim)


@router.post(
    "/eot-claims/{claim_id}/reject",
    response_model=ExtensionOfTimeClaimResponse,
)
async def reject_eot_claim(
    claim_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    body: _DecisionBody = Body(default=_DecisionBody()),
    _perm: None = Depends(RequirePermission("variations.decide_claim")),
    service: VariationsService = Depends(_get_service),
) -> ExtensionOfTimeClaimResponse:
    existing = await service.get_eot_claim(claim_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    claim = await service.transition_eot(
        claim_id,
        "rejected",
        decision_notes=body.decision_notes,
    )
    return ExtensionOfTimeClaimResponse.model_validate(claim)


# ── Final account ─────────────────────────────────────────────────────────


@router.get("/final-accounts/", response_model=list[FinalAccountResponse])
async def list_final_accounts(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("variations.read")),
    service: VariationsService = Depends(_get_service),
) -> list[FinalAccountResponse]:
    await verify_project_access(project_id, user_id, session)
    fa = await service.final_account_repo.for_project(project_id)
    return [FinalAccountResponse.model_validate(fa)] if fa is not None else []


@router.post(
    "/final-accounts/",
    response_model=FinalAccountResponse,
    status_code=201,
)
async def create_final_account(
    data: FinalAccountCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("variations.create")),
    service: VariationsService = Depends(_get_service),
) -> FinalAccountResponse:
    await verify_project_access(data.project_id, user_id, session)
    fa = await service.create_final_account(data)
    return FinalAccountResponse.model_validate(fa)


@router.get("/final-accounts/{fa_id}", response_model=FinalAccountResponse)
async def get_final_account(
    fa_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("variations.read")),
    service: VariationsService = Depends(_get_service),
) -> FinalAccountResponse:
    fa = await service.get_final_account(fa_id)
    await verify_project_access(fa.project_id, str(user_id), session)
    return FinalAccountResponse.model_validate(fa)


@router.patch("/final-accounts/{fa_id}", response_model=FinalAccountResponse)
async def update_final_account(
    fa_id: uuid.UUID,
    data: FinalAccountUpdate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("variations.update")),
    service: VariationsService = Depends(_get_service),
) -> FinalAccountResponse:
    existing = await service.get_final_account(fa_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    fa = await service.update_final_account(fa_id, data)
    return FinalAccountResponse.model_validate(fa)


@router.delete("/final-accounts/{fa_id}", status_code=204)
async def delete_final_account(
    fa_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("variations.delete")),
    service: VariationsService = Depends(_get_service),
) -> None:
    fa = await service.get_final_account(fa_id)
    await verify_project_access(fa.project_id, str(user_id), session)
    await service.final_account_repo.delete(fa.id)


@router.post(
    "/final-accounts/{fa_id}/close",
    response_model=FinalAccountResponse,
)
async def close_final_account(
    fa_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("variations.close_final_account")),
    service: VariationsService = Depends(_get_service),
) -> FinalAccountResponse:
    existing = await service.get_final_account(fa_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    fa = await service.close_final_account(fa_id, signer_id=user_id)
    return FinalAccountResponse.model_validate(fa)


# ── Dashboard ─────────────────────────────────────────────────────────────


@router.get(
    "/dashboard/project/{project_id}",
    response_model=VariationDashboardResponse,
)
async def variation_dashboard(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("variations.read")),
    service: VariationsService = Depends(_get_service),
) -> VariationDashboardResponse:
    await verify_project_access(project_id, user_id, session)
    summary = await service.get_dashboard(project_id)
    return VariationDashboardResponse(**summary)


# ── Contract clauses (FIDIC / JCT / NEC4) ─────────────────────────────────


@router.get("/contract-standards", response_model=list[str])
async def list_contract_standards(
    _perm: None = Depends(RequirePermission("variations.read")),
) -> list[str]:
    """Return supported contract standards for variation clause stamping."""
    return supported_contract_standards()


@router.get(
    "/requests/{vr_id}/nec4-timer",
    response_model=NEC4TimerStatusResponse,
)
async def nec4_timer_status(
    vr_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("variations.read")),
    service: VariationsService = Depends(_get_service),
) -> NEC4TimerStatusResponse:
    """Return overdue flags for the NEC4 quotation/assessment SLA."""
    vr = await service.get_request(vr_id)
    await verify_project_access(vr.project_id, user_id, session)
    flags = is_nec4_overdue(vr)
    return NEC4TimerStatusResponse(
        request_id=vr.id,
        contract_standard=getattr(vr, "contract_standard", "") or "",
        contract_clause_ref=getattr(vr, "contract_clause_ref", "") or "",
        quotation_due_at=getattr(vr, "quotation_due_at", None),
        assessment_due_at=getattr(vr, "assessment_due_at", None),
        quotation_overdue=flags["quotation_overdue"],
        assessment_overdue=flags["assessment_overdue"],
    )


# ── EOT TIA ───────────────────────────────────────────────────────────────


@router.post(
    "/eot-claims/{claim_id}/tia",
    response_model=ExtensionOfTimeClaimResponse,
)
async def record_eot_tia(
    claim_id: uuid.UUID,
    data: EOTTIARecordRequest,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("variations.update")),
    service: VariationsService = Depends(_get_service),
) -> ExtensionOfTimeClaimResponse:
    """Stamp a Time-Impact-Analysis result onto an EoT claim."""
    claim = await service.get_eot_claim(claim_id)
    await verify_project_access(claim.project_id, user_id, session)
    updated = await service.record_eot_tia(
        claim_id,
        data.tia_delta_days,
        data.critical_path_impact,
    )
    return ExtensionOfTimeClaimResponse.model_validate(updated)
