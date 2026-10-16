# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Supplier deliveries through the portal (BF-01).

A supplier with a portal account and ``submit`` access to a purchase order
(access rule resource type ``po``) can tell the site what is on its way: the
delivery note, the quantity per order line, the batch and the certificates that
travel with the material. That becomes a **draft** goods receipt. Site staff
check it against what actually arrived and confirm it in procurement; nothing a
supplier submits moves stock, budget or payment on its own.

RLS follows the rest of the portal: a purchase order the caller has no rule on
answers 404, never 403, so the existence of another supplier's order does not
leak. Files go to the documents module under the order's project, stamped with
the portal account as uploader, and a supplier may attach only files it
uploaded itself.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import publish_after_commit
from app.modules.portal.schemas import (
    PortalDeliveryEntry,
    PortalDeliveryLineEntry,
    PortalDeliverySubmit,
    PortalPOLine,
    PortalPurchaseOrderEntry,
)
from app.modules.portal.service import PortalService

logger = logging.getLogger(__name__)

#: Portal access-rule resource type of a purchase order.
PO_RESOURCE = "po"
#: Order statuses a delivery can still be submitted against.
DELIVERABLE_STATUSES = frozenset({"issued", "partially_received"})


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Purchase order not found")


def _dec(raw: Any) -> Decimal:
    try:
        return Decimal(str(raw or "0"))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


class PortalDeliveryService:
    """What a supplier may see and submit about the orders shared with it."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.portal = PortalService(session)

    async def _po_for(self, portal_user_id: uuid.UUID, po_id: uuid.UUID, required: str) -> Any:
        from app.modules.procurement.models import PurchaseOrder

        if not await self.portal.enforce_rls(portal_user_id, PO_RESOURCE, po_id, required=required):
            raise _not_found()
        po = await self.session.get(PurchaseOrder, po_id)
        if po is None:
            raise _not_found()
        return po

    async def _received_by_item(self, item_ids: list[uuid.UUID]) -> dict[uuid.UUID, Decimal]:
        """Confirmed received quantity per order line, so the supplier sees what is still open."""
        from app.core.sql_numeric import numeric_value
        from app.modules.procurement.models import GoodsReceipt, GoodsReceiptItem

        if not item_ids:
            return {}
        rows = (
            await self.session.execute(
                select(
                    GoodsReceiptItem.po_item_id,
                    func.coalesce(func.sum(numeric_value(GoodsReceiptItem.quantity_received)), 0),
                )
                .join(GoodsReceipt, GoodsReceipt.id == GoodsReceiptItem.receipt_id)
                .where(GoodsReceipt.status == "confirmed")
                .where(GoodsReceiptItem.po_item_id.in_(item_ids))
                .group_by(GoodsReceiptItem.po_item_id)
            )
        ).all()
        return {row[0]: _dec(row[1]) for row in rows}

    async def list_purchase_orders(self, portal_user_id: uuid.UUID) -> list[PortalPurchaseOrderEntry]:
        """Orders the caller holds a live ``po`` rule on, with their lines."""
        from sqlalchemy.orm import selectinload

        from app.modules.procurement.models import PurchaseOrder

        visible = await self.portal._granted_resource_ids(portal_user_id, PO_RESOURCE, "view")
        if not visible:
            return []
        submittable = set(await self.portal._granted_resource_ids(portal_user_id, PO_RESOURCE, "submit"))
        pos = list(
            (
                await self.session.execute(
                    select(PurchaseOrder)
                    .options(selectinload(PurchaseOrder.items))
                    .where(PurchaseOrder.id.in_(visible))
                    .where(PurchaseOrder.status != "draft")
                    .order_by(PurchaseOrder.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        received = await self._received_by_item([it.id for po in pos for it in po.items or []])
        out: list[PortalPurchaseOrderEntry] = []
        for po in pos:
            out.append(
                PortalPurchaseOrderEntry(
                    id=po.id,
                    po_number=po.po_number,
                    status=po.status,
                    delivery_date=po.delivery_date,
                    currency_code=po.currency_code or "",
                    can_deliver=po.id in submittable and po.status in DELIVERABLE_STATUSES,
                    lines=[
                        PortalPOLine(
                            id=it.id,
                            description=it.description,
                            unit=it.unit,
                            quantity_ordered=format(_dec(it.quantity).normalize(), "f"),
                            quantity_received=format(received.get(it.id, Decimal("0")).normalize(), "f"),
                            required_certificate_type=it.required_certificate_type,
                            requires_inspection=bool(it.requires_inspection),
                        )
                        for it in sorted(po.items or [], key=lambda i: (i.sort_order, str(i.id)))
                    ],
                )
            )
        return out

    async def upload_document(self, portal_user_id: uuid.UUID, po_id: uuid.UUID, file: UploadFile) -> Any:
        """Store a delivery note or certificate scan under the order's project."""
        from app.modules.documents.service import DocumentService

        po = await self._po_for(portal_user_id, po_id, "submit")
        doc = await DocumentService(self.session).upload_document(po.project_id, file, "other", str(portal_user_id))
        await self.portal.record_document_access(
            portal_user_id,
            document_type="document",
            document_id=doc.id,
            action="upload",
        )
        return doc

    async def submit_delivery(
        self,
        portal_user_id: uuid.UUID,
        data: PortalDeliverySubmit,
        *,
        client_ip: str | None = None,
    ) -> Any:
        """Create the draft goods receipt the site confirms."""
        from app.modules.procurement.receiving import SOURCE_SUPPLIER_PORTAL, ReceivingService
        from app.modules.procurement.schemas import GRCertificateCreate, GRCreate, GRItemCreate
        from app.modules.procurement.service import ProcurementService

        po = await self._po_for(portal_user_id, data.po_id, "submit")
        if po.status not in DELIVERABLE_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Deliveries can only be submitted against an issued purchase order.",
            )
        po_items = {it.id: it for it in po.items or []}
        if any(line.po_item_id not in po_items for line in data.lines):
            raise _not_found()
        if data.delivery_note_document_id is not None:
            await ReceivingService(self.session).check_documents(
                po.project_id, [data.delivery_note_document_id], uploaded_by=str(portal_user_id)
            )
        create = GRCreate(
            po_id=po.id,
            receipt_date=data.delivery_date.isoformat(),
            delivery_note_number=data.delivery_note_number,
            status="draft",
            notes=data.notes,
            items=[
                GRItemCreate(
                    po_item_id=line.po_item_id,
                    quantity_ordered=po_items[line.po_item_id].quantity or "0",
                    quantity_received=format(line.quantity.normalize(), "f"),
                    batch_lot=line.batch_lot,
                    certificates=[GRCertificateCreate(**c.model_dump()) for c in line.certificates],
                )
                for line in data.lines
            ],
            metadata={
                "submitted_via_portal": True,
                "portal_user_id": str(portal_user_id),
                "submitted_ip": client_ip,
                "delivery_note_document_id": (
                    str(data.delivery_note_document_id) if data.delivery_note_document_id else None
                ),
            },
        )
        gr = await ProcurementService(self.session).create_goods_receipt(
            create,
            user_id=None,
            source=SOURCE_SUPPLIER_PORTAL,
            portal_user_id=portal_user_id,
        )
        publish_after_commit(
            self.session,
            "portal.delivery.submitted",
            {
                "gr_id": str(gr.id),
                "po_id": str(po.id),
                "project_id": str(po.project_id),
                "portal_user_id": str(portal_user_id),
            },
            source_module="portal",
        )
        return gr

    async def list_deliveries(self, portal_user_id: uuid.UUID) -> list[PortalDeliveryEntry]:
        """Deliveries this account submitted, on orders it can still see."""
        from sqlalchemy.orm import selectinload

        from app.modules.procurement.models import GoodsReceipt, GoodsReceiptItem, PurchaseOrder

        visible = await self.portal._granted_resource_ids(portal_user_id, PO_RESOURCE, "view")
        if not visible:
            return []
        rows = (
            await self.session.execute(
                select(GoodsReceipt, PurchaseOrder.po_number)
                .join(PurchaseOrder, PurchaseOrder.id == GoodsReceipt.po_id)
                .options(selectinload(GoodsReceipt.items).selectinload(GoodsReceiptItem.certificates))
                .where(GoodsReceipt.portal_user_id == portal_user_id)
                .where(GoodsReceipt.po_id.in_(visible))
                .order_by(GoodsReceipt.created_at.desc())
                .limit(200)
            )
        ).all()
        descriptions: dict[uuid.UUID, str] = {}
        item_ids = {it.po_item_id for gr, _ in rows for it in gr.items or [] if it.po_item_id}
        if item_ids:
            from app.modules.procurement.models import PurchaseOrderItem

            for item_id, desc in (
                await self.session.execute(
                    select(PurchaseOrderItem.id, PurchaseOrderItem.description).where(
                        PurchaseOrderItem.id.in_(item_ids)
                    )
                )
            ).all():
                descriptions[item_id] = desc
        return [
            PortalDeliveryEntry(
                id=gr.id,
                po_id=gr.po_id,
                po_number=po_number or "",
                delivery_note_number=gr.delivery_note_number,
                receipt_date=gr.receipt_date,
                status=gr.status,
                created_at=gr.created_at,
                lines=[
                    PortalDeliveryLineEntry(
                        po_item_id=it.po_item_id,
                        description=descriptions.get(it.po_item_id, "") if it.po_item_id else "",
                        quantity_received=it.quantity_received,
                        batch_lot=it.batch_lot,
                        certificate_count=len(it.certificates or []),
                    )
                    for it in gr.items or []
                ],
            )
            for gr, po_number in rows
        ]


__all__ = ["DELIVERABLE_STATUSES", "PO_RESOURCE", "PortalDeliveryService"]
