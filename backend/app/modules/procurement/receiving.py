# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Receiving: from a delivery to the release of its payment (BF-01).

The chain a construction site runs for material is supplier delivery, check,
site approval, quality, payment. This module holds the parts of it that sit
around a goods receipt:

* material certificates on receipt lines, and the ``goods_receipt`` rule set
  that gates confirmation (a certificate the order asks for is missing: ERROR;
  its batch disagrees with the delivered batch: WARNING);
* the follow-ups the person confirming a receipt may start in the same
  transaction: the project's approval route for goods receipts and a pending
  incoming inspection for lines whose order asks for one;
* the ``invoice_payment_release`` rule set the finance module runs before a
  payable invoice on the order is approved or paid.

Nothing here starts on its own. Confirmation is a human act, the follow-ups
are boxes that person ticks, and a delivery submitted by a supplier through the
portal only ever creates a draft. The event bus is in-process and best effort,
so every write that matters happens in the caller's transaction and events are
published after it commits.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import publish_after_commit
from app.core.i18n import get_locale
from app.core.validation.engine import ValidationReport, validation_engine
from app.modules.procurement.models import (
    GoodsReceipt,
    GoodsReceiptCertificate,
    PurchaseOrder,
    PurchaseOrderItem,
)
from app.modules.procurement.schemas import GRCertificateCreate, GRConfirmRequest
from app.modules.procurement.validators import line_label, parse_money

logger = logging.getLogger(__name__)

#: Rule set run against a goods receipt before it is confirmed.
RECEIPT_RULE_SET = "goods_receipt"
#: Rule set run against the order of a payable invoice before it is released.
PAYMENT_RELEASE_RULE_SET = "invoice_payment_release"
#: The ``approval_routes`` target kind of a goods receipt.
GR_TARGET_KIND = "goods_receipt"
#: Where a receipt or certificate came from.
SOURCE_SITE = "site"
SOURCE_SUPPLIER_PORTAL = "supplier_portal"


def receipt_ref(gr: Any) -> str:
    """How a receipt is named to a person: its delivery note, else a short id."""
    note = str(getattr(gr, "delivery_note_number", "") or "").strip()
    return note or f"GR-{str(gr.id)[:8]}"


def _po_lines(po: PurchaseOrder) -> list[PurchaseOrderItem]:
    return sorted(po.items or [], key=lambda i: (i.sort_order, str(i.id)))


def _labels(po: PurchaseOrder) -> dict[uuid.UUID, str]:
    """The order's own line numbering, so a finding names the line the buyer sees."""
    return {item.id: line_label(idx, {"description": item.description}) for idx, item in enumerate(_po_lines(po))}


def receipt_validation_payload(gr: GoodsReceipt, po: PurchaseOrder) -> dict[str, Any]:
    """Flatten a receipt, its certificates and its order's requirements for the rules."""
    po_items = {item.id: item for item in po.items or []}
    labels = _labels(po)
    items: list[dict[str, Any]] = []
    for index, line in enumerate(gr.items or []):
        po_item = po_items.get(line.po_item_id) if line.po_item_id else None
        items.append(
            {
                "label": labels.get(line.po_item_id, str(index + 1)) if line.po_item_id else str(index + 1),
                "po_item_id": str(line.po_item_id) if line.po_item_id else None,
                "quantity_received": line.quantity_received,
                "batch_lot": line.batch_lot,
                "required_certificate_type": po_item.required_certificate_type if po_item else None,
                "certificates": [
                    {
                        "certificate_type": c.certificate_type,
                        "certificate_number": c.certificate_number,
                        "batch_number": c.batch_number,
                    }
                    for c in line.certificates or []
                ],
            }
        )
    return {
        "id": str(gr.id),
        "receipt_ref": receipt_ref(gr),
        "po_number": po.po_number,
        "items": items,
    }


def readiness_lines(gr: GoodsReceipt, po: PurchaseOrder) -> list[dict[str, Any]]:
    """Each delivered line with its order's requirements and its certificates, for the confirm dialog."""
    po_items = {item.id: item for item in po.items or []}
    labels = _labels(po)
    out: list[dict[str, Any]] = []
    for index, line in enumerate(gr.items or []):
        po_item = po_items.get(line.po_item_id) if line.po_item_id else None
        out.append(
            {
                "gr_item_id": line.id,
                "label": labels.get(po_item.id, str(index + 1)) if po_item else str(index + 1),
                "unit": (po_item.unit or "") if po_item else "",
                "quantity_received": line.quantity_received or "0",
                "batch_lot": line.batch_lot,
                "required_certificate_type": po_item.required_certificate_type if po_item else None,
                "requires_inspection": bool(po_item.requires_inspection) if po_item else False,
                "certificates": list(line.certificates or []),
            }
        )
    return out


def inspection_lines(gr: GoodsReceipt, po: PurchaseOrder) -> list[str]:
    """Labels of the delivered lines whose order asks for an incoming inspection."""
    po_items = {item.id: item for item in po.items or []}
    labels = _labels(po)
    out: list[str] = []
    for line in gr.items or []:
        po_item = po_items.get(line.po_item_id) if line.po_item_id else None
        if po_item is None or not po_item.requires_inspection:
            continue
        received = parse_money(line.quantity_received)
        if received is None or received <= 0:
            continue
        out.append(labels.get(po_item.id, po_item.description))
    return out


def _report_detail(report: ValidationReport, message: str, code: str) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "report": report.summary(),
        "errors": [
            {
                "rule_id": r.rule_id,
                "message": r.message,
                "element_ref": r.element_ref,
                "suggestion": r.suggestion,
            }
            for r in report.errors
        ],
    }


def report_to_dict(report: ValidationReport) -> dict[str, Any]:
    """A report in the traffic-light shape the receipt screens render."""
    summary = report.summary()
    return {
        "status": summary["status"],
        "score": summary["score"],
        "counts": summary["counts"],
        "results": [
            {
                "rule_id": r.rule_id,
                "rule_name": r.rule_name,
                "severity": r.severity.value,
                "category": r.category.value,
                "passed": r.passed,
                "message": r.message,
                "element_ref": r.element_ref,
                "suggestion": r.suggestion,
            }
            for r in report.results
        ],
    }


class ReceivingService:
    """Certificates, the confirmation gate, follow-ups and the payment release check."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Validation ──────────────────────────────────────────────────────────

    async def validate_receipt(self, gr: GoodsReceipt, po: PurchaseOrder) -> ValidationReport:
        """Run the ``goods_receipt`` rule set against a receipt."""
        return await validation_engine.validate(
            data=receipt_validation_payload(gr, po),
            rule_sets=[RECEIPT_RULE_SET],
            target_type="goods_receipt",
            target_id=str(gr.id),
            project_id=str(po.project_id),
            metadata={"locale": get_locale(), "operation": "confirm"},
        )

    async def validate_receipt_or_raise(self, gr: GoodsReceipt, po: PurchaseOrder) -> ValidationReport:
        """Validate and refuse confirmation (422) when an ERROR rule fails."""
        report = await self.validate_receipt(gr, po)
        if report.has_errors:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=_report_detail(
                    report,
                    "This goods receipt cannot be confirmed yet. See the problems listed below, "
                    "fix each one, then confirm again.",
                    "receipt_validation_failed",
                ),
            )
        return report

    # ── Certificates ────────────────────────────────────────────────────────

    async def check_documents(
        self,
        project_id: uuid.UUID,
        document_ids: list[uuid.UUID],
        *,
        uploaded_by: str | None = None,
    ) -> None:
        """Every attached document must be a document of this project (422 otherwise).

        ``uploaded_by`` narrows it further for a supplier: a portal account may
        attach only what it uploaded itself, never another document of the
        project it happens to know the id of.
        """
        wanted = {d for d in document_ids if d is not None}
        if not wanted:
            return
        try:
            from app.modules.documents.models import Document
        except ImportError:  # pragma: no cover - documents is a core module
            return
        stmt = select(Document.id).where(Document.id.in_(wanted), Document.project_id == project_id)
        if uploaded_by is not None:
            stmt = stmt.where(Document.uploaded_by == uploaded_by)
        found = set((await self.session.execute(stmt)).scalars().all())
        if found != wanted:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "code": "document_not_in_project",
                    "message": "An attached document does not belong to this project.",
                },
            )

    def certificate_row(
        self,
        gr_id: uuid.UUID,
        gr_item_id: uuid.UUID,
        data: GRCertificateCreate,
        *,
        source: str,
        created_by: str | None,
    ) -> GoodsReceiptCertificate:
        """A certificate row ready to add to the session."""
        return GoodsReceiptCertificate(
            receipt_id=gr_id,
            gr_item_id=gr_item_id,
            certificate_type=data.certificate_type,
            certificate_number=data.certificate_number or "",
            issuer=data.issuer,
            issue_date=data.issue_date,
            document_id=data.document_id,
            batch_number=data.batch_number,
            source=source,
            created_by=created_by,
        )

    async def add_certificate(
        self,
        gr: GoodsReceipt,
        po: PurchaseOrder,
        gr_item_id: uuid.UUID,
        data: GRCertificateCreate,
        *,
        actor_id: str | None,
    ) -> GoodsReceiptCertificate:
        """Attach a certificate to a line of a draft receipt.

        A confirmed receipt is a record of what was accepted, so its documents
        are not changed afterwards: a late certificate goes on a new receipt or
        on the inspection.
        """
        if gr.status != "draft":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Certificates can only be added while the goods receipt is a draft.",
            )
        if gr_item_id not in {line.id for line in gr.items or []}:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Goods receipt line not found")
        if data.document_id is not None:
            await self.check_documents(po.project_id, [data.document_id])
        cert = self.certificate_row(gr.id, gr_item_id, data, source=SOURCE_SITE, created_by=actor_id)
        self.session.add(cert)
        await self.session.flush()
        return cert

    async def delete_certificate(self, gr: GoodsReceipt, certificate_id: uuid.UUID) -> None:
        """Remove a certificate from a draft receipt."""
        if gr.status != "draft":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Certificates can only be removed while the goods receipt is a draft.",
            )
        cert = await self.session.get(GoodsReceiptCertificate, certificate_id)
        if cert is None or cert.receipt_id != gr.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Certificate not found")
        await self.session.delete(cert)
        await self.session.flush()

    # ── Follow-ups on confirmation ──────────────────────────────────────────

    async def goods_receipt_routes(self, project_id: uuid.UUID) -> list[Any]:
        """Active approval routes this project has for goods receipts.

        Only routes of the project itself: a route without a project carries
        nothing that says whose it is (the same reasoning the permits module
        applies to its internal release).
        """
        try:
            from app.modules.approval_routes.models import Route
        except ImportError:  # pragma: no cover - optional module
            return []
        stmt = (
            select(Route)
            .where(Route.project_id == project_id)
            .where(Route.target_kind == GR_TARGET_KIND)
            .where(Route.is_active.is_(True))
            .order_by(Route.name)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def resolve_route(self, options: GRConfirmRequest, project_id: uuid.UUID) -> Any | None:
        """The route the person confirming chose, or ``None`` when they chose none.

        Resolved before the receipt is flipped, so a bad choice is refused
        without confirming anything.
        """
        if not options.start_approval_route:
            return None
        routes = await self.goods_receipt_routes(project_id)
        if options.approval_route_id is not None:
            chosen = next((r for r in routes if r.id == options.approval_route_id), None)
            if chosen is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail={
                        "code": "approval_route_not_usable",
                        "message": "The chosen approval route is not an active goods receipt route of this project.",
                    },
                )
            return chosen
        if len(routes) == 1:
            return routes[0]
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "approval_route_missing" if not routes else "approval_route_ambiguous",
                "message": (
                    "This project has no active approval route for goods receipts."
                    if not routes
                    else "This project has several approval routes for goods receipts. Choose one."
                ),
            },
        )

    async def start_follow_ups(
        self,
        gr: GoodsReceipt,
        po: PurchaseOrder,
        *,
        route_id: uuid.UUID | None,
        create_inspection: bool,
        actor_id: str | None,
    ) -> dict[str, uuid.UUID | None]:
        """Start the chosen route and the due inspection in the caller's transaction.

        Returns the ids written onto the receipt. Events go out only once the
        transaction commits, so a subscriber never reads a receipt that a later
        failure rolled back.
        """
        # Everything read off the ORM rows is taken now: the writes below (the
        # approval engine's audit row, the inspection's numbering savepoint)
        # may expire them, and a later read would then lazy-load outside the
        # async greenlet.
        ref = receipt_ref(gr)
        gr_id = gr.id
        po_id = po.id
        project_id = po.project_id
        po_number = po.po_number
        lines = inspection_lines(gr, po) if create_inspection else []
        out: dict[str, uuid.UUID | None] = {"approval_instance_id": None, "inspection_id": None}
        actor_uuid: uuid.UUID | None = None
        try:
            actor_uuid = uuid.UUID(str(actor_id)) if actor_id else None
        except ValueError:
            actor_uuid = None

        if route_id is not None:
            from app.modules.approval_routes.schemas import InstanceCreate
            from app.modules.approval_routes.service import ApprovalRouteService

            instance = await ApprovalRouteService(self.session).start_instance(
                InstanceCreate(route_id=route_id, target_kind=GR_TARGET_KIND, target_id=gr_id),
                started_by=actor_uuid,
            )
            instance_id = instance.id
            out["approval_instance_id"] = instance_id
            publish_after_commit(
                self.session,
                "procurement.gr.approval_started",
                {
                    "gr_id": str(gr_id),
                    "po_id": str(po_id),
                    "project_id": str(project_id),
                    "approval_instance_id": str(instance_id),
                    "route_id": str(route_id),
                },
                source_module="oe_procurement",
            )

        if lines:
            from app.modules.inspections.schemas import InspectionCreate
            from app.modules.inspections.service import InspectionService

            inspection = await InspectionService(self.session).create_inspection(
                InspectionCreate(
                    project_id=project_id,
                    inspection_type="general",
                    title=f"Incoming inspection {po_number} / {ref}"[:500],
                    description="\n".join(lines)[:5000],
                    status="scheduled",
                    metadata={
                        "source": "goods_receipt",
                        "goods_receipt_id": str(gr_id),
                        "po_id": str(po_id),
                        "lines": lines,
                    },
                ),
                user_id=actor_id,
            )
            inspection_id = inspection.id
            out["inspection_id"] = inspection_id
            publish_after_commit(
                self.session,
                "procurement.gr.inspection_requested",
                {
                    "gr_id": str(gr_id),
                    "po_id": str(po_id),
                    "project_id": str(project_id),
                    "inspection_id": str(inspection_id),
                },
                source_module="oe_procurement",
            )
        return out

    # ── Payment release ─────────────────────────────────────────────────────

    async def payment_release_payload(self, po: PurchaseOrder, *, invoice_ref: str = "") -> dict[str, Any]:
        """The confirmed receipts of an order with their approval and inspection state."""
        receipts = list(
            (
                await self.session.execute(
                    select(GoodsReceipt)
                    .where(GoodsReceipt.po_id == po.id)
                    .where(GoodsReceipt.status == "confirmed")
                    .order_by(GoodsReceipt.receipt_date, GoodsReceipt.created_at)
                )
            )
            .scalars()
            .all()
        )
        approval: dict[uuid.UUID, tuple[str, uuid.UUID]] = {}
        inspection: dict[uuid.UUID, str] = {}
        ids = [gr.id for gr in receipts]
        if ids:
            try:
                from app.modules.approval_routes.models import Instance
            except ImportError:  # pragma: no cover - optional module
                Instance = None  # noqa: N806
            if Instance is not None:
                rows = (
                    await self.session.execute(
                        select(Instance.target_id, Instance.status, Instance.id)
                        .where(Instance.target_kind == GR_TARGET_KIND)
                        .where(Instance.target_id.in_(ids))
                        .where(Instance.status != "cancelled")
                        .order_by(Instance.started_at.desc(), Instance.created_at.desc())
                    )
                ).all()
                for target_id, inst_status, inst_id in rows:
                    approval.setdefault(target_id, (inst_status, inst_id))
            inspection_ids = [gr.inspection_id for gr in receipts if gr.inspection_id]
            if inspection_ids:
                try:
                    from app.modules.inspections.models import QualityInspection
                except ImportError:  # pragma: no cover - optional module
                    QualityInspection = None  # noqa: N806
                if QualityInspection is not None:
                    for ins_id, ins_status in (
                        await self.session.execute(
                            select(QualityInspection.id, QualityInspection.status).where(
                                QualityInspection.id.in_(inspection_ids)
                            )
                        )
                    ).all():
                        inspection[ins_id] = ins_status
        return {
            "id": str(po.id),
            "po_number": po.po_number,
            "invoice_ref": invoice_ref,
            "receipts": [
                {
                    "ref": receipt_ref(gr),
                    "gr_id": str(gr.id),
                    "approval_status": approval[gr.id][0] if gr.id in approval else None,
                    "approval_instance_id": str(approval[gr.id][1]) if gr.id in approval else None,
                    "inspection_status": inspection.get(gr.inspection_id) if gr.inspection_id else None,
                    "inspection_id": str(gr.inspection_id) if gr.inspection_id else None,
                }
                for gr in receipts
            ],
        }

    async def payment_release_report(self, po: PurchaseOrder, *, invoice_ref: str = "") -> ValidationReport:
        """Run the ``invoice_payment_release`` rule set for an order."""
        return await validation_engine.validate(
            data=await self.payment_release_payload(po, invoice_ref=invoice_ref),
            rule_sets=[PAYMENT_RELEASE_RULE_SET],
            target_type="purchase_order",
            target_id=str(po.id),
            project_id=str(po.project_id),
            metadata={"locale": get_locale(), "operation": "payment_release"},
        )


async def check_payment_release(
    session: AsyncSession,
    purchase_order_id: uuid.UUID | str | None,
    *,
    invoice_ref: str = "",
) -> ValidationReport | None:
    """Refuse (422) to release a payable invoice whose order fails the release rules.

    Called by the finance module when a payable invoice is approved or paid.
    ``None`` when the invoice names no order or the order no longer exists.
    """
    if not purchase_order_id:
        return None
    try:
        po_uuid = uuid.UUID(str(purchase_order_id))
    except ValueError:
        return None
    po = await session.get(PurchaseOrder, po_uuid)
    if po is None:
        return None
    report = await ReceivingService(session).payment_release_report(po, invoice_ref=invoice_ref)
    if report.has_errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=_report_detail(
                report,
                "This invoice cannot be released for payment yet. See the problems listed below.",
                "payment_release_blocked",
            ),
        )
    return report


__all__ = [
    "GR_TARGET_KIND",
    "PAYMENT_RELEASE_RULE_SET",
    "RECEIPT_RULE_SET",
    "SOURCE_SITE",
    "SOURCE_SUPPLIER_PORTAL",
    "ReceivingService",
    "check_payment_release",
    "inspection_lines",
    "receipt_ref",
    "receipt_validation_payload",
    "report_to_dict",
]
