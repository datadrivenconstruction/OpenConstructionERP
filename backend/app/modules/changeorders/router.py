"""‌⁠‍Change Orders API routes.

Endpoints:
    POST   /                       - Create change order
    GET    /?project_id=X          - List for project
    GET    /{id}                   - Get with items
    PATCH  /{id}                   - Update
    DELETE /{id}                   - Delete
    POST   /{id}/items             - Add item
    PATCH  /{id}/items/{item_id}   - Update item
    DELETE /{id}/items/{item_id}   - Delete item
    POST   /{id}/submit            - Change status to submitted
    POST   /{id}/approve           - Change status to approved
    POST   /{id}/reject            - Change status to rejected
    GET    /summary?project_id=X   - Aggregated stats
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.rate_limiter import approval_limiter
from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.changeorders.schemas import (
    AIDraftRequest,
    AIDraftResponse,
    ApprovalAdvanceRequest,
    ApprovalRow,
    ApprovalStartRequest,
    ChangeOrderCreate,
    ChangeOrderItemCreate,
    ChangeOrderItemResponse,
    ChangeOrderItemUpdate,
    ChangeOrderResponse,
    ChangeOrderSummary,
    ChangeOrderUpdate,
    ChangeOrderWithItems,
    SimulateImpactRequest,
    SimulateImpactResponse,
)
from app.modules.changeorders.service import ChangeOrderService

router = APIRouter(tags=["changeorders"])
logger = logging.getLogger(__name__)


def _get_service(session: SessionDep) -> ChangeOrderService:
    return ChangeOrderService(session)


def _order_to_response(order: object) -> ChangeOrderResponse:
    """‌⁠‍Build a ChangeOrderResponse from a ChangeOrder ORM object."""
    # `items` may not be eager-loaded in async context - only attempt to access
    # if the relationship was populated upstream (via selectinload or similar).
    # Returning an empty list when unloaded is intentional: this response type
    # only uses `item_count`, not the items themselves.
    try:
        items = list(order.items)  # type: ignore[attr-defined]
    except Exception as exc:
        import logging

        logging.getLogger(__name__).debug("ChangeOrder items not loaded for response: %s", exc)
        items = []
    return ChangeOrderResponse(
        id=order.id,  # type: ignore[attr-defined]
        project_id=order.project_id,  # type: ignore[attr-defined]
        code=order.code,  # type: ignore[attr-defined]
        title=order.title,  # type: ignore[attr-defined]
        description=order.description,  # type: ignore[attr-defined]
        reason_category=order.reason_category,  # type: ignore[attr-defined]
        status=order.status,  # type: ignore[attr-defined]
        submitted_by=order.submitted_by,  # type: ignore[attr-defined]
        approved_by=order.approved_by,  # type: ignore[attr-defined]
        rejected_by=getattr(order, "rejected_by", None),  # type: ignore[attr-defined]
        submitted_at=order.submitted_at,  # type: ignore[attr-defined]
        approved_at=order.approved_at,  # type: ignore[attr-defined]
        rejected_at=getattr(order, "rejected_at", None),  # type: ignore[attr-defined]
        cost_impact=str(order.cost_impact),  # type: ignore[attr-defined]
        schedule_impact_days=order.schedule_impact_days,  # type: ignore[attr-defined]
        currency=order.currency,  # type: ignore[attr-defined]
        metadata=getattr(order, "metadata_", {}),  # type: ignore[attr-defined]
        created_at=order.created_at,  # type: ignore[attr-defined]
        updated_at=order.updated_at,  # type: ignore[attr-defined]
        item_count=len(items),
        linked_po_ids=[str(x) for x in (getattr(order, "linked_po_ids", None) or [])],
        linked_rfi_ids=[str(x) for x in (getattr(order, "linked_rfi_ids", None) or [])],
        current_approval_step=getattr(order, "current_approval_step", None),
    )


def _order_to_with_items(order: object) -> ChangeOrderWithItems:
    """‌⁠‍Build a ChangeOrderWithItems from a ChangeOrder ORM object."""
    try:
        items = list(order.items)  # type: ignore[attr-defined]
    except Exception:
        items = []
    return ChangeOrderWithItems(
        id=order.id,  # type: ignore[attr-defined]
        project_id=order.project_id,  # type: ignore[attr-defined]
        code=order.code,  # type: ignore[attr-defined]
        title=order.title,  # type: ignore[attr-defined]
        description=order.description,  # type: ignore[attr-defined]
        reason_category=order.reason_category,  # type: ignore[attr-defined]
        status=order.status,  # type: ignore[attr-defined]
        submitted_by=order.submitted_by,  # type: ignore[attr-defined]
        approved_by=order.approved_by,  # type: ignore[attr-defined]
        rejected_by=getattr(order, "rejected_by", None),  # type: ignore[attr-defined]
        submitted_at=order.submitted_at,  # type: ignore[attr-defined]
        approved_at=order.approved_at,  # type: ignore[attr-defined]
        rejected_at=getattr(order, "rejected_at", None),  # type: ignore[attr-defined]
        cost_impact=str(order.cost_impact),  # type: ignore[attr-defined]
        schedule_impact_days=order.schedule_impact_days,  # type: ignore[attr-defined]
        currency=order.currency,  # type: ignore[attr-defined]
        metadata=getattr(order, "metadata_", {}),  # type: ignore[attr-defined]
        created_at=order.created_at,  # type: ignore[attr-defined]
        updated_at=order.updated_at,  # type: ignore[attr-defined]
        item_count=len(items),
        linked_po_ids=[str(x) for x in (getattr(order, "linked_po_ids", None) or [])],
        linked_rfi_ids=[str(x) for x in (getattr(order, "linked_rfi_ids", None) or [])],
        current_approval_step=getattr(order, "current_approval_step", None),
        items=[
            ChangeOrderItemResponse(
                id=item.id,
                change_order_id=item.change_order_id,
                description=item.description,
                change_type=item.change_type,
                original_quantity=str(item.original_quantity),
                new_quantity=str(item.new_quantity),
                original_rate=str(item.original_rate),
                new_rate=str(item.new_rate),
                cost_delta=str(item.cost_delta),
                unit=item.unit,
                sort_order=item.sort_order,
                metadata=getattr(item, "metadata_", {}),
                created_at=item.created_at,
                updated_at=item.updated_at,
            )
            for item in items
        ],
    )


def _item_to_response(item: object) -> ChangeOrderItemResponse:
    """Build a ChangeOrderItemResponse from a ChangeOrderItem ORM object."""
    return ChangeOrderItemResponse(
        id=item.id,  # type: ignore[attr-defined]
        change_order_id=item.change_order_id,  # type: ignore[attr-defined]
        description=item.description,  # type: ignore[attr-defined]
        change_type=item.change_type,  # type: ignore[attr-defined]
        original_quantity=str(item.original_quantity),  # type: ignore[attr-defined]
        new_quantity=str(item.new_quantity),  # type: ignore[attr-defined]
        original_rate=str(item.original_rate),  # type: ignore[attr-defined]
        new_rate=str(item.new_rate),  # type: ignore[attr-defined]
        cost_delta=str(item.cost_delta),  # type: ignore[attr-defined]
        unit=item.unit,  # type: ignore[attr-defined]
        sort_order=item.sort_order,  # type: ignore[attr-defined]
        metadata=getattr(item, "metadata_", {}),  # type: ignore[attr-defined]
        created_at=item.created_at,  # type: ignore[attr-defined]
        updated_at=item.updated_at,  # type: ignore[attr-defined]
    )


# ── Summary ──────────────────────────────────────────────────────────────────


@router.get(
    "/summary/",
    response_model=ChangeOrderSummary,
    dependencies=[Depends(RequirePermission("changeorders.read"))],
)
async def get_summary(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: ChangeOrderService = Depends(_get_service),
) -> ChangeOrderSummary:
    """Aggregated change order stats for a project."""
    await verify_project_access(project_id, str(user_id), session)
    data = await service.get_summary(project_id)
    return ChangeOrderSummary(**data)


# ── Create ───────────────────────────────────────────────────────────────────


@router.post("/", response_model=ChangeOrderResponse, status_code=201)
async def create_change_order(
    data: ChangeOrderCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("changeorders.create")),
    service: ChangeOrderService = Depends(_get_service),
) -> ChangeOrderResponse:
    """Create a new change order.

    R7 audit: the legacy POST trusted the ``project_id`` field on the
    payload and would happily create a change order on any project whose
    UUID the caller could guess - silently leaking cost / schedule data
    across tenants on subsequent reads. Now gated through
    ``verify_project_access`` which returns 404 on both "missing" and
    "not owned" so we don't leak existence either.
    """
    await verify_project_access(data.project_id, str(user_id), session)
    try:
        order = await service.create_order(data)
        return _order_to_response(order)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to create change order")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create change order",
        )


# ── List ─────────────────────────────────────────────────────────────────────


@router.get(
    "/",
    response_model=list[ChangeOrderResponse],
    dependencies=[Depends(RequirePermission("changeorders.read"))],
)
async def list_change_orders(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status"),
    service: ChangeOrderService = Depends(_get_service),
) -> list[ChangeOrderResponse]:
    """List change orders.

    If ``project_id`` is supplied we verify the caller owns/admins that project
    before returning anything - earlier the route trusted the path parameter
    and silently leaked change-order data across tenants. When omitted we scope
    to every project the caller owns, matching the sibling-module convention
    and avoiding the 422 that fresh installs hit before any project exists.
    """
    if project_id is None:
        orders, _ = await service.list_orders_for_owner(
            uuid.UUID(str(user_id)),
            offset=offset,
            limit=limit,
            status_filter=status_filter,
        )
    else:
        await verify_project_access(project_id, str(user_id), session)
        orders, _ = await service.list_orders(project_id, offset=offset, limit=limit, status_filter=status_filter)
    return [_order_to_response(o) for o in orders]


# ── Get ──────────────────────────────────────────────────────────────────────


@router.get("/{order_id}", response_model=ChangeOrderWithItems)
async def get_change_order(
    order_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("changeorders.read")),
    service: ChangeOrderService = Depends(_get_service),
) -> ChangeOrderWithItems:
    """Get change order with all items.

    R8 audit: the legacy GET /{order_id} lacked a RequirePermission gate -
    only verify_project_access ran, meaning any authenticated user could
    read a CO on a project they owned regardless of their CO-module role.
    Now gated on ``changeorders.read`` (viewer+) for consistency with the
    list endpoint.
    """
    order = await service.get_order(order_id)
    await verify_project_access(order.project_id, str(user_id), session)
    return _order_to_with_items(order)


# ── Update ───────────────────────────────────────────────────────────────────


@router.patch("/{order_id}", response_model=ChangeOrderResponse)
async def update_change_order(
    order_id: uuid.UUID,
    data: ChangeOrderUpdate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("changeorders.update")),
    service: ChangeOrderService = Depends(_get_service),
) -> ChangeOrderResponse:
    """Update a change order (draft only)."""
    existing = await service.get_order(order_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    order = await service.update_order(order_id, data)
    return _order_to_response(order)


# ── Delete ───────────────────────────────────────────────────────────────────


@router.delete("/{order_id}", status_code=204)
async def delete_change_order(
    order_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("changeorders.delete")),
    service: ChangeOrderService = Depends(_get_service),
) -> None:
    """Delete a change order (draft only)."""
    existing = await service.get_order(order_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    await service.delete_order(order_id)


# ── Items ────────────────────────────────────────────────────────────────────


@router.post("/{order_id}/items/", response_model=ChangeOrderItemResponse, status_code=201)
async def add_item(
    order_id: uuid.UUID,
    data: ChangeOrderItemCreate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("changeorders.update")),
    service: ChangeOrderService = Depends(_get_service),
) -> ChangeOrderItemResponse:
    """Add an item to a change order."""
    existing = await service.get_order(order_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    item = await service.add_item(order_id, data)
    return _item_to_response(item)


@router.patch("/{order_id}/items/{item_id}", response_model=ChangeOrderItemResponse)
async def update_item(
    order_id: uuid.UUID,
    item_id: uuid.UUID,
    data: ChangeOrderItemUpdate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("changeorders.update")),
    service: ChangeOrderService = Depends(_get_service),
) -> ChangeOrderItemResponse:
    """Update an item in a change order."""
    existing = await service.get_order(order_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    item = await service.update_item(order_id, item_id, data)
    return _item_to_response(item)


@router.delete("/{order_id}/items/{item_id}", status_code=204)
async def delete_item(
    order_id: uuid.UUID,
    item_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("changeorders.update")),
    service: ChangeOrderService = Depends(_get_service),
) -> None:
    """Delete an item from a change order."""
    existing = await service.get_order(order_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    await service.delete_item(order_id, item_id)


# ── Status transitions ──────────────────────────────────────────────────────


@router.post("/{order_id}/submit/", response_model=ChangeOrderResponse)
async def submit_order(
    order_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("changeorders.update")),
    service: ChangeOrderService = Depends(_get_service),
) -> ChangeOrderResponse:
    """Submit a change order for approval."""
    existing = await service.get_order(order_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    order = await service.submit_order(order_id, user_id)
    return _order_to_response(order)


@router.post("/{order_id}/approve/", response_model=ChangeOrderResponse)
async def approve_order(
    order_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    boq_id: uuid.UUID | None = Query(default=None),
    _perm: None = Depends(RequirePermission("changeorders.approve")),
    service: ChangeOrderService = Depends(_get_service),
) -> ChangeOrderResponse:
    """Approve a submitted change order."""
    existing = await service.get_order(order_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    allowed, _ = approval_limiter.is_allowed(str(user_id))
    if not allowed:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Rate limit exceeded. Try again later.")
    order = await service.approve_order(order_id, user_id, boq_id=boq_id)
    return _order_to_response(order)


@router.post("/{order_id}/reject/", response_model=ChangeOrderResponse)
async def reject_order(
    order_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("changeorders.approve")),
    service: ChangeOrderService = Depends(_get_service),
) -> ChangeOrderResponse:
    """Reject a submitted change order."""
    existing = await service.get_order(order_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    order = await service.reject_order(order_id, user_id)
    return _order_to_response(order)


@router.post("/{order_id}/execute/", response_model=ChangeOrderResponse)
async def execute_order(
    order_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("changeorders.update")),
    service: ChangeOrderService = Depends(_get_service),
) -> ChangeOrderResponse:
    """Mark an approved change order as executed (work completed on site).

    R8 audit: the ``executed`` terminal state existed in the service FSM
    (``approved`` → ``executed``) but had no router endpoint - leaving
    approved COs permanently stuck at that status and making the
    ``executed`` distinction invisible to project controllers. Callers
    need ``changeorders.update`` (editor-level) because execution is an
    operational milestone, not an approval decision.
    """
    existing = await service.get_order(order_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    order = await service.execute_order(order_id, user_id)
    return _order_to_response(order)


# ── T3: construction management platform style multi-step approval chain ────


def _approval_to_response(row: object) -> ApprovalRow:
    """Build an :class:`ApprovalRow` from a ChangeOrderApproval ORM object."""
    return ApprovalRow(
        id=row.id,  # type: ignore[attr-defined]
        change_order_id=row.change_order_id,  # type: ignore[attr-defined]
        step_order=row.step_order,  # type: ignore[attr-defined]
        approver_user_id=row.approver_user_id,  # type: ignore[attr-defined]
        decision=row.decision,  # type: ignore[attr-defined]
        decided_at=row.decided_at,  # type: ignore[attr-defined]
        comments=row.comments,  # type: ignore[attr-defined]
        created_at=row.created_at,  # type: ignore[attr-defined]
    )


@router.post(
    "/{order_id}/approval-chain",
    response_model=list[ApprovalRow],
    status_code=201,
)
async def start_approval_chain(
    order_id: uuid.UUID,
    data: ApprovalStartRequest,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("changeorders.approve")),
    service: ChangeOrderService = Depends(_get_service),
) -> list[ApprovalRow]:
    """Start a sequential construction management platform style approval chain on a change order.

    Requires ``changeorders.approve`` so that an arbitrary editor can't
    hand-pick their own approver list and shortcut the four-eyes
    principle. The chain can only be started on a CO that has already
    been submitted; see ``ChangeOrderService.start_approval_chain``
    for the full state model.
    """
    existing = await service.get_order(order_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    rows = await service.start_approval_chain(order_id, list(data.approver_user_ids))
    return [_approval_to_response(r) for r in rows]


@router.post(
    "/{order_id}/advance-approval",
    response_model=ApprovalRow,
)
async def advance_approval(
    order_id: uuid.UUID,
    data: ApprovalAdvanceRequest,
    user_id: CurrentUserId,
    session: SessionDep,
    service: ChangeOrderService = Depends(_get_service),
) -> ApprovalRow:
    """Record the calling user's decision on the active chain step.

    The caller is identified from the JWT and must be the approver
    assigned to the step pointed at by ``co.current_approval_step``;
    any other user gets 403. No additional ``changeorders.approve``
    role check is applied - being named as an approver in a chain
    is itself the authorisation.
    """
    existing = await service.get_order(order_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    row = await service.advance_approval(order_id, str(user_id), data.decision, data.comments)
    return _approval_to_response(row)


@router.get(
    "/{order_id}/approvals",
    response_model=list[ApprovalRow],
    dependencies=[Depends(RequirePermission("changeorders.read"))],
)
async def get_approvals(
    order_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: ChangeOrderService = Depends(_get_service),
) -> list[ApprovalRow]:
    """Return the approval-chain rows for a change order in step order."""
    existing = await service.get_order(order_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    rows = await service.list_approvals(order_id)
    return [_approval_to_response(r) for r in rows]


# ── What-If impact simulator + AI draft (TOP-30 #11) ─────────────────────────


@router.post(
    "/{order_id}/simulate-impact/",
    response_model=SimulateImpactResponse,
)
async def simulate_impact(
    order_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    payload: SimulateImpactRequest | None = None,
    _perm: None = Depends(RequirePermission("changeorders.read")),
    service: ChangeOrderService = Depends(_get_service),
) -> SimulateImpactResponse:
    """Project a change order's cost, schedule, EVM and BOQ effect (read-only).

    Nothing is persisted. With an empty body it forecasts the CO as it stands;
    supplying ``cost_impact`` / ``schedule_impact_days`` runs a what-if with
    those overrides so a reviewer can model an alternative before approving.
    """
    existing = await service.get_order(order_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    body = payload or SimulateImpactRequest()
    result = await service.simulate_impact(
        order_id,
        cost_override=body.cost_impact,
        schedule_override=body.schedule_impact_days,
    )
    return SimulateImpactResponse(**result)


@router.post(
    "/{order_id}/publish-scenario/",
    response_model=ChangeOrderResponse,
)
async def publish_scenario(
    order_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    payload: SimulateImpactRequest | None = None,
    _perm: None = Depends(RequirePermission("changeorders.update")),
    service: ChangeOrderService = Depends(_get_service),
) -> ChangeOrderResponse:
    """Snapshot the current what-if projection into the CO audit trail.

    Re-runs the projection server-side (so the stored snapshot can never be
    spoofed by the client) and appends it to the change order's metadata,
    keeping the last 10 scenarios.
    """
    existing = await service.get_order(order_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    body = payload or SimulateImpactRequest()
    snapshot = await service.simulate_impact(
        order_id,
        cost_override=body.cost_impact,
        schedule_override=body.schedule_impact_days,
    )
    order = await service.publish_scenario(order_id, snapshot)
    return _order_to_response(order)


@router.post(
    "/ai-draft/",
    response_model=AIDraftResponse,
)
async def ai_draft_change_order(
    payload: AIDraftRequest,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("changeorders.create")),
    service: ChangeOrderService = Depends(_get_service),
) -> AIDraftResponse:
    """Draft a change order from source text (AI when a key is set, else heuristic).

    The response is a review-ready proposal - it is never saved. The caller
    reviews or edits it, then creates the change order through the normal
    create endpoint. Requires ``changeorders.create`` since it is the first
    step of authoring one.
    """
    await verify_project_access(payload.project_id, str(user_id), session)
    result = await service.ai_draft(
        project_id=payload.project_id,
        source_kind=payload.source_kind,
        source_text=payload.source_text,
        source_id=payload.source_id,
        currency=payload.currency,
        user_id=user_id,
    )
    return AIDraftResponse(**result)
