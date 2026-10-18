# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Procurement ORM models.

Tables:
    oe_procurement_po            - purchase orders
    oe_procurement_po_item       - purchase order line items
    oe_procurement_goods_receipt - goods receipts against POs
    oe_procurement_gr_item       - goods receipt line items
    oe_procurement_gr_cert       - material certificates (e.g. EN 10204) on a receipt line
    oe_procurement_requisition   - material requisitions (R7 FSM)
    oe_procurement_req_item      - requisition line items
    oe_procurement_req_item_source - BOQ provenance of a requisition line
    oe_procurement_project_settings - per-project order owner and default approvers
    oe_procurement_req_ext_line  - external order lines reconciled against requisition lines
    oe_procurement_req_change    - replayable requisition change feed
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
    """A purchase order linked to a project and vendor."""

    __tablename__ = "oe_procurement_po"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "po_number",
            name="uq_procurement_po_project_number",
        ),
        # Hot filter: both the supplier scorecard (vendor_contact_id == X AND
        # created_at >= cutoff) and the PO-list ``vendor_contact_id`` filter
        # scan on this column, which was previously unindexed - a full table
        # scan as PO volume grows. The composite leads on vendor_contact_id
        # (equality) and trails on created_at (the scorecard range + the list's
        # ORDER BY created_at DESC), so it serves both queries.
        Index(
            "ix_procurement_po_vendor_created",
            "vendor_contact_id",
            "created_at",
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
    # The VAT rate the order is taxed at, as a decimal-string percentage. Set,
    # it drives ``tax_amount`` from the subtotal; null keeps the absolute tax
    # the order was given, which is how every order before issue #515 reads.
    # A new order without one takes the project's ``default_vat_rate``.
    tax_rate_pct: Mapped[str | None] = mapped_column(String(20), nullable=True)
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
    # The supplier's order confirmation, recorded by the buyer once an issued
    # order is answered. Null until then, which is how the register finds the
    # orders nobody has confirmed. The confirmed date sits beside
    # ``delivery_date`` instead of overwriting it: the gap is the point.
    supplier_acknowledged_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    supplier_acknowledged_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    supplier_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    supplier_confirmed_delivery_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # The overrun a supplier invoice may carry before the invoice match warns,
    # as a percentage of the order and/or an amount in its currency. Decimal
    # strings; null keeps the one-cent rounding band.
    invoice_tolerance_pct: Mapped[str | None] = mapped_column(String(20), nullable=True)
    invoice_tolerance_abs: Mapped[str | None] = mapped_column(String(50), nullable=True)
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
    """A single line item within a purchase order."""

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
    # The requisition line this order line was converted from (issue #516).
    # Written only by the requisition-to-order conversion and carried through
    # a line replace, so an order line leads back to the requisition line and
    # from there to the BOQ positions it was raised from. A plain column, like
    # the requisition's own provenance, so a deleted line does not erase it.
    requisition_item_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)

    # ── Receiving requirements (BF-01) ───────────────────────────────────
    # What the delivery of this line must arrive with. The certificate type is
    # agreed with the supplier when the material is ordered (EN 10204 says the
    # same: the document type is part of the order), so it lives on the order
    # line, not on a catalogue item. A code from the certificate-type catalogue
    # (``procurement/catalogues``); null means no certificate is required.
    required_certificate_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # True when the site must inspect this material on arrival: confirming its
    # receipt then offers a pending incoming inspection.
    requires_inspection: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )

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
    # Who put the receipt on file: ``site`` (recorded by site staff) or
    # ``supplier_portal`` (a delivery the supplier submitted through the portal).
    # Either way it enters as a draft that site staff confirm.
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="site", server_default="site")
    # The portal account that submitted it, for a supplier-submitted delivery.
    portal_user_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    # Follow-ups the person confirming the receipt chose to start: the approval
    # instance (``approval_routes``, target kind ``goods_receipt``) and the
    # incoming inspection (``inspections``). Plain ids, no foreign keys: both
    # live in optional modules.
    approval_instance_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    inspection_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
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
    # Traceability carried over from the supplier catalogue receipt line when
    # procurement became the one purchasing flow: the supplier's batch or lot
    # and the serial numbers of the units received on this line.
    batch_lot: Mapped[str | None] = mapped_column(String(100), nullable=True)
    serial_numbers: Mapped[list | None] = mapped_column(JSON, nullable=True)  # type: ignore[assignment]

    # Relationship
    goods_receipt: Mapped["GoodsReceipt"] = relationship(back_populates="items")
    # The inspection documents that came with the material on this line. Read
    # with the receipt every time, which is why they load eagerly.
    certificates: Mapped[list["GoodsReceiptCertificate"]] = relationship(
        back_populates="gr_item",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="GoodsReceiptCertificate.created_at",
    )

    def __repr__(self) -> str:
        return f"<GoodsReceiptItem recv={self.quantity_received} rej={self.quantity_rejected}>"


class GoodsReceiptCertificate(Base):
    """An inspection document delivered with the material on one receipt line.

    Typically an EN 10204 certificate (2.1, 2.2, 3.1, 3.2), but the type is a
    code from the certificate-type catalogue, which is data: a project or a
    country pack can add its own types without a schema change. The batch or
    heat number is what ties the document to the physical material, so the
    receipt validation compares it with the batch recorded on the line.
    """

    __tablename__ = "oe_procurement_gr_cert"

    receipt_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey(
            "oe_procurement_goods_receipt.id",
            ondelete="CASCADE",
            name="fk_oe_procurement_gr_cert_receipt_id",
        ),
        nullable=False,
        index=True,
    )
    gr_item_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey(
            "oe_procurement_gr_item.id",
            ondelete="CASCADE",
            name="fk_oe_procurement_gr_cert_gr_item_id",
        ),
        nullable=False,
        index=True,
    )
    certificate_type: Mapped[str] = mapped_column(String(40), nullable=False)
    certificate_number: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    issuer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    issue_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # The scanned or digital certificate in the documents module, when attached.
    document_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # Batch, lot or heat number printed on the certificate.
    batch_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # ``site`` or ``supplier_portal``, the same vocabulary as the receipt.
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="site", server_default="site")
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    gr_item: Mapped["GoodsReceiptItem"] = relationship(back_populates="certificates", lazy="raise_on_sql")

    def __repr__(self) -> str:
        return f"<GoodsReceiptCertificate {self.certificate_type} {self.certificate_number}>"


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
    # Who submitted the requisition last. The four-eyes check reads it: the
    # person who submitted may not approve or reject the same requisition.
    submitted_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # When the approver decided, and what they said. A rejection always
    # carries its reason here; an approval may carry a note.
    decided_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    decision_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The supplier chosen from the Vendor directory
    # (``oe_supplier_catalogs_vendor``). A plain column: procurement does not
    # depend on the supplier catalogue module, and the choice must survive a
    # vendor being retired.
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft", index=True)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    required_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    lead_time_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # When the supplier is expected to deliver: the delivery date of the order
    # the requisition was converted into, written at conversion and cleared
    # when that order is released. None before an order exists. It is never
    # required_date - lead_time_days, which is the latest ordering date and is
    # derived on read (issue #516).
    estimated_delivery_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # FK to PO once approved → ordered
    po_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_procurement_po.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Who places the orders for this requisition: ``ocerp`` (purchase orders
    # are raised here) or ``external`` (another purchasing system orders and
    # reports back). Null reads as ``ocerp``. Taken from the project setting
    # when the requisition is created and editable while it is a draft.
    order_owner: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Designated approvers in order (user id strings). Empty or null means any
    # holder of ``procurement.approve_requisition`` approves in one step.
    approval_chain: Mapped[list | None] = mapped_column(JSON, nullable=True)  # type: ignore[assignment]
    # How many designated approvers have approved in the current round.
    approval_step: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Bumped on every change that lands in the change feed. Doubles as the
    # row lock a line-level conversion takes before it counts what is ordered.
    row_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # A caller-chosen key that makes a create idempotent: a second create in
    # the same project with the same key returns the first requisition.
    client_request_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
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
    # The supplier catalogue item this line asks for, when one is known. It is
    # the only identity two lines are merged on without a person confirming it:
    # a shared description and unit are not proof of the same material.
    catalog_item_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    # The supplier the requester suggests for this line, from the Vendor
    # directory. Inherited from the BOQ sources when they agree, overridable
    # and clearable. A suggestion only: the order's supplier is chosen at
    # approval or conversion and is never taken from here silently.
    suggested_vendor_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    # When this line is needed on site. Null means the requisition's own
    # ``required_date`` applies. Kept apart from the supplier's expected or
    # confirmed delivery date, which belongs to the order.
    required_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # The schedule activity the date was proposed from, the buffer in days
    # before its start, and the activity start the proposal was read from.
    # A later schedule change does not rewrite ``required_date``: the anchor
    # lets the line show that the activity has moved since.
    schedule_activity_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    schedule_buffer_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    schedule_anchor_date: Mapped[str | None] = mapped_column(String(40), nullable=True)

    # Relationship
    requisition: Mapped["MaterialRequisition"] = relationship(back_populates="items")
    # Where the requested quantity came from. A line raised from the buy list
    # usually has several sources, one per contributing BOQ position.
    sources: Mapped[list["MaterialRequisitionItemSource"]] = relationship(
        back_populates="item",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="MaterialRequisitionItemSource.sort_order",
    )

    def __repr__(self) -> str:
        return f"<MaterialRequisitionItem {self.description[:40]}>"


class MaterialRequisitionItemSource(Base):
    """One BOQ resource that contributes quantity to a requisition line.

    Keeps the position, the resource within the position's resource split, the
    quantity and unit as they stood at the source, and the cost line the
    position pointed at when the line was written. The source quantity is never
    rewritten by a later BOQ edit, so what was asked for stays explainable.
    """

    __tablename__ = "oe_procurement_req_item_source"

    item_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_procurement_req_item.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Plain columns rather than foreign keys: the position or cost line may be
    # deleted later, and the requisition must still say where it came from.
    boq_position_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    resource_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    quantity: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    cost_line_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # The supplier the BOQ suggested for this source when the line was written:
    # the resource's own suggestion, else the position default. Kept per source
    # so sources that disagree stay visible on the line.
    suggested_vendor_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    item: Mapped["MaterialRequisitionItem"] = relationship(back_populates="sources", lazy="raise_on_sql")

    def __repr__(self) -> str:
        return f"<MaterialRequisitionItemSource {self.boq_position_id} {self.resource_key}>"


class ProcurementProjectSettings(Base):
    """Per-project purchasing settings for requisitions (issue #516).

    ``order_owner`` says where orders for this project's requisitions are
    placed: ``ocerp`` (purchase orders are raised here) or ``external`` (an
    outside purchasing system orders, and OCERP only reconciles what it
    reports). Award subscribers read it and draft no order when it is
    ``external``. ``default_approval_chain`` is copied onto new requisitions.
    """

    __tablename__ = "oe_procurement_project_settings"

    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, unique=True, index=True)
    order_owner: Mapped[str] = mapped_column(String(20), nullable=False, default="ocerp", server_default="ocerp")
    default_approval_chain: Mapped[list | None] = mapped_column(JSON, nullable=True)  # type: ignore[assignment]
    updated_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    def __repr__(self) -> str:
        return f"<ProcurementProjectSettings {self.project_id} {self.order_owner}>"


class RequisitionExternalOrderLine(Base):
    """An order line placed in an external purchasing system against a requisition line.

    No purchase order and no commitment is created for it: the external system
    owns the order, OCERP keeps what it reported so requested, ordered and
    received quantities reconcile. One row per (requisition line, system,
    order number, line reference); a repeated report updates the row.
    """

    __tablename__ = "oe_procurement_req_ext_line"
    __table_args__ = (
        UniqueConstraint(
            "requisition_item_id",
            "external_system",
            "external_order_number",
            "external_line_ref",
            name="uq_procurement_req_ext_line_key",
        ),
    )

    requisition_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_procurement_requisition.id", ondelete="CASCADE", name="fk_oe_procurement_req_ext_line_req"),
        nullable=False,
        index=True,
    )
    requisition_item_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_procurement_req_item.id", ondelete="CASCADE", name="fk_oe_procurement_req_ext_line_item"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    external_system: Mapped[str] = mapped_column(String(100), nullable=False)
    external_order_number: Mapped[str] = mapped_column(String(100), nullable=False)
    external_line_ref: Mapped[str] = mapped_column(String(100), nullable=False, default="", server_default="")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="open", server_default="open")
    quantity_ordered: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    quantity_received: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    expected_delivery_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    confirmed_delivery_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    def __repr__(self) -> str:
        return f"<RequisitionExternalOrderLine {self.external_system}:{self.external_order_number}>"


class RequisitionChange(Base):
    """One entry of the requisition change feed (issue #516).

    Written in the same transaction as the change it describes, so a committed
    submission, edit or cancellation always has its entry and an integration
    that missed a detached event can replay the feed from its last cursor.
    Rows are never updated or deleted by the application.
    """

    __tablename__ = "oe_procurement_req_change"
    __table_args__ = (Index("ix_procurement_req_change_cursor", "project_id", "created_at", "id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    requisition_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    req_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    event: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")  # type: ignore[assignment]

    def __repr__(self) -> str:
        return f"<RequisitionChange {self.requisition_id} {self.event} v{self.row_version}>"
