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

    async def get_summary(self, project_id: uuid.UUID) -> dict[str, int | float | str]:
        """Aggregate change order stats for a project."""
        base = select(ChangeOrder).where(ChangeOrder.project_id == project_id)
        result = await self.session.execute(base)
        orders = list(result.scalars().all())

        summary: dict[str, int | float | str] = {
            "total_orders": len(orders),
            "draft_count": 0,
            "submitted_count": 0,
            "approved_count": 0,
            "rejected_count": 0,
            "total_cost_impact": 0.0,
            "total_schedule_impact_days": 0,
            "currency": "EUR",
        }

        for order in orders:
            if order.status == "draft":
                summary["draft_count"] = int(summary["draft_count"]) + 1  # type: ignore[arg-type]
            elif order.status == "submitted":
                summary["submitted_count"] = int(summary["submitted_count"]) + 1  # type: ignore[arg-type]
            elif order.status == "approved":
                summary["approved_count"] = int(summary["approved_count"]) + 1  # type: ignore[arg-type]
                # Only approved orders count toward total cost/schedule impact
                summary["total_cost_impact"] = float(summary["total_cost_impact"]) + float(order.cost_impact)  # type: ignore[arg-type]
                summary["total_schedule_impact_days"] = int(summary["total_schedule_impact_days"]) + order.schedule_impact_days  # type: ignore[arg-type]
            elif order.status == "rejected":
                summary["rejected_count"] = int(summary["rejected_count"]) + 1  # type: ignore[arg-type]

            if order.currency:
                summary["currency"] = order.currency

        return summary

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
