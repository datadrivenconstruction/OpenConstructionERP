"""Procurement ORM models.

Tables:
    oe_procurement_po            - purchase orders
    oe_procurement_po_item       - purchase order line items
    oe_procurement_goods_receipt - goods receipts against POs
    oe_procurement_gr_item       - goods receipt line items
    oe_procurement_requisition   - material requisitions (R7 FSM)
    oe_procurement_req_item      - requisition line items
"""

import uuid
from decimal import Decimal, InvalidOperation

from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db_types import MoneyType
from app.database import GUID, Base


class PurchaseOrder(Base):
    """‌⁠‍A purchase order linked to a project and vendor."""

    __tablename__ = "oe_procurement_po"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "po_number",
            name="uq_procurement_po_project_number",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        nullable=False,
        index=True,
    )
    vendor_contact_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    po_number: Mapped[str] = mapped_column(String(50), nullable=False)
    po_type: Mapped[str] = mapped_column(String(50), nullable=False, default="standard")
    issue_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    delivery_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Empty by default - service inherits the parent project's currency so
    # no PO silently shows EUR when the project is non-EUR (task #217).
    currency_code: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    amount_subtotal: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    tax_amount: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    amount_total: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    # ── Retainage (Gap F, v6.x) ──────────────────────────────────────────
    # Retention withheld on a PO commitment. ``retention_percent`` is the
    # agreed retainage rate (e.g. 5.00 for 5%); ``retainage_amount`` is
    # computed = amount_total × percent / 100 and ``retainage_held`` nets
    # off whatever has already been released. ``retainage_released_amount``
    # is the cumulative Decimal-string total released so far. Money is
    # never blended across currencies - every value stays in the PO's own
    # ``currency_code`` (the report rolls up per-currency).
    retention_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
        default=Decimal("0.00"),
        server_default="0.00",
        index=True,
        doc="Retention percentage (e.g. 5.00 for 5%)",
    )
    retain_on_receipt: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        doc="True: retainage applies at goods receipt; False: at invoice",
    )
    retainage_released_amount: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="0",
        server_default="0",
        doc="Cumulative retainage released (Decimal string)",
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft", index=True)
    payment_terms: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # Relationships
    items: Mapped[list["PurchaseOrderItem"]] = relationship(
        back_populates="purchase_order",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    goods_receipts: Mapped[list["GoodsReceipt"]] = relationship(
        back_populates="purchase_order",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def retainage_amount(self) -> Decimal:
        """Computed retention withheld = amount_total × retention_percent / 100.

        Quantised to four decimal places to match the NUMERIC(18, 4) precision
        of the release-log column. Never blends currencies - the result is in
        this PO's own ``currency_code``.
        """
        try:
            total = Decimal(str(self.amount_total or "0"))
        except (InvalidOperation, ValueError, TypeError):
            total = Decimal("0")
        pct = self.retention_percent if self.retention_percent is not None else Decimal("0")
        if not isinstance(pct, Decimal):
            try:
                pct = Decimal(str(pct))
            except (InvalidOperation, ValueError, TypeError):
                pct = Decimal("0")
        return (total * pct / Decimal("100")).quantize(Decimal("0.0001"))

    def retainage_held(self) -> Decimal:
        """Computed = retainage_amount − retainage_released_amount (floored at 0)."""
        withheld = self.retainage_amount()
        try:
            released = Decimal(str(self.retainage_released_amount or "0"))
        except (InvalidOperation, ValueError, TypeError):
            released = Decimal("0")
        return max(withheld - released, Decimal("0"))

    def __repr__(self) -> str:
        return f"<PurchaseOrder {self.po_number} ({self.status})>"


class PurchaseOrderItem(Base):
    """‌⁠‍A single line item within a purchase order."""

    __tablename__ = "oe_procurement_po_item"

    po_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_procurement_po.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    quantity: Mapped[str] = mapped_column(String(50), nullable=False, default="1")
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    unit_rate: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    amount: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    wbs_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    cost_category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # ── Cost Spine linkage (v6.4) ────────────────────────────────────────
    # Additive nullable link to the cost line this PO item commits against.
    cost_line_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Relationship
    purchase_order: Mapped["PurchaseOrder"] = relationship(back_populates="items")

    def __repr__(self) -> str:
        return f"<PurchaseOrderItem {self.description[:40]}>"


class PORetainageRelease(Base):
    """Audit log of retainage-release transactions on a purchase order.

    Each row records one MANAGER-approved release of withheld retainage:
    who released it, when, how much, and an optional reason. The cumulative
    sum is mirrored onto ``PurchaseOrder.retainage_released_amount`` so the
    held balance can be computed without re-aggregating this log on every
    read; this table is the immutable evidence trail.
    """

    __tablename__ = "oe_procurement_po_retainage_release"
    __table_args__ = (Index("ix_retainage_po_date", "po_id", "release_date"),)

    po_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_procurement_po.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    release_date: Mapped[str] = mapped_column(String(40), nullable=False)
    release_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
    )
    release_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    released_by_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<PORetainageRelease po={self.po_id} amount={self.release_amount}>"


class GoodsReceipt(Base):
    """A goods receipt recorded against a purchase order."""

    __tablename__ = "oe_procurement_goods_receipt"

    po_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_procurement_po.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    receipt_date: Mapped[str] = mapped_column(String(40), nullable=False)
    received_by_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    delivery_note_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft", index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # Relationships
    purchase_order: Mapped["PurchaseOrder"] = relationship(back_populates="goods_receipts")
    items: Mapped[list["GoodsReceiptItem"]] = relationship(
        back_populates="goods_receipt",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<GoodsReceipt PO={self.po_id} date={self.receipt_date} ({self.status})>"


class GoodsReceiptItem(Base):
    """A single item within a goods receipt."""

    __tablename__ = "oe_procurement_gr_item"

    receipt_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_procurement_goods_receipt.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    po_item_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_procurement_po_item.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    quantity_ordered: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    quantity_received: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    quantity_rejected: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationship
    goods_receipt: Mapped["GoodsReceipt"] = relationship(back_populates="items")

    def __repr__(self) -> str:
        return f"<GoodsReceiptItem recv={self.quantity_received} rej={self.quantity_rejected}>"


# ── Material Requisition (R7 FSM) ─────────────────────────────────────────────


class MaterialRequisition(Base):
    """A material requisition request with FSM lifecycle.

    FSM: draft → submitted → approved → ordered → received → consumed
    """

    __tablename__ = "oe_procurement_requisition"
    __table_args__ = (
        Index("ix_req_project_status", "project_id", "status"),
        UniqueConstraint(
            "project_id",
            "req_number",
            name="uq_procurement_req_project_number",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    # Human-facing sequential number per project (e.g. "MR-0001"). Generated
    # service-side with a retry-on-collision loop, scoped unique per project.
    req_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    requester_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    approver_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft", index=True)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    required_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    lead_time_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Computed from required_date - lead_time_days; stored for query efficiency
    estimated_delivery_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # FK to PO once approved → ordered
    po_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_procurement_po.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # Relationships
    items: Mapped[list["MaterialRequisitionItem"]] = relationship(
        back_populates="requisition",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<MaterialRequisition {self.id} ({self.status})>"


class MaterialRequisitionItem(Base):
    """A single material line within a requisition."""

    __tablename__ = "oe_procurement_req_item"

    requisition_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_procurement_requisition.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Qty at each lifecycle stage - all stored as Decimal-strings (R7)
    quantity_requested: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    quantity_ordered: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    quantity_received: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    quantity_consumed: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    # Money fields as Decimal-strings (R7 money sweep)
    unit_cost: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False, default=Decimal("0"))
    extended_cost: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False, default=Decimal("0"))
    currency_code: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    # ── Cost Spine linkage (v6.4) ────────────────────────────────────────
    # Additive nullable link to the cost line this requisition item maps to.
    cost_line_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Relationship
    requisition: Mapped["MaterialRequisition"] = relationship(back_populates="items")

    def __repr__(self) -> str:
        return f"<MaterialRequisitionItem {self.description[:40]}>"
