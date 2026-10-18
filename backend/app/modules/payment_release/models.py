# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Payment release ORM models.

Tables:
    oe_payment_release_terms              - a contract's payment terms (one row per contract)
    oe_payment_release_invoice            - what a supplier invoice needs for its release, and the frozen release
    oe_payment_release_posting  - held retention released as cash on a date

Nothing here duplicates a record another module owns. The invoice, its lines,
its VAT and its payments stay in ``finance``; the contract, its interim
retention rate (``Contract.retention_percent``) and the event that releases it
(``Contract.retention_release_event``) stay in ``contracts``. These tables
carry only what neither has: the invoice mode, the optional terms, the
deductions a controller agrees on one invoice, and the release a person
confirmed.

Cross-module references to finance invoices are plain GUIDs without a foreign
key, the convention the platform uses wherever a record may outlive the row it
points at (an invoice deleted in finance leaves its release history readable).
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db_types import MoneyType
from app.database import GUID, Base


class PaymentTerms(Base):
    """How a contract is invoiced and paid. Optional features default to off."""

    __tablename__ = "oe_payment_release_terms"
    __table_args__ = (UniqueConstraint("contract_id", name="uq_payment_release_terms_contract"),)

    contract_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_contracts_contract.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # cumulative: each interim states the total to date; incremental: each bills only the new work.
    invoice_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, default="incremental", server_default="incremental"
    )
    # Whether retention is taken on the net (most markets) or on the gross including VAT.
    retention_basis: Mapped[str] = mapped_column(String(10), nullable=False, default="net", server_default="net")
    warranty_enabled: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=False, server_default="0")
    warranty_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("0"), server_default="0"
    )
    warranty_release_event: Mapped[str] = mapped_column(
        String(40), nullable=False, default="defects_period_end", server_default="defects_period_end"
    )
    warranty_period_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    discount_enabled: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=False, server_default="0")
    discount_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("0"), server_default="0"
    )
    discount_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    discount_applies_to: Mapped[str] = mapped_column(String(10), nullable=False, default="both", server_default="both")
    rounding_enabled: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=False, server_default="0")
    rounding_step: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal("0"), server_default="0"
    )
    interim_due_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    final_due_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )

    def __repr__(self) -> str:
        return f"<PaymentTerms {self.contract_id} {self.invoice_mode}>"


class InvoiceRelease(Base):
    """A supplier invoice's place in its contract's payment release, and the release once confirmed."""

    __tablename__ = "oe_payment_release_invoice"
    __table_args__ = (UniqueConstraint("invoice_id", name="uq_payment_release_invoice_invoice"),)

    # Plain GUID - the finance invoice (oe_finance_invoice).
    invoice_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Plain GUID - the contract this invoice bills, when a person named it here. Otherwise the
    # contract comes from the invoice's own links (its lines' schedule lines, its claim).
    contract_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    # interim, final, daywork or credit_note.
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="interim", server_default="interim")
    net_deduction: Mapped[Decimal] = mapped_column(
        MoneyType(), nullable=False, default=Decimal("0"), server_default="0"
    )
    net_deduction_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    gross_deduction: Mapped[Decimal] = mapped_column(
        MoneyType(), nullable=False, default=Decimal("0"), server_default="0"
    )
    gross_deduction_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # open while the figures follow the terms; released once a person confirmed them.
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open", server_default="open", index=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    released_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # The confirmed figures, kept as columns for the rules and as the full step list.
    release_amount: Mapped[Decimal | None] = mapped_column(MoneyType(), nullable=True)
    payable_amount: Mapped[Decimal | None] = mapped_column(MoneyType(), nullable=True)
    retention_amount: Mapped[Decimal | None] = mapped_column(MoneyType(), nullable=True)
    rounding_amount: Mapped[Decimal | None] = mapped_column(MoneyType(), nullable=True)
    discount_amount: Mapped[Decimal | None] = mapped_column(MoneyType(), nullable=True)
    snapshot: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )

    def __repr__(self) -> str:
        return f"<InvoiceRelease {self.invoice_id} {self.kind}/{self.status}>"


class RetentionPosting(Base):
    """Held retention paid back to the contractor: the money posting a release event triggers."""

    __tablename__ = "oe_payment_release_posting"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False, index=True
    )
    contract_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_contracts_contract.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # interim (held on the interims) or warranty (held on the final for the defects period).
    retention_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="interim")
    # The completion event the release follows, in the contracts vocabulary.
    event: Mapped[str] = mapped_column(String(40), nullable=False)
    event_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    amount: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False)
    posted_on: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="posted", server_default="posted")
    document_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    voided_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )

    def __repr__(self) -> str:
        return f"<RetentionPosting {self.contract_id} {self.amount} {self.status}>"
