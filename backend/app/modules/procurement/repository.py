"""‌⁠‍Procurement data access layer.

All database queries for procurement entities live here.
No business logic — pure data access.
"""

import uuid

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.procurement.models import (
    GoodsReceipt,
    GoodsReceiptItem,
    PurchaseOrder,
    PurchaseOrderItem,
)


class PurchaseOrderRepository:
    """‌⁠‍Data access for PurchaseOrder model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, po_id: uuid.UUID) -> PurchaseOrder | None:
        """‌⁠‍Get PO by ID (with items and GRs via selectin).

        Uses ``selectinload`` to eagerly load items and goods_receipts
        so they are available outside the async context.
        """
        from sqlalchemy.orm import selectinload

        stmt = (
            select(PurchaseOrder)
            .options(
                selectinload(PurchaseOrder.items),
                selectinload(PurchaseOrder.goods_receipts),
            )
            .where(PurchaseOrder.id == po_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list(
        self,
        *,
        project_id: uuid.UUID | None = None,
        status: str | None = None,
        vendor_contact_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[PurchaseOrder], int]:
        """List POs with filters and pagination."""
        base = select(PurchaseOrder)

        if project_id is not None:
            base = base.where(PurchaseOrder.project_id == project_id)
        if status is not None:
            base = base.where(PurchaseOrder.status == status)
        if vendor_contact_id is not None:
            base = base.where(PurchaseOrder.vendor_contact_id == vendor_contact_id)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(PurchaseOrder.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def create(self, po: PurchaseOrder) -> PurchaseOrder:
        """Insert a new PO.

        After flush we refresh to eagerly load ``selectin`` relationships
        (items, goods_receipts) so the caller can safely serialize the object
        outside the async greenlet context.
        """
        self.session.add(po)
        await self.session.flush()
        await self.session.refresh(po)
        return po

    async def update(self, po_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a PO."""
        stmt = update(PurchaseOrder).where(PurchaseOrder.id == po_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def stats_for_project(self, project_id: uuid.UUID) -> dict:
        """Compute aggregate procurement statistics for a project.

        Returns dict with total_pos, by_status, total_committed,
        total_received (confirmed GR count), pending_delivery_count.
        """
        # Total POs
        total_stmt = select(func.count()).select_from(PurchaseOrder).where(PurchaseOrder.project_id == project_id)
        total_pos = (await self.session.execute(total_stmt)).scalar_one()

        # By status
        status_stmt = (
            select(PurchaseOrder.status, func.count())
            .where(PurchaseOrder.project_id == project_id)
            .group_by(PurchaseOrder.status)
        )
        status_rows = (await self.session.execute(status_stmt)).all()
        by_status = {row[0]: row[1] for row in status_rows}

        # Total committed = SUM(amount_total) for non-cancelled POs
        # amount_total is stored as string, so we cast in Python after fetching
        committed_stmt = (
            select(PurchaseOrder.amount_total)
            .where(PurchaseOrder.project_id == project_id)
            .where(PurchaseOrder.status != "cancelled")
        )
        committed_rows = (await self.session.execute(committed_stmt)).all()
        from decimal import Decimal, InvalidOperation

        total_committed = Decimal("0")
        for row in committed_rows:
            try:
                total_committed += Decimal(row[0])
            except (InvalidOperation, ValueError, TypeError):
                pass

        # Count of confirmed goods receipts
        from app.modules.procurement.models import GoodsReceipt

        received_stmt = (
            select(func.count())
            .select_from(GoodsReceipt)
            .join(PurchaseOrder, GoodsReceipt.po_id == PurchaseOrder.id)
            .where(PurchaseOrder.project_id == project_id)
            .where(GoodsReceipt.status == "confirmed")
        )
        total_received = (await self.session.execute(received_stmt)).scalar_one()

        # POs pending delivery (issued or partially_received)
        pending_stmt = (
            select(func.count())
            .select_from(PurchaseOrder)
            .where(PurchaseOrder.project_id == project_id)
            .where(PurchaseOrder.status.in_(("issued", "partially_received")))
        )
        pending_delivery = (await self.session.execute(pending_stmt)).scalar_one()

        return {
            "total_pos": total_pos,
            "by_status": by_status,
            "total_committed": str(total_committed),
            "total_received": total_received,
            "pending_delivery_count": pending_delivery,
        }

    async def next_po_number(self, project_id: uuid.UUID) -> str:
        """Generate the next PO number for a project.

        Uses MAX of existing PO numbers to avoid race conditions where
        COUNT-based generation would produce duplicates under concurrency.
        """
        stmt = (
            select(func.max(PurchaseOrder.po_number))
            .where(PurchaseOrder.project_id == project_id)
            .where(PurchaseOrder.po_number.like("PO-%"))
        )
        max_number = (await self.session.execute(stmt)).scalar_one_or_none()

        if max_number:
            try:
                suffix = int(max_number.rsplit("-", 1)[-1])
            except (ValueError, IndexError):
                suffix = 0
            return f"PO-{suffix + 1:03d}"

        return "PO-001"


class POItemRepository:
    """Data access for PurchaseOrderItem model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, item: PurchaseOrderItem) -> PurchaseOrderItem:
        """Insert a new PO item."""
        self.session.add(item)
        await self.session.flush()
        return item

    async def delete_by_po(self, po_id: uuid.UUID) -> None:
        """Delete all items for a PO."""
        stmt = delete(PurchaseOrderItem).where(PurchaseOrderItem.po_id == po_id)
        await self.session.execute(stmt)
        await self.session.flush()


class GoodsReceiptRepository:
    """Data access for GoodsReceipt model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, gr_id: uuid.UUID) -> GoodsReceipt | None:
        """Get goods receipt by ID (with items via selectin)."""
        return await self.session.get(GoodsReceipt, gr_id)

    async def list(
        self,
        *,
        po_id: uuid.UUID | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[GoodsReceipt], int]:
        """List goods receipts with filters."""
        base = select(GoodsReceipt)

        if po_id is not None:
            base = base.where(GoodsReceipt.po_id == po_id)
        if status is not None:
            base = base.where(GoodsReceipt.status == status)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(GoodsReceipt.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def create(self, gr: GoodsReceipt) -> GoodsReceipt:
        """Insert a new goods receipt."""
        self.session.add(gr)
        await self.session.flush()
        return gr

    async def update(self, gr_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a goods receipt."""
        stmt = update(GoodsReceipt).where(GoodsReceipt.id == gr_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()


class GRItemRepository:
    """Data access for GoodsReceiptItem model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, item: GoodsReceiptItem) -> GoodsReceiptItem:
        """Insert a new GR item."""
        self.session.add(item)
        await self.session.flush()
        return item
