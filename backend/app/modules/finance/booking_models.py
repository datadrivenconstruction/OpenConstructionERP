# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""ORM models of booking export batches: one immutable file per batch and its invoice stamps."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import JSON, Boolean, Date, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class BookingExportBatch(Base):
    """A booking file handed to the bookkeeper; never edited after creation."""

    __tablename__ = "oe_finance_booking_batch"
    __table_args__ = (UniqueConstraint("number", name="uq_oe_finance_booking_batch_number"),)

    number: Mapped[int] = mapped_column(Integer, nullable=False)
    connector_config_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    connector_type: Mapped[str] = mapped_column(String(50), nullable=False)
    period_from: Mapped[date] = mapped_column(Date, nullable=False)
    period_to: Mapped[date] = mapped_column(Date, nullable=False)
    reexport: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    invoice_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    filename: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    encoding: Mapped[str] = mapped_column(String(20), nullable=False, default="utf-8", server_default="utf-8")
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    findings: Mapped[list] = mapped_column(JSON, nullable=False, default=list)  # type: ignore[assignment]
    sync_log_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class BookingExportItem(Base):
    """Stamp: this captured invoice went out in this batch."""

    __tablename__ = "oe_finance_booking_batch_item"

    batch_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_finance_booking_batch.id", ondelete="CASCADE"), nullable=False, index=True
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    invoice_number: Mapped[str] = mapped_column(String(100), nullable=False, default="")
