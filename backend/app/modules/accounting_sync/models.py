# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Accounting​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ sync ORM models.

Tables:
    oe_acctsync_connection   - one company ledger in an external accounting system
                               (Xero, QuickBooks Online) or a file target (DATEV EXTF,
                               generic journal, SAF-T). OAuth secrets are Fernet encrypted.
    oe_acctsync_account_map  - posting category -> account code, per connection.
    oe_acctsync_tax_map      - platform tax code + direction -> external tax key.
    oe_acctsync_external_ref - the external id of every pushed record, so a push is
                               idempotent and an update goes to the same remote row.
    oe_acctsync_log          - one row per record attempt, with retry count and reason.

Master data: the platform owns projects, cost codes, contracts and documents; the
accounting system owns the posted ledger and payment status, which flows back.
Record ids are soft links (no foreign key) into finance, contacts and guarantees.
"""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import JSON, Boolean, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
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
    # Xero tenant id or QuickBooks realm id.
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
    # QuickBooks SyncToken for sparse updates.
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
