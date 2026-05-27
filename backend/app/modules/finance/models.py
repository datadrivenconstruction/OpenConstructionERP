"""‌⁠‍Finance ORM models.

Tables:
    oe_finance_invoice       — payable/receivable invoices
    oe_finance_invoice_item  — invoice line items
    oe_finance_payment       — payments against invoices
    oe_finance_budget        — project budgets by WBS/category
    oe_finance_evm_snapshot  — Earned Value Management snapshots
"""

import uuid
from decimal import Decimal

from sqlalchemy import JSON, Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db_types import MoneyType
from app.database import GUID, Base


class Invoice(Base):
    """‌⁠‍A payable or receivable invoice linked to a project."""

    __tablename__ = "oe_finance_invoice"
    __table_args__ = (
        Index("ix_invoice_project_direction", "project_id", "invoice_direction"),
        Index("ix_invoice_project_status", "project_id", "status"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        nullable=False,
        index=True,
    )
    contact_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    invoice_direction: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    invoice_number: Mapped[str] = mapped_column(String(50), nullable=False)
    invoice_date: Mapped[str] = mapped_column(String(20), nullable=False)
    due_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    currency_code: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    # Phase 2e: money columns back to NUMERIC on PG while staying VARCHAR
    # on SQLite for dev-DB compatibility. Python always sees ``Decimal``.
    amount_subtotal: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False, default=Decimal("0"))
    tax_amount: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False, default=Decimal("0"))
    retention_amount: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False, default=Decimal("0"))
    amount_total: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False, default=Decimal("0"))
    tax_config_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft", index=True)
    payment_terms_days: Mapped[str | None] = mapped_column(String(10), nullable=True)
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
    line_items: Mapped[list["InvoiceLineItem"]] = relationship(
        back_populates="invoice",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    payments: Mapped[list["Payment"]] = relationship(
        back_populates="invoice",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Invoice {self.invoice_number} ({self.status})>"


class InvoiceLineItem(Base):
    """‌⁠‍A single line item within an invoice."""

    __tablename__ = "oe_finance_invoice_item"

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_finance_invoice.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    # Quantity / rate / amount: wider scale so quantities like 1.234567
    # don't round-trip as "1.23". The PG type becomes NUMERIC(18, 6).
    quantity: Mapped[Decimal] = mapped_column(MoneyType(scale=6), nullable=False, default=Decimal("1"))
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    unit_rate: Mapped[Decimal] = mapped_column(MoneyType(scale=6), nullable=False, default=Decimal("0"))
    amount: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False, default=Decimal("0"))
    wbs_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    cost_category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Relationship
    invoice: Mapped["Invoice"] = relationship(back_populates="line_items")

    def __repr__(self) -> str:
        return f"<InvoiceLineItem {self.description[:40]}>"


class Payment(Base):
    """A payment recorded against an invoice."""

    __tablename__ = "oe_finance_payment"
    __table_args__ = (Index("ix_finance_payment_idempotency", "idempotency_key", unique=True),)

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_finance_invoice.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    payment_date: Mapped[str] = mapped_column(String(20), nullable=False)
    amount: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False)
    currency_code: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    exchange_rate_snapshot: Mapped[Decimal] = mapped_column(MoneyType(scale=6), nullable=False, default=Decimal("1"))
    reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # R7: idempotency key — caller supplies a unique token per payment
    # attempt; second POST with same key returns the existing row.
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # R7: is_refund flag — stored separately from amount sign so the positive
    # amount validator on PaymentCreate can remain in place.
    is_refund: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=False, server_default="0")
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # Relationship
    invoice: Mapped["Invoice"] = relationship(back_populates="payments")

    def __repr__(self) -> str:
        return f"<Payment {self.amount} on {self.payment_date}>"


class ProjectBudget(Base):
    """Budget line for a project, optionally scoped by WBS and cost category."""

    __tablename__ = "oe_finance_budget"
    __table_args__ = (UniqueConstraint("project_id", "wbs_id", "category", name="uq_finance_budget_proj_wbs_cat"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        nullable=False,
        index=True,
    )
    wbs_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    currency_code: Mapped[str] = mapped_column(
        # v3 universality #217 — no DB default; service code MUST supply
        # currency from the project context so per-project rollups don't
        # silently bias toward EUR. server_default preserved for backfill
        # safety on rows inserted via raw SQL paths during migration.
        String(3),
        nullable=False,
        default="",
        server_default="",
    )
    # Phase 2d pilot: money columns now return Decimal in Python.
    # On PostgreSQL this emits NUMERIC(18, 2); on the existing SQLite
    # dev DBs the physical column stays VARCHAR(50), so no destructive
    # migration is required — MoneyType normalises both ends.
    original_budget: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False, default=Decimal("0"))
    revised_budget: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False, default=Decimal("0"))
    committed: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False, default=Decimal("0"))
    actual: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False, default=Decimal("0"))
    forecast_final: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False, default=Decimal("0"))
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<ProjectBudget project={self.project_id} cat={self.category}>"


class EVMSnapshot(Base):
    """Earned Value Management snapshot for a project at a point in time."""

    __tablename__ = "oe_finance_evm_snapshot"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        nullable=False,
        index=True,
    )
    snapshot_date: Mapped[str] = mapped_column(String(20), nullable=False)
    bac: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    pv: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    ev: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    ac: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    sv: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    cv: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    spi: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    cpi: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    # Forecast metrics (EVM standard):
    #   eac  = AC + (BAC - EV) / CPI  — estimate at completion
    #   vac  = BAC - EAC              — variance at completion
    #   etc  = EAC - AC               — estimate to complete
    #   tcpi = (BAC - EV) / (BAC - AC) — to-complete performance index
    eac: Mapped[str] = mapped_column(String(50), nullable=False, default="0", server_default="0")
    vac: Mapped[str] = mapped_column(String(50), nullable=False, default="0", server_default="0")
    etc: Mapped[str] = mapped_column(String(50), nullable=False, default="0", server_default="0")
    tcpi: Mapped[str] = mapped_column(String(50), nullable=False, default="0", server_default="0")
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<EVMSnapshot project={self.project_id} date={self.snapshot_date}>"


class LedgerEntry(Base):
    """Append-only double-entry ledger row.

    R7 invariants:
    * Rows are NEVER updated or deleted — corrections come as new rows with
      ``is_reversal=True`` referencing ``reversal_of_id``.
    * Every transaction consists of exactly two rows:
        - debit row:  debit_amount > 0, credit_amount == 0
        - credit row: credit_amount > 0, debit_amount == 0
    * Service enforces debit_amount == credit_amount before writing.
    """

    __tablename__ = "oe_finance_ledger"
    __table_args__ = (
        Index("ix_ledger_project_ref", "project_id", "transaction_ref"),
        Index("ix_ledger_posted_at", "posted_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    transaction_ref: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    account_code: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    debit_amount: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False, default=Decimal("0"))
    credit_amount: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False, default=Decimal("0"))
    currency_code: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    posted_at: Mapped[str] = mapped_column(String(30), nullable=False)
    source_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # Reversal link — non-null when this row reverses a prior entry
    is_reversal: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=False, server_default="0")
    reversal_of_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_finance_ledger.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    def __repr__(self) -> str:
        return f"<LedgerEntry ref={self.transaction_ref} dr={self.debit_amount} cr={self.credit_amount}>"
