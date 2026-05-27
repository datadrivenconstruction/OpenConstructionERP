"""Procurement ORM models.

Tables:
    oe_procurement_po            — purchase orders
    oe_procurement_po_item       — purchase order line items
    oe_procurement_goods_receipt — goods receipts against POs
    oe_procurement_gr_item       — goods receipt line items
    oe_procurement_requisition   — material requisitions (R7 FSM)
    oe_procurement_req_item      — requisition line items
"""

import uuid
from decimal import Decimal

from sqlalchemy import JSON, ForeignKey, Index, Integer, String, Text, UniqueConstraint
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
    issue_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    delivery_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Empty by default — service inherits the parent project's currency so
    # no PO silently shows EUR when the project is non-EUR (task #217).
    currency_code: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    amount_subtotal: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    tax_amount: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    amount_total: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
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
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Relationship
    purchase_order: Mapped["PurchaseOrder"] = relationship(back_populates="items")

    def __repr__(self) -> str:
        return f"<PurchaseOrderItem {self.description[:40]}>"


class GoodsReceipt(Base):
    """A goods receipt recorded against a purchase order."""

    __tablename__ = "oe_procurement_goods_receipt"

    po_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_procurement_po.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    receipt_date: Mapped[str] = mapped_column(String(20), nullable=False)
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
    __table_args__ = (Index("ix_req_project_status", "project_id", "status"),)

    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    requester_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    approver_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft", index=True)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    required_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    lead_time_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Computed from required_date - lead_time_days; stored for query efficiency
    estimated_delivery_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
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
    # Qty at each lifecycle stage — all stored as Decimal-strings (R7)
    quantity_requested: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    quantity_ordered: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    quantity_received: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    quantity_consumed: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    # Money fields as Decimal-strings (R7 money sweep)
    unit_cost: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False, default=Decimal("0"))
    extended_cost: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False, default=Decimal("0"))
    currency_code: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Relationship
    requisition: Mapped["MaterialRequisition"] = relationship(back_populates="items")

    def __repr__(self) -> str:
        return f"<MaterialRequisitionItem {self.description[:40]}>"
