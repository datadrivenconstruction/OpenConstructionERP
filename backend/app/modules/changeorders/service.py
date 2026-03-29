"""Change Order service — business logic for change order management.

Stateless service layer. Handles:
- Change order CRUD with auto-generated codes
- Item management with cost_delta calculation
- Status transitions (draft -> submitted -> approved/rejected)
- Cost impact recalculation from items
"""

import logging
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.changeorders.models import ChangeOrder, ChangeOrderItem
from app.modules.changeorders.repository import ChangeOrderRepository
from app.modules.changeorders.schemas import (
    ChangeOrderCreate,
    ChangeOrderItemCreate,
    ChangeOrderItemUpdate,
    ChangeOrderUpdate,
)

logger = logging.getLogger(__name__)

# Valid status transitions
VALID_TRANSITIONS: dict[str, list[str]] = {
    "draft": ["submitted"],
    "submitted": ["approved", "rejected", "draft"],
    "approved": [],
    "rejected": ["draft"],
}


class ChangeOrderService:
    """Business logic for change order operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = ChangeOrderRepository(session)

    # ── Create ────────────────────────────────────────────────────────────

    async def create_order(self, data: ChangeOrderCreate) -> ChangeOrder:
        """Create a new change order with auto-generated code."""
        count = await self.repo.count_for_project(data.project_id)
        code = f"CO-{count + 1:03d}"

        order = ChangeOrder(
            project_id=data.project_id,
            code=code,
            title=data.title,
            description=data.description,
            reason_category=data.reason_category,
            schedule_impact_days=data.schedule_impact_days,
            currency=data.currency,
            metadata_=data.metadata,
        )
        order = await self.repo.create(order)
        logger.info("Change order created: %s for project %s", code, data.project_id)
        return order

    # ── Read ──────────────────────────────────────────────────────────────

    async def get_order(self, order_id: uuid.UUID) -> ChangeOrder:
        """Get change order by ID. Raises 404 if not found."""
        order = await self.repo.get_by_id(order_id)
        if order is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Change order not found",
            )
        return order

    async def list_orders(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status_filter: str | None = None,
    ) -> tuple[list[ChangeOrder], int]:
        """List change orders for a project."""
        return await self.repo.list_for_project(
            project_id,
            offset=offset,
            limit=limit,
            status=status_filter,
        )

    async def get_summary(self, project_id: uuid.UUID) -> dict:
        """Get aggregated stats for a project's change orders."""
        return await self.repo.get_summary(project_id)

    # ── Update ────────────────────────────────────────────────────────────

    async def update_order(
        self,
        order_id: uuid.UUID,
        data: ChangeOrderUpdate,
    ) -> ChangeOrder:
        """Update change order fields. Only draft orders can be edited."""
        order = await self.get_order(order_id)

        if order.status != "draft":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only draft change orders can be edited",
            )

        fields = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        if not fields:
            return order

        await self.repo.update_fields(order_id, **fields)
        await self.session.refresh(order)

        logger.info("Change order updated: %s (fields=%s)", order_id, list(fields.keys()))
        return order

    # ── Delete ────────────────────────────────────────────────────────────

    async def delete_order(self, order_id: uuid.UUID) -> None:
        """Delete a change order. Only draft orders can be deleted."""
        order = await self.get_order(order_id)

        if order.status != "draft":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only draft change orders can be deleted",
            )

        await self.repo.delete(order_id)
        logger.info("Change order deleted: %s", order_id)

    # ── Status transitions ────────────────────────────────────────────────

    async def submit_order(self, order_id: uuid.UUID, user_id: str) -> ChangeOrder:
        """Submit a change order for approval."""
        order = await self.get_order(order_id)
        self._validate_transition(order.status, "submitted")

        now = datetime.now(timezone.utc).isoformat()[:19]
        await self.repo.update_fields(
            order_id,
            status="submitted",
            submitted_by=user_id,
            submitted_at=now,
        )
        await self.session.refresh(order)

        logger.info("Change order submitted: %s by %s", order.code, user_id)
        return order

    async def approve_order(self, order_id: uuid.UUID, user_id: str) -> ChangeOrder:
        """Approve a submitted change order."""
        order = await self.get_order(order_id)
        self._validate_transition(order.status, "approved")

        now = datetime.now(timezone.utc).isoformat()[:19]
        await self.repo.update_fields(
            order_id,
            status="approved",
            approved_by=user_id,
            approved_at=now,
        )
        await self.session.refresh(order)

        logger.info("Change order approved: %s by %s", order.code, user_id)
        return order

    async def reject_order(self, order_id: uuid.UUID, user_id: str) -> ChangeOrder:
        """Reject a submitted change order."""
        order = await self.get_order(order_id)
        self._validate_transition(order.status, "rejected")

        now = datetime.now(timezone.utc).isoformat()[:19]
        await self.repo.update_fields(
            order_id,
            status="rejected",
            approved_by=user_id,
            approved_at=now,
        )
        await self.session.refresh(order)

        logger.info("Change order rejected: %s by %s", order.code, user_id)
        return order

    def _validate_transition(self, current: str, target: str) -> None:
        """Validate a status transition."""
        allowed = VALID_TRANSITIONS.get(current, [])
        if target not in allowed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot transition from '{current}' to '{target}'",
            )

    # ── Items ─────────────────────────────────────────────────────────────

    async def add_item(
        self,
        order_id: uuid.UUID,
        data: ChangeOrderItemCreate,
    ) -> ChangeOrderItem:
        """Add an item to a change order and recalculate cost impact."""
        order = await self.get_order(order_id)

        if order.status not in ("draft", "submitted"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot add items to approved/rejected change orders",
            )

        cost_delta = (data.new_quantity * data.new_rate) - (
            data.original_quantity * data.original_rate
        )

        item = ChangeOrderItem(
            change_order_id=order_id,
            description=data.description,
            change_type=data.change_type,
            original_quantity=str(data.original_quantity),
            new_quantity=str(data.new_quantity),
            original_rate=str(data.original_rate),
            new_rate=str(data.new_rate),
            cost_delta=str(round(cost_delta, 2)),
            unit=data.unit,
            sort_order=data.sort_order,
            metadata_=data.metadata,
        )
        item = await self.repo.create_item(item)

        await self._recalculate_cost_impact(order_id)

        logger.info("Item added to change order %s: %s", order.code, data.description[:40])
        return item

    async def update_item(
        self,
        order_id: uuid.UUID,
        item_id: uuid.UUID,
        data: ChangeOrderItemUpdate,
    ) -> ChangeOrderItem:
        """Update an item and recalculate cost impact."""
        order = await self.get_order(order_id)

        if order.status not in ("draft", "submitted"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot edit items on approved/rejected change orders",
            )

        item = await self.repo.get_item_by_id(item_id)
        if item is None or item.change_order_id != order_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Change order item not found",
            )

        fields = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        # Recalculate cost_delta if quantities or rates changed
        orig_qty = fields.get("original_quantity", float(item.original_quantity))
        new_qty = fields.get("new_quantity", float(item.new_quantity))
        orig_rate = fields.get("original_rate", float(item.original_rate))
        new_rate = fields.get("new_rate", float(item.new_rate))

        if any(k in fields for k in ("original_quantity", "new_quantity", "original_rate", "new_rate")):
            cost_delta = (new_qty * new_rate) - (orig_qty * orig_rate)
            fields["cost_delta"] = str(round(cost_delta, 2))

        # Convert float fields to strings for storage
        for key in ("original_quantity", "new_quantity", "original_rate", "new_rate"):
            if key in fields:
                fields[key] = str(fields[key])

        if fields:
            await self.repo.update_item_fields(item_id, **fields)
            await self._recalculate_cost_impact(order_id)
            await self.session.refresh(item)

        return item

    async def delete_item(self, order_id: uuid.UUID, item_id: uuid.UUID) -> None:
        """Delete an item and recalculate cost impact."""
        order = await self.get_order(order_id)

        if order.status not in ("draft", "submitted"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete items from approved/rejected change orders",
            )

        item = await self.repo.get_item_by_id(item_id)
        if item is None or item.change_order_id != order_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Change order item not found",
            )

        await self.repo.delete_item(item_id)
        await self._recalculate_cost_impact(order_id)

        logger.info("Item deleted from change order %s: %s", order.code, item_id)

    async def _recalculate_cost_impact(self, order_id: uuid.UUID) -> None:
        """Recalculate the total cost impact from all items."""
        items = await self.repo.list_items_for_order(order_id)
        total = sum(float(item.cost_delta) for item in items)
        await self.repo.update_fields(order_id, cost_impact=str(round(total, 2)))
