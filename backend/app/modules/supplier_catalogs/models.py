"""‌⁠‍Supplier Catalogs ORM models.

Tables (prefix ``oe_supplier_catalogs_``):
    vendor              — supplier master (with contacts in JSON)
    item_category       — material/service hierarchy
    catalog_item        — master catalog of items
    price_list          — vendor price list version
    catalog_entry       — vendor-specific price for an item
    pr                  — purchase requisition
    pr_line             — PR line
    po                  — extended purchase order
    po_line             — PO line
    gr                  — goods receipt (extended with batch/photo)
    gr_line             — GR line
    invoice             — vendor invoice
    match_record        — 3-way match audit trail
    warehouse           — physical stock location
    stock_balance       — current on-hand quantity
    stock_movement      — IN/OUT/TRANSFER/ADJUST/RESERVATION/RELEASE
    commodity_code      — UNSPSC / eClass classification dropdown source
    tolerance_profile   — per-tenant configurable 3-way match tolerance bands
    kyc_document        — region-aware vendor KYC docs with expiry
    scorecard           — vendor performance scorecard (weighted multi-criteria)
"""

from __future__ import annotations

import uuid
from datetime import date as _date
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base

# ── Vendor master ────────────────────────────────────────────────────────────


class Vendor(Base):
    """‌⁠‍Supplier master record."""

    __tablename__ = "oe_supplier_catalogs_vendor"

    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tax_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    contact_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="active",
        index=True,
    )
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="EUR")
    payment_terms_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    country_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    region: Mapped[str | None] = mapped_column(String(64), nullable=True)
    categories_json: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    preferred_for_json: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    contacts_json: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Name of the TolerianceProfile this vendor should be matched against.
    # Resolved by name (not FK) so the link survives profile deletes/renames.
    tolerance_profile_name: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="default",
        server_default="default",
    )

    price_lists: Mapped[list[PriceList]] = relationship(
        back_populates="vendor",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Vendor {self.code} ({self.status})>"


# ── Catalog ──────────────────────────────────────────────────────────────────


class ItemCategory(Base):
    """‌⁠‍Hierarchical category tree for materials and services."""

    __tablename__ = "oe_supplier_catalogs_item_category"

    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_supplier_catalogs_item_category.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    classification_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)

    def __repr__(self) -> str:
        return f"<ItemCategory {self.code}>"


class CatalogItem(Base):
    """Master catalog item (material / equipment / service)."""

    __tablename__ = "oe_supplier_catalogs_catalog_item"

    sku: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_supplier_catalogs_item_category.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    unit_of_measure: Mapped[str] = mapped_column(String(20), nullable=False, default="pcs")
    manufacturer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mpn: Mapped[str | None] = mapped_column(String(100), nullable=True)
    spec_json: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    hazard_class: Mapped[str | None] = mapped_column(String(50), nullable=True)
    shelf_life_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reorder_point: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
    )
    # GS1 GTIN (global trade item number); 8/12/13/14 digits — string for flexibility
    gtin: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    # UNSPSC/eClass commodity code reference (e.g. "30161501" for portland cement)
    commodity_code: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        index=True,
    )
    commodity_scheme: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="unspsc",
        server_default="unspsc",
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    def __repr__(self) -> str:
        return f"<CatalogItem {self.sku}>"


class PriceList(Base):
    """A versioned price list from a vendor."""

    __tablename__ = "oe_supplier_catalogs_price_list"

    vendor_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_supplier_catalogs_vendor.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    valid_from: Mapped[str | None] = mapped_column(String(20), nullable=True)
    valid_to: Mapped[str | None] = mapped_column(String(20), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="EUR")
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="draft",
        index=True,
    )
    uploaded_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    vendor: Mapped[Vendor] = relationship(back_populates="price_lists")
    entries: Mapped[list[CatalogEntry]] = relationship(
        back_populates="price_list",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<PriceList {self.name} vendor={self.vendor_id}>"


class CatalogEntry(Base):
    """A vendor's price for a single catalog item within a price list."""

    __tablename__ = "oe_supplier_catalogs_catalog_entry"
    __table_args__ = (
        UniqueConstraint(
            "price_list_id",
            "catalog_item_id",
            name="uq_supplier_catalogs_entry_pricelist_item",
        ),
    )

    price_list_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_supplier_catalogs_price_list.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    catalog_item_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_supplier_catalogs_catalog_item.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    vendor_sku: Mapped[str | None] = mapped_column(String(100), nullable=True)
    unit_price: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
    )
    min_order_qty: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("1"),
    )
    lead_time_days: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    last_purchased_at: Mapped[str | None] = mapped_column(String(30), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    price_list: Mapped[PriceList] = relationship(back_populates="entries")


# ── Purchase Requisition ─────────────────────────────────────────────────────


class PurchaseRequisition(Base):
    """A request to procure items from approved vendors."""

    __tablename__ = "oe_supplier_catalogs_pr"

    number: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    requested_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    requested_at: Mapped[str | None] = mapped_column(String(30), nullable=True)
    needed_by: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="draft",
        index=True,
    )
    total_estimate: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=Decimal("0"),
    )
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="EUR")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    approval_chain_json: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )

    lines: Mapped[list[PRLine]] = relationship(
        back_populates="pr",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class PRLine(Base):
    """A single line on a purchase requisition."""

    __tablename__ = "oe_supplier_catalogs_pr_line"

    pr_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_supplier_catalogs_pr.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    catalog_item_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_supplier_catalogs_catalog_item.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("1"))
    unit_of_measure: Mapped[str] = mapped_column(String(20), nullable=False, default="pcs")
    estimated_unit_price: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
    )
    estimated_total: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=Decimal("0"),
    )

    pr: Mapped[PurchaseRequisition] = relationship(back_populates="lines")


# ── Extended Purchase Order ──────────────────────────────────────────────────


class SupplierPurchaseOrder(Base):
    """Extended Purchase Order — adds vendor master FK + contract + PR link.

    NOTE: This is the supplier_catalogs PO, NOT the procurement.PurchaseOrder.
    The two coexist; the procurement table is kept for legacy v2 compatibility.
    """

    __tablename__ = "oe_supplier_catalogs_po"

    number: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_supplier_catalogs_vendor.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    contract_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    pr_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_supplier_catalogs_pr.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="draft",
        index=True,
    )
    order_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    expected_delivery: Mapped[str | None] = mapped_column(String(20), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="EUR")
    subtotal: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=Decimal("0"),
    )
    tax: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    terms: Mapped[str | None] = mapped_column(Text, nullable=True)

    lines: Mapped[list[POLine]] = relationship(
        back_populates="po",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    receipts: Mapped[list[SupplierGoodsReceipt]] = relationship(
        back_populates="po",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class POLine(Base):
    """A PO line item, with running received/invoiced counters."""

    __tablename__ = "oe_supplier_catalogs_po_line"

    po_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_supplier_catalogs_po.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    catalog_item_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_supplier_catalogs_catalog_item.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    ordered_qty: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
    )
    unit_of_measure: Mapped[str] = mapped_column(String(20), nullable=False, default="pcs")
    unit_price: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
    )
    line_total: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=Decimal("0"),
    )
    received_qty: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
    )
    invoiced_qty: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
    )

    po: Mapped[SupplierPurchaseOrder] = relationship(back_populates="lines")


# ── Goods Receipt ────────────────────────────────────────────────────────────


class SupplierGoodsReceipt(Base):
    """Goods received against a PO; advances stock on post()."""

    __tablename__ = "oe_supplier_catalogs_gr"

    number: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)
    po_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_supplier_catalogs_po.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_supplier_catalogs_warehouse.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    received_at: Mapped[str | None] = mapped_column(String(30), nullable=True)
    received_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="draft",
        index=True,
    )
    scan_method: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    photos_json: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    discrepancy_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    po: Mapped[SupplierPurchaseOrder] = relationship(back_populates="receipts")
    lines: Mapped[list[GRLine]] = relationship(
        back_populates="gr",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class GRLine(Base):
    """A goods-receipt line tied to a PO line."""

    __tablename__ = "oe_supplier_catalogs_gr_line"

    gr_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_supplier_catalogs_gr.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    po_line_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_supplier_catalogs_po_line.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    received_qty: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
    )
    accepted_qty: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
    )
    rejected_qty: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
    )
    batch_lot: Mapped[str | None] = mapped_column(String(100), nullable=True)
    serial_numbers_json: Mapped[list | None] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    gr: Mapped[SupplierGoodsReceipt] = relationship(back_populates="lines")


# ── Vendor Invoice & 3-way match ─────────────────────────────────────────────


class VendorInvoice(Base):
    """An invoice received from a vendor, optionally tied to a PO."""

    __tablename__ = "oe_supplier_catalogs_invoice"

    number: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_supplier_catalogs_vendor.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    po_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_supplier_catalogs_po.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    invoice_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    due_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="EUR")
    subtotal: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=Decimal("0"),
    )
    tax: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="received",
        index=True,
    )
    three_way_match_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        index=True,
    )
    exception_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # PEPPOL UBL 2.1 / e-invoice tracking
    source: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="manual",
        server_default="manual",
    )  # manual | peppol | edi | email_pdf
    peppol_message_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )
    line_level_match_json: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    lines: Mapped[list[VendorInvoiceLine]] = relationship(
        back_populates="invoice",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class VendorInvoiceLine(Base):
    """A single line on a vendor invoice — required for line-level 3-way match.

    PEPPOL UBL 2.1 ingest fills these from ``cac:InvoiceLine`` entries; manual
    invoices can be created header-only and lines added later (or omitted, in
    which case match falls back to header totals).
    """

    __tablename__ = "oe_supplier_catalogs_invoice_line"

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_supplier_catalogs_invoice.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    po_line_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_supplier_catalogs_po_line.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
    )
    unit_of_measure: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pcs",
    )
    unit_price: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
    )
    line_total: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=Decimal("0"),
    )
    # Vendor-supplied identifier (PEPPOL: cac:Item/cac:SellersItemIdentification)
    vendor_sku: Mapped[str | None] = mapped_column(String(100), nullable=True)

    invoice: Mapped[VendorInvoice] = relationship(back_populates="lines")


class ThreeWayMatchRecord(Base):
    """Audit trail of a 3-way match attempt against an invoice."""

    __tablename__ = "oe_supplier_catalogs_match_record"

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_supplier_catalogs_invoice.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    po_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_supplier_catalogs_po.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    gr_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_supplier_catalogs_gr.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    matched_at: Mapped[str | None] = mapped_column(String(30), nullable=True)
    matched_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    price_variance: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
    )
    qty_variance: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="auto_matched",
        index=True,
    )
    tolerance_used_pct: Mapped[Decimal] = mapped_column(
        Numeric(8, 4),
        nullable=False,
        default=Decimal("2.0"),
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


# ── Warehouse & stock ────────────────────────────────────────────────────────


class Warehouse(Base):
    """A physical (or virtual) location holding inventory."""

    __tablename__ = "oe_supplier_catalogs_warehouse"

    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    manager_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="active",
        index=True,
    )


class StockBalance(Base):
    """Current on-hand quantity per (warehouse, item, batch)."""

    __tablename__ = "oe_supplier_catalogs_stock_balance"
    __table_args__ = (
        UniqueConstraint(
            "warehouse_id",
            "catalog_item_id",
            "batch_lot",
            name="uq_supplier_catalogs_balance_wh_item_batch",
        ),
    )

    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_supplier_catalogs_warehouse.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    catalog_item_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_supplier_catalogs_catalog_item.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    batch_lot: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    quantity_on_hand: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
    )
    quantity_reserved: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
    )
    unit_cost_avg: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
    )
    last_movement_at: Mapped[str | None] = mapped_column(String(30), nullable=True)


class StockMovement(Base):
    """An immutable audit row for every stock change."""

    __tablename__ = "oe_supplier_catalogs_stock_movement"

    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_supplier_catalogs_warehouse.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    catalog_item_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_supplier_catalogs_catalog_item.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    movement_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
    )  # in / out / transfer / adjust / reservation / release
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
    )
    unit_cost: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
    )
    reference_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reference_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    batch_lot: Mapped[str | None] = mapped_column(String(100), nullable=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    performed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    performed_at: Mapped[str | None] = mapped_column(String(30), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )


# ── Commodity codes (UNSPSC / eClass) ───────────────────────────────────────


class CommodityCode(Base):
    """A UN-SPSC or eClass commodity-classification entry.

    Seeded from public CSVs that ship with the module. Used by:
        * Vendor master (``categories_json`` keys reference this table's ``code``)
        * CatalogItem (optional 1:1 FK ``commodity_code_id``)
        * Spend analytics rollups
    """

    __tablename__ = "oe_supplier_catalogs_commodity_code"
    __table_args__ = (
        UniqueConstraint(
            "scheme",
            "code",
            name="uq_supplier_catalogs_commodity_scheme_code",
        ),
    )

    scheme: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="unspsc",
        server_default="unspsc",
        index=True,
    )  # unspsc | eclass | cpv (EU public procurement)
    code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_code: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
        index=True,
    )
    level: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="1",
    )

    def __repr__(self) -> str:
        return f"<CommodityCode {self.scheme}:{self.code}>"


# ── Tolerance profile (per-tenant 3-way match config) ───────────────────────


class TolerianceProfile(Base):
    """Configurable per-tenant tolerance bands for 3-way matching.

    Resolved at match time by ``name``: ``default`` is the fallback profile
    that ships seeded with every installation. Tenants can edit the default
    or add named profiles (e.g. "strategic-supplier" with tighter bands).
    """

    __tablename__ = "oe_supplier_catalogs_tolerance_profile"

    name: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
        index=True,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Price tolerance: absolute (currency) AND percentage — both checked
    price_tolerance_pct: Mapped[Decimal] = mapped_column(
        Numeric(8, 4),
        nullable=False,
        default=Decimal("2.0"),
    )
    price_tolerance_abs: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
    )
    # Quantity tolerance: percentage
    qty_tolerance_pct: Mapped[Decimal] = mapped_column(
        Numeric(8, 4),
        nullable=False,
        default=Decimal("0"),
    )
    # Period tolerance: days early/late on delivery vs PO.expected_delivery
    period_tolerance_days: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=7,
    )
    # If GR is required (most installs yes); set false for service POs
    require_gr: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="1",
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )

    def __repr__(self) -> str:
        return f"<TolerianceProfile {self.name}>"


# ── KYC documents ───────────────────────────────────────────────────────────


class KYCDocument(Base):
    """A KYC / tax-compliance document tied to a vendor.

    ``doc_type`` is region-aware:
        * ``w9``        — US IRS form W-9 (Request for Taxpayer ID)
        * ``vat_cert``  — EU VAT registration certificate
        * ``gst``       — India GST registration
        * ``trn``       — UAE Tax Registration Number
        * ``coi``       — Certificate of Insurance
        * ``iso``       — ISO 9001/14001/45001 certificate
        * ``other``     — generic
    """

    __tablename__ = "oe_supplier_catalogs_kyc_document"

    vendor_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_supplier_catalogs_vendor.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    doc_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    document_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    issued_on: Mapped[_date | None] = mapped_column(Date, nullable=True)
    expires_on: Mapped[_date | None] = mapped_column(Date, nullable=True, index=True)
    issuing_country: Mapped[str | None] = mapped_column(String(8), nullable=True)
    issuing_authority: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="active",
        server_default="active",
        index=True,
    )  # active | expired | rejected | pending_review
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    verified_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<KYCDocument {self.doc_type} vendor={self.vendor_id}>"


# ── Vendor scorecard ────────────────────────────────────────────────────────


class VendorScorecard(Base):
    """Period-scoped composite scorecard for a single vendor.

    Recomputed on demand (or on schedule) by
    :meth:`SupplierCatalogsService.recompute_scorecard`. The formula is:

        score = (delivery_score * w_delivery
               + quality_score  * w_quality
               + price_score    * w_price
               + esg_score      * w_esg) / sum(weights)

    Default weights (sum = 100): delivery 30, quality 30, price 20, esg 20.
    """

    __tablename__ = "oe_supplier_catalogs_scorecard"
    __table_args__ = (
        UniqueConstraint(
            "vendor_id",
            "period_start",
            "period_end",
            name="uq_supplier_catalogs_scorecard_vendor_period",
        ),
    )

    vendor_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_supplier_catalogs_vendor.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    period_start: Mapped[_date] = mapped_column(Date, nullable=False)
    period_end: Mapped[_date] = mapped_column(Date, nullable=False)
    # Sub-scores, each 0..100
    delivery_score: Mapped[Decimal] = mapped_column(
        Numeric(6, 2),
        nullable=False,
        default=Decimal("0"),
    )
    quality_score: Mapped[Decimal] = mapped_column(
        Numeric(6, 2),
        nullable=False,
        default=Decimal("0"),
    )
    price_score: Mapped[Decimal] = mapped_column(
        Numeric(6, 2),
        nullable=False,
        default=Decimal("0"),
    )
    esg_score: Mapped[Decimal] = mapped_column(
        Numeric(6, 2),
        nullable=False,
        default=Decimal("0"),
    )
    composite_score: Mapped[Decimal] = mapped_column(
        Numeric(6, 2),
        nullable=False,
        default=Decimal("0"),
    )
    # Audit trail of inputs that fed the formula
    inputs_json: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    weights_json: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<VendorScorecard vendor={self.vendor_id} score={self.composite_score}>"


# ── Public aliases ───────────────────────────────────────────────────────────
# The classes were renamed away from ``PurchaseOrder`` / ``GoodsReceipt`` to
# avoid a SQLAlchemy registry collision with the legacy ``procurement`` module
# (string-based relationship lookups across the shared declarative base would
# otherwise fail with "Multiple classes found"). Callers inside the
# supplier_catalogs module — service.py, router.py, seed.py, tests — keep
# using the unqualified names via these aliases.

PurchaseOrder = SupplierPurchaseOrder
GoodsReceipt = SupplierGoodsReceipt
