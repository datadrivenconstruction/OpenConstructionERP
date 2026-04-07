"""Procurement service — business logic for purchase orders and goods receipts.

Stateless service layer.
"""

import logging
import uuid
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.procurement.models import (
    GoodsReceipt,
    GoodsReceiptItem,
    PurchaseOrder,
    PurchaseOrderItem,
)
from app.modules.procurement.repository import (
    GoodsReceiptRepository,
    GRItemRepository,
    POItemRepository,
    PurchaseOrderRepository,
)
from app.modules.procurement.schemas import (
    GRCreate,
    POCreate,
    POUpdate,
)

logger = logging.getLogger(__name__)

# ── Allowed PO status transitions ───────────────────────────────────────────

_PO_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"issued", "cancelled"},
    "issued": {"partially_received", "completed", "cancelled"},
    "partially_received": {"completed", "cancelled"},
    "completed": set(),  # terminal
    "cancelled": {"draft"},  # allow re-opening
}

_VALID_PO_STATUSES = set(_PO_STATUS_TRANSITIONS.keys())


def _parse_decimal(value: str, field_name: str = "value") -> Decimal:
    """Parse a string to Decimal, raising a clear error on failure."""
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid numeric value for {field_name}: {value!r}",
        ) from exc


def _compute_po_total(subtotal: str, tax: str) -> str:
    """Compute amount_total = amount_subtotal + tax_amount."""
    s = _parse_decimal(subtotal, "amount_subtotal")
    t = _parse_decimal(tax, "tax_amount")
    return str(s + t)


class ProcurementService:
    """Business logic for procurement operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.po_repo = PurchaseOrderRepository(session)
        self.po_item_repo = POItemRepository(session)
        self.gr_repo = GoodsReceiptRepository(session)
        self.gr_item_repo = GRItemRepository(session)

    # ── Purchase Orders ──────────────────────────────────────────────────────

    async def create_po(
        self,
        data: POCreate,
        user_id: str | None = None,
    ) -> PurchaseOrder:
        """Create a new purchase order with optional line items.

        Automatically computes amount_total = amount_subtotal + tax_amount.
        """
        # Validate initial status
        if data.status not in _VALID_PO_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Invalid PO status: '{data.status}'. "
                    f"Allowed: {', '.join(sorted(_VALID_PO_STATUSES))}"
                ),
            )

        po_number = data.po_number
        if not po_number:
            po_number = await self.po_repo.next_po_number(data.project_id)

        # Server-side total computation
        computed_total = _compute_po_total(data.amount_subtotal, data.tax_amount)

        po = PurchaseOrder(
            project_id=data.project_id,
            vendor_contact_id=data.vendor_contact_id,
            po_number=po_number,
            po_type=data.po_type,
            issue_date=data.issue_date,
            delivery_date=data.delivery_date,
            currency_code=data.currency_code,
            amount_subtotal=data.amount_subtotal,
            tax_amount=data.tax_amount,
            amount_total=computed_total,
            status=data.status,
            payment_terms=data.payment_terms,
            notes=data.notes,
            created_by=uuid.UUID(user_id) if user_id else None,
            metadata_=data.metadata,
        )
        po = await self.po_repo.create(po)

        # Create line items
        for idx, item_data in enumerate(data.items):
            item = PurchaseOrderItem(
                po_id=po.id,
                description=item_data.description,
                quantity=item_data.quantity,
                unit=item_data.unit,
                unit_rate=item_data.unit_rate,
                amount=item_data.amount,
                wbs_id=item_data.wbs_id,
                cost_category=item_data.cost_category,
                sort_order=item_data.sort_order if item_data.sort_order else idx,
            )
            await self.po_item_repo.create(item)

        logger.info("PO created: %s (type=%s)", po.po_number, po.po_type)
        return po

    async def get_po(self, po_id: uuid.UUID) -> PurchaseOrder:
        """Get PO by ID. Raises 404 if not found."""
        po = await self.po_repo.get(po_id)
        if po is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Purchase order not found",
            )
        return po

    async def list_pos(
        self,
        *,
        project_id: uuid.UUID | None = None,
        po_status: str | None = None,
        vendor_contact_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[PurchaseOrder], int]:
        """List POs with filters."""
        return await self.po_repo.list(
            project_id=project_id,
            status=po_status,
            vendor_contact_id=vendor_contact_id,
            limit=limit,
            offset=offset,
        )

    async def update_po(
        self,
        po_id: uuid.UUID,
        data: POUpdate,
    ) -> PurchaseOrder:
        """Update PO fields and optionally replace items.

        Validates status transitions and recomputes amount_total when
        subtotal or tax are changed.
        """
        po = await self.get_po(po_id)  # 404 check

        fields = data.model_dump(exclude_unset=True, exclude={"items"})
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        # Validate status transition if status is being changed
        if "status" in fields and fields["status"] is not None:
            new_status = fields["status"]
            if new_status not in _VALID_PO_STATUSES:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Invalid PO status: '{new_status}'. "
                        f"Allowed: {', '.join(sorted(_VALID_PO_STATUSES))}"
                    ),
                )
            allowed = _PO_STATUS_TRANSITIONS.get(po.status, set())
            if new_status != po.status and new_status not in allowed:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Cannot transition PO from '{po.status}' to '{new_status}'. "
                        f"Allowed transitions: {', '.join(sorted(allowed)) or 'none'}"
                    ),
                )

        # Recompute total if subtotal or tax changed
        new_subtotal = fields.get("amount_subtotal", po.amount_subtotal)
        new_tax = fields.get("tax_amount", po.tax_amount)
        if "amount_subtotal" in fields or "tax_amount" in fields:
            fields["amount_total"] = _compute_po_total(
                new_subtotal or po.amount_subtotal,
                new_tax or po.tax_amount,
            )

        if fields:
            await self.po_repo.update(po_id, **fields)

        # Replace items if provided
        if data.items is not None:
            await self.po_item_repo.delete_by_po(po_id)
            for idx, item_data in enumerate(data.items):
                item = PurchaseOrderItem(
                    po_id=po_id,
                    description=item_data.description,
                    quantity=item_data.quantity,
                    unit=item_data.unit,
                    unit_rate=item_data.unit_rate,
                    amount=item_data.amount,
                    wbs_id=item_data.wbs_id,
                    cost_category=item_data.cost_category,
                    sort_order=item_data.sort_order if item_data.sort_order else idx,
                )
                await self.po_item_repo.create(item)

        updated = await self.po_repo.get(po_id)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Purchase order not found",
            )
        logger.info("PO updated: %s", po_id)
        return updated

    async def issue_po(self, po_id: uuid.UUID) -> PurchaseOrder:
        """Transition PO to issued status."""
        po = await self.get_po(po_id)
        if po.status != "draft":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot issue PO in status '{po.status}'",
            )
        await self.po_repo.update(po_id, status="issued")
        updated = await self.po_repo.get(po_id)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Purchase order not found",
            )
        logger.info("PO issued: %s", po.po_number)
        return updated

    # ── Goods Receipts ───────────────────────────────────────────────────────

    async def create_goods_receipt(
        self,
        data: GRCreate,
        user_id: str | None = None,
    ) -> GoodsReceipt:
        """Create a goods receipt against a PO.

        Validates:
        - PO exists and is in a receivable status (issued or partially_received)
        - received_qty <= ordered_qty for each GR item (when po_item_id provided)
        """
        po = await self.get_po(data.po_id)  # 404 check

        # PO must be in a status that accepts goods receipts
        if po.status not in ("issued", "partially_received"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Cannot create goods receipt for PO in status '{po.status}'. "
                    "PO must be issued or partially_received."
                ),
            )

        # Validate GR item quantities against PO items
        po_items_by_id = {item.id: item for item in po.items}
        for item_data in data.items:
            if item_data.po_item_id is not None:
                po_item = po_items_by_id.get(item_data.po_item_id)
                if po_item is None:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=(
                            f"PO item {item_data.po_item_id} not found "
                            f"in purchase order {data.po_id}"
                        ),
                    )
                # Validate received quantity does not exceed ordered quantity
                try:
                    ordered = Decimal(po_item.quantity)
                    received = Decimal(item_data.quantity_received)
                except (InvalidOperation, ValueError, TypeError):
                    continue  # let DB-level validation handle bad numbers
                if received > ordered:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=(
                            f"Received quantity ({received}) exceeds ordered quantity "
                            f"({ordered}) for PO item '{po_item.description}'"
                        ),
                    )

        gr = GoodsReceipt(
            po_id=data.po_id,
            receipt_date=data.receipt_date,
            received_by_id=data.received_by_id or (uuid.UUID(user_id) if user_id else None),
            delivery_note_number=data.delivery_note_number,
            status=data.status,
            notes=data.notes,
            metadata_=data.metadata,
        )
        gr = await self.gr_repo.create(gr)

        # Create GR items
        for item_data in data.items:
            item = GoodsReceiptItem(
                receipt_id=gr.id,
                po_item_id=item_data.po_item_id,
                quantity_ordered=item_data.quantity_ordered,
                quantity_received=item_data.quantity_received,
                quantity_rejected=item_data.quantity_rejected,
                rejection_reason=item_data.rejection_reason,
            )
            await self.gr_item_repo.create(item)

        logger.info("GR created for PO %s (date=%s)", data.po_id, data.receipt_date)
        return gr

    async def get_goods_receipt(self, gr_id: uuid.UUID) -> GoodsReceipt:
        """Get goods receipt by ID. Raises 404 if not found."""
        gr = await self.gr_repo.get(gr_id)
        if gr is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Goods receipt not found",
            )
        return gr

    async def list_goods_receipts(
        self,
        *,
        po_id: uuid.UUID | None = None,
        gr_status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[GoodsReceipt], int]:
        """List goods receipts with optional filters."""
        return await self.gr_repo.list(
            po_id=po_id, status=gr_status, limit=limit, offset=offset
        )

    async def confirm_goods_receipt(self, gr_id: uuid.UUID) -> GoodsReceipt:
        """Confirm a goods receipt and update the PO status accordingly.

        After confirmation, checks whether ALL PO items are fully received:
        - If fully received -> PO status = 'completed'
        - If partially received -> PO status = 'partially_received'
        """
        gr = await self.get_goods_receipt(gr_id)
        if gr.status != "draft":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot confirm goods receipt in status '{gr.status}'",
            )
        await self.gr_repo.update(gr_id, status="confirmed")

        # Update PO status based on total received quantities
        po = await self.get_po(gr.po_id)
        if po.status in ("issued", "partially_received"):
            all_fully_received = self._check_po_fully_received(po)
            if all_fully_received:
                await self.po_repo.update(po.id, status="completed")
                logger.info("PO %s fully received, status -> completed", po.po_number)
            elif po.status == "issued":
                await self.po_repo.update(po.id, status="partially_received")
                logger.info("PO %s partially received", po.po_number)

        updated = await self.gr_repo.get(gr_id)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Goods receipt not found",
            )
        logger.info("GR confirmed: %s", gr_id)
        return updated

    @staticmethod
    def _check_po_fully_received(po: PurchaseOrder) -> bool:
        """Check if all PO items have been fully received across confirmed GRs."""
        if not po.items:
            return True

        # Sum confirmed received quantities per PO item
        received_by_item: dict[uuid.UUID, Decimal] = {}
        for gr in po.goods_receipts:
            if gr.status != "confirmed":
                continue
            for gr_item in gr.items:
                if gr_item.po_item_id is not None:
                    try:
                        qty = Decimal(gr_item.quantity_received)
                    except (InvalidOperation, ValueError, TypeError):
                        qty = Decimal("0")
                    received_by_item[gr_item.po_item_id] = (
                        received_by_item.get(gr_item.po_item_id, Decimal("0")) + qty
                    )

        # Check each PO item
        for po_item in po.items:
            try:
                ordered = Decimal(po_item.quantity)
            except (InvalidOperation, ValueError, TypeError):
                ordered = Decimal("0")
            received = received_by_item.get(po_item.id, Decimal("0"))
            if received < ordered:
                return False

        return True
