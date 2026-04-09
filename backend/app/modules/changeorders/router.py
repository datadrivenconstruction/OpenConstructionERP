"""Change Orders API routes.

Endpoints:
    POST   /                       — Create change order
    GET    /?project_id=X          — List for project
    GET    /{id}                   — Get with items
    PATCH  /{id}                   — Update
    DELETE /{id}                   — Delete
    POST   /{id}/items             — Add item
    PATCH  /{id}/items/{item_id}   — Update item
    DELETE /{id}/items/{item_id}   — Delete item
    POST   /{id}/submit            — Change status to submitted
    POST   /{id}/approve           — Change status to approved
    POST   /{id}/reject            — Change status to rejected
    GET    /summary?project_id=X   — Aggregated stats
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.changeorders.schemas import (
    ChangeOrderCreate,
    ChangeOrderItemCreate,
    ChangeOrderItemResponse,
    ChangeOrderItemUpdate,
    ChangeOrderResponse,
    ChangeOrderSummary,
    ChangeOrderUpdate,
    ChangeOrderWithItems,
)
from app.modules.changeorders.service import ChangeOrderService

router = APIRouter()
logger = logging.getLogger(__name__)


def _get_service(session: SessionDep) -> ChangeOrderService:
    return ChangeOrderService(session)


def _order_to_response(order: object) -> ChangeOrderResponse:
    """Build a ChangeOrderResponse from a ChangeOrder ORM object."""
    try:
        items = list(order.items)  # type: ignore[attr-defined]
    except Exception:
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
        submitted_at=order.submitted_at,  # type: ignore[attr-defined]
        approved_at=order.approved_at,  # type: ignore[attr-defined]
        cost_impact=float(order.cost_impact),  # type: ignore[attr-defined]
        schedule_impact_days=order.schedule_impact_days,  # type: ignore[attr-defined]
        currency=order.currency,  # type: ignore[attr-defined]
        metadata=getattr(order, "metadata_", {}),  # type: ignore[attr-defined]
        created_at=order.created_at,  # type: ignore[attr-defined]
        updated_at=order.updated_at,  # type: ignore[attr-defined]
        item_count=len(items),
    )


def _order_to_with_items(order: object) -> ChangeOrderWithItems:
    """Build a ChangeOrderWithItems from a ChangeOrder ORM object."""
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
        submitted_at=order.submitted_at,  # type: ignore[attr-defined]
        approved_at=order.approved_at,  # type: ignore[attr-defined]
        cost_impact=float(order.cost_impact),  # type: ignore[attr-defined]
        schedule_impact_days=order.schedule_impact_days,  # type: ignore[attr-defined]
        currency=order.currency,  # type: ignore[attr-defined]
        metadata=getattr(order, "metadata_", {}),  # type: ignore[attr-defined]
        created_at=order.created_at,  # type: ignore[attr-defined]
        updated_at=order.updated_at,  # type: ignore[attr-defined]
        item_count=len(items),
        items=[
            ChangeOrderItemResponse(
                id=item.id,
                change_order_id=item.change_order_id,
                description=item.description,
                change_type=item.change_type,
                original_quantity=float(item.original_quantity),
                new_quantity=float(item.new_quantity),
                original_rate=float(item.original_rate),
                new_rate=float(item.new_rate),
                cost_delta=float(item.cost_delta),
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
        original_quantity=float(item.original_quantity),  # type: ignore[attr-defined]
        new_quantity=float(item.new_quantity),  # type: ignore[attr-defined]
        original_rate=float(item.original_rate),  # type: ignore[attr-defined]
        new_rate=float(item.new_rate),  # type: ignore[attr-defined]
        cost_delta=float(item.cost_delta),  # type: ignore[attr-defined]
        unit=item.unit,  # type: ignore[attr-defined]
        sort_order=item.sort_order,  # type: ignore[attr-defined]
        metadata=getattr(item, "metadata_", {}),  # type: ignore[attr-defined]
        created_at=item.created_at,  # type: ignore[attr-defined]
        updated_at=item.updated_at,  # type: ignore[attr-defined]
    )


# ── Summary ──────────────────────────────────────────────────────────────────


@router.get("/summary/", response_model=ChangeOrderSummary)
async def get_summary(
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: ChangeOrderService = Depends(_get_service),
) -> ChangeOrderSummary:
    """Aggregated change order stats for a project."""
    data = await service.get_summary(project_id)
    return ChangeOrderSummary(**data)


# ── Create ───────────────────────────────────────────────────────────────────


@router.post("/", response_model=ChangeOrderResponse, status_code=201)
async def create_change_order(
    data: ChangeOrderCreate,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("changeorders.create")),
    service: ChangeOrderService = Depends(_get_service),
) -> ChangeOrderResponse:
    """Create a new change order."""
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


@router.get("/", response_model=list[ChangeOrderResponse])
async def list_change_orders(
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status"),
    service: ChangeOrderService = Depends(_get_service),
) -> list[ChangeOrderResponse]:
    """List change orders for a project."""
    orders, _ = await service.list_orders(project_id, offset=offset, limit=limit, status_filter=status_filter)
    return [_order_to_response(o) for o in orders]


# ── Get ──────────────────────────────────────────────────────────────────────


@router.get("/{order_id}", response_model=ChangeOrderWithItems)
async def get_change_order(
    order_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: ChangeOrderService = Depends(_get_service),
) -> ChangeOrderWithItems:
    """Get change order with all items."""
    order = await service.get_order(order_id)
    return _order_to_with_items(order)


# ── Update ───────────────────────────────────────────────────────────────────


@router.patch("/{order_id}", response_model=ChangeOrderResponse)
async def update_change_order(
    order_id: uuid.UUID,
    data: ChangeOrderUpdate,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("changeorders.update")),
    service: ChangeOrderService = Depends(_get_service),
) -> ChangeOrderResponse:
    """Update a change order (draft only)."""
    order = await service.update_order(order_id, data)
    return _order_to_response(order)


# ── Delete ───────────────────────────────────────────────────────────────────


@router.delete("/{order_id}", status_code=204)
async def delete_change_order(
    order_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("changeorders.delete")),
    service: ChangeOrderService = Depends(_get_service),
) -> None:
    """Delete a change order (draft only)."""
    await service.delete_order(order_id)


# ── Items ────────────────────────────────────────────────────────────────────


@router.post("/{order_id}/items/", response_model=ChangeOrderItemResponse, status_code=201)
async def add_item(
    order_id: uuid.UUID,
    data: ChangeOrderItemCreate,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("changeorders.update")),
    service: ChangeOrderService = Depends(_get_service),
) -> ChangeOrderItemResponse:
    """Add an item to a change order."""
    item = await service.add_item(order_id, data)
    return _item_to_response(item)


@router.patch("/{order_id}/items/{item_id}", response_model=ChangeOrderItemResponse)
async def update_item(
    order_id: uuid.UUID,
    item_id: uuid.UUID,
    data: ChangeOrderItemUpdate,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("changeorders.update")),
    service: ChangeOrderService = Depends(_get_service),
) -> ChangeOrderItemResponse:
    """Update an item in a change order."""
    item = await service.update_item(order_id, item_id, data)
    return _item_to_response(item)


@router.delete("/{order_id}/items/{item_id}", status_code=204)
async def delete_item(
    order_id: uuid.UUID,
    item_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("changeorders.update")),
    service: ChangeOrderService = Depends(_get_service),
) -> None:
    """Delete an item from a change order."""
    await service.delete_item(order_id, item_id)


# ── Status transitions ──────────────────────────────────────────────────────


@router.post("/{order_id}/submit/", response_model=ChangeOrderResponse)
async def submit_order(
    order_id: uuid.UUID,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("changeorders.update")),
    service: ChangeOrderService = Depends(_get_service),
) -> ChangeOrderResponse:
    """Submit a change order for approval."""
    order = await service.submit_order(order_id, user_id)
    return _order_to_response(order)


@router.post("/{order_id}/approve/", response_model=ChangeOrderResponse)
async def approve_order(
    order_id: uuid.UUID,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("changeorders.approve")),
    service: ChangeOrderService = Depends(_get_service),
) -> ChangeOrderResponse:
    """Approve a submitted change order."""
    order = await service.approve_order(order_id, user_id)
    return _order_to_response(order)


@router.post("/{order_id}/reject/", response_model=ChangeOrderResponse)
async def reject_order(
    order_id: uuid.UUID,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("changeorders.approve")),
    service: ChangeOrderService = Depends(_get_service),
) -> ChangeOrderResponse:
    """Reject a submitted change order."""
    order = await service.reject_order(order_id, user_id)
    return _order_to_response(order)
