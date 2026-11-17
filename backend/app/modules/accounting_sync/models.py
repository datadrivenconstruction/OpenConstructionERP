# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Accounting​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ sync ORM models.

Tables:
    oe_acctsync_connection   - one company ledger in an external accounting system
                               (Xero, QBO) or a file target (DATEV EXTF,
                               generic journal, SAF-T). OAuth secrets are Fernet encrypted.
    oe_acctsync_account_map  - posting category -> account code, per connection.
    oe_acctsync_tax_map      - platform tax code + direction -> external tax key.
    oe_acctsync_external_ref - the external id of every pushed record, so a push is
                               idempotent and an update goes to the same remote row.
    oe_acctsync_log          - one row per record attempt, with retry count and reason.
    oe_acctsync_costcode_map - platform cost code (per standard) -> external cost centre.
    oe_acctsync_supplier_map - platform contact -> external creditor account.
    oe_acctsync_export_batch - one numbered, hashed export file per connection.
    oe_acctsync_batch_item   - the records in a batch; a record sits in one active batch only.
    oe_acctsync_import       - ledger lines read from a books file, for reconciliation.

Master data: the platform owns projects, cost codes, contracts and documents; the
accounting system owns the posted ledger and payment status, which flows back.
Record ids are soft links (no foreign key) into finance, contacts and guarantees.
"""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db_types import SafeDate
from app.database import GUID, Base


class AccountingConnection(Base):
    """A company ledger the platform pushes to or exports for."""

    __tablename__ = "oe_acctsync_connection"
    __table_args__ = (UniqueConstraint("name", name="uq_acctsync_connection_name"),)

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    chart_template: Mapped[str] = mapped_column(String(40), nullable=False, default="generic", server_default="generic")
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR", server_default="EUR")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", server_default="draft")
    is_sandbox: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    client_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Fernet tokens (app.core.crypto); never returned to the client.
    client_secret_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    tokens_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Xero tenant id or QBO realm id.
    external_tenant_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Books closed through this day: nothing may post on or before it.
    lock_date: Mapped[date | None] = mapped_column(SafeDate(), nullable=True)
    # Empty list = every project.
    project_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list, server_default="[]")  # type: ignore[assignment]
    settings_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "settings", JSON, nullable=False, default=dict, server_default="{}"
    )
    last_sync_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last_sync_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)


class AccountMapping(Base):
    """Posting category -> account code for one connection."""

    __tablename__ = "oe_acctsync_account_map"
    __table_args__ = (UniqueConstraint("connection_id", "category", name="uq_acctsync_account_map"),)

    connection_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_acctsync_connection.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String(60), nullable=False)
    account_code: Mapped[str] = mapped_column(String(40), nullable=False, default="", server_default="")
    account_name: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")


class TaxCodeMapping(Base):
    """Platform tax code (from the dated tax seed) -> external tax key."""

    __tablename__ = "oe_acctsync_tax_map"
    __table_args__ = (UniqueConstraint("connection_id", "tax_code", "direction", name="uq_acctsync_tax_map"),)

    connection_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_acctsync_connection.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tax_code: Mapped[str] = mapped_column(String(40), nullable=False)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)  # sales | purchase
    external_code: Mapped[str] = mapped_column(String(40), nullable=False, default="", server_default="")
    rate_pct: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), nullable=True)


class ExternalRef(Base):
    """Remote id of one pushed record; the idempotency anchor of every push."""

    __tablename__ = "oe_acctsync_external_ref"
    __table_args__ = (UniqueConstraint("connection_id", "record_type", "record_id", name="uq_acctsync_external_ref"),)

    connection_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_acctsync_connection.id", ondelete="CASCADE"), nullable=False, index=True
    )
    record_type: Mapped[str] = mapped_column(String(30), nullable=False)
    record_id: Mapped[str] = mapped_column(String(80), nullable=False)
    external_id: Mapped[str] = mapped_column(String(120), nullable=False)
    # QBO SyncToken for sparse updates.
    external_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    pushed_total: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    remote_total: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    last_pushed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)


class SyncLogEntry(Base):
    """One attempt to push, pull or export one record."""

    __tablename__ = "oe_acctsync_log"
    __table_args__ = (
        Index("ix_acctsync_log_conn_status", "connection_id", "status"),
        Index("ix_acctsync_log_record", "connection_id", "record_type", "record_id"),
    )

    connection_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_acctsync_connection.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(20), nullable=False)  # push | pull | export
    record_type: Mapped[str] = mapped_column(String(30), nullable=False)
    record_id: Mapped[str] = mapped_column(String(80), nullable=False, default="", server_default="")
    record_label: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # success | failed | skipped
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    error_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    details_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "details", JSON, nullable=False, default=dict, server_default="{}"
    )


class CostCodeMapping(Base):
    """Platform cost code (in one standard) -> external cost centre."""

    __tablename__ = "oe_acctsync_costcode_map"
    __table_args__ = (UniqueConstraint("connection_id", "platform_code", "standard", name="uq_acctsync_costcode_map"),)

    connection_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_acctsync_connection.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform_code: Mapped[str] = mapped_column(String(60), nullable=False)
    standard: Mapped[str] = mapped_column(String(40), nullable=False, default="project", server_default="project")
    external_cost_center: Mapped[str] = mapped_column(String(40), nullable=False, default="", server_default="")


class SupplierMapping(Base):
    """Platform contact -> creditor (or debtor) account in the books."""

    __tablename__ = "oe_acctsync_supplier_map"
    __table_args__ = (UniqueConstraint("connection_id", "contact_id", name="uq_acctsync_supplier_map"),)

    connection_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_acctsync_connection.id", ondelete="CASCADE"), nullable=False, index=True
    )
    contact_id: Mapped[str] = mapped_column(String(80), nullable=False)
    external_account: Mapped[str] = mapped_column(String(40), nullable=False, default="", server_default="")


class ExportBatch(Base):
    """One numbered export file; the file bytes are kept so its hash never drifts."""

    __tablename__ = "oe_acctsync_export_batch"
    __table_args__ = (
        UniqueConstraint("connection_id", "batch_no", name="uq_acctsync_batch_no"),
        UniqueConstraint("connection_id", "idempotency_key", name="uq_acctsync_batch_idem"),
    )

    connection_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_acctsync_connection.id", ondelete="CASCADE"), nullable=False, index=True
    )
    batch_no: Mapped[int] = mapped_column(Integer, nullable=False)
    format: Mapped[str] = mapped_column(String(20), nullable=False)  # csv | xlsx | datev | journal
    period_from: Mapped[date] = mapped_column(SafeDate(), nullable=False)
    period_to: Mapped[date] = mapped_column(SafeDate(), nullable=False)
    record_types: Mapped[list] = mapped_column(JSON, nullable=False, default=list, server_default="[]")  # type: ignore[assignment]
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    total_net: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"), server_default="0")
    total_tax: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"), server_default="0")
    total_gross: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal("0"), server_default="0"
    )
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="draft", server_default="draft")
    idempotency_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    file_name: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default="")
    media_type: Mapped[str] = mapped_column(String(80), nullable=False, default="", server_default="")
    content: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    void_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    voided_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)


class BatchItem(Base):
    """A record inside a batch. ``active`` is cleared when the batch is voided."""

    __tablename__ = "oe_acctsync_batch_item"
    __table_args__ = (
        Index(
            "uq_acctsync_batch_item_active",
            "connection_id",
            "record_type",
            "record_id",
            unique=True,
            postgresql_where=text("active"),
        ),
    )

    batch_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_acctsync_export_batch.id", ondelete="CASCADE"), nullable=False, index=True
    )
    connection_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_acctsync_connection.id", ondelete="CASCADE"), nullable=False
    )
    record_type: Mapped[str] = mapped_column(String(30), nullable=False)
    record_id: Mapped[str] = mapped_column(String(80), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class LedgerImportLine(Base):
    """One ledger line read from a books file (payment status and reconciliation)."""

    __tablename__ = "oe_acctsync_import"
    __table_args__ = (Index("ix_acctsync_import_conn_doc", "connection_id", "document_number"),)

    connection_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_acctsync_connection.id", ondelete="CASCADE"), nullable=False, index=True
    )
    import_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    file_name: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default="")
    line_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    posting_date: Mapped[date | None] = mapped_column(SafeDate(), nullable=True)
    document_number: Mapped[str] = mapped_column(String(80), nullable=False, default="", server_default="")
    account: Mapped[str] = mapped_column(String(40), nullable=False, default="", server_default="")
    debit: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"), server_default="0")
    credit: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"), server_default="0")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="", server_default="")
    payment_status: Mapped[str] = mapped_column(String(20), nullable=False, default="", server_default="")
    description: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
