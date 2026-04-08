"""Change Order data access layer.

All database queries for change orders live here.
No business logic — pure data access.
"""

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.changeorders.models import ChangeOrder, ChangeOrderItem


class ChangeOrderRepository:
    """Data access for ChangeOrder and ChangeOrderItem models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── ChangeOrder ──────────────────────────────────────────────────────

    async def get_by_id(self, order_id: uuid.UUID) -> ChangeOrder | None:
        """Get change order by ID (includes items via selectin)."""
        return await self.session.get(ChangeOrder, order_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
    ) -> tuple[list[ChangeOrder], int]:
        """List change orders for a project with pagination."""
        base = select(ChangeOrder).where(ChangeOrder.project_id == project_id)
        if status is not None:
            base = base.where(ChangeOrder.status == status)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(ChangeOrder.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        orders = list(result.scalars().all())

        return orders, total

    async def create(self, order: ChangeOrder) -> ChangeOrder:
        """Insert a new change order."""
        self.session.add(order)
        await self.session.flush()
        return order

    async def update_fields(self, order_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a change order."""
        stmt = update(ChangeOrder).where(ChangeOrder.id == order_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, order_id: uuid.UUID) -> None:
        """Hard delete a change order and its items."""
        order = await self.get_by_id(order_id)
        if order is not None:
            await self.session.delete(order)
            await self.session.flush()

    async def count_for_project(self, project_id: uuid.UUID) -> int:
        """Count change orders for a project (used for code generation)."""
        stmt = select(func.count()).select_from(
            select(ChangeOrder).where(ChangeOrder.project_id == project_id).subquery()
        )
        return (await self.session.execute(stmt)).scalar_one()

    async def get_summary(self, project_id: uuid.UUID) -> dict[str, object]:
        """Aggregate change order stats for a project."""
        base = select(ChangeOrder).where(ChangeOrder.project_id == project_id)
        result = await self.session.execute(base)
        orders = list(result.scalars().all())

        draft_count = 0
        submitted_count = 0
        approved_count = 0
        rejected_count = 0
        total_cost_impact = 0.0
        total_approved_amount = 0.0
        total_schedule_impact_days = 0
        total_time_impact_days = 0
        by_status: dict[str, int] = {}
        by_type: dict[str, int] = {}
        currency = "EUR"

        for order in orders:
            # by_status aggregation
            by_status[order.status] = by_status.get(order.status, 0) + 1

            # by_type aggregation (reason_category)
            rcat = order.reason_category or "other"
            by_type[rcat] = by_type.get(rcat, 0) + 1

            if order.status == "draft":
                draft_count += 1
            elif order.status == "submitted":
                submitted_count += 1
            elif order.status == "approved":
                approved_count += 1
                # Only approved orders count toward total cost/schedule impact
                try:
                    total_cost_impact += float(order.cost_impact)
                    total_approved_amount += float(order.cost_impact)
                except (ValueError, TypeError):
                    pass
                total_schedule_impact_days += order.schedule_impact_days or 0
                total_time_impact_days += order.schedule_impact_days or 0
            elif order.status == "rejected":
                rejected_count += 1

            if order.currency:
                currency = order.currency

        return {
            "total": len(orders),
            "total_orders": len(orders),
            "by_status": by_status,
            "by_type": by_type,
            "draft_count": draft_count,
            "submitted_count": submitted_count,
            "approved_count": approved_count,
            "rejected_count": rejected_count,
            "total_approved_amount": round(total_approved_amount, 2),
            "total_cost_impact": round(total_cost_impact, 2),
            "total_time_impact_days": total_time_impact_days,
            "total_schedule_impact_days": total_schedule_impact_days,
            "currency": currency,
        }

    # ── ChangeOrderItem ──────────────────────────────────────────────────

    async def get_item_by_id(self, item_id: uuid.UUID) -> ChangeOrderItem | None:
        """Get a change order item by ID."""
        return await self.session.get(ChangeOrderItem, item_id)

    async def create_item(self, item: ChangeOrderItem) -> ChangeOrderItem:
        """Insert a new change order item."""
        self.session.add(item)
        await self.session.flush()
        return item

    async def update_item_fields(self, item_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a change order item."""
        stmt = update(ChangeOrderItem).where(ChangeOrderItem.id == item_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def delete_item(self, item_id: uuid.UUID) -> None:
        """Hard delete a change order item."""
        item = await self.get_item_by_id(item_id)
        if item is not None:
            await self.session.delete(item)
            await self.session.flush()

    async def list_items_for_order(self, order_id: uuid.UUID) -> list[ChangeOrderItem]:
        """List all items for a change order."""
        stmt = (
            select(ChangeOrderItem)
            .where(ChangeOrderItem.change_order_id == order_id)
            .order_by(ChangeOrderItem.sort_order)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
