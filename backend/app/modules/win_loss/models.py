# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Bid outcome ledger ORM models.

Tables:
    oe_win_loss_entry - one row per bid we submitted and how it ended; the single outcome record of a tender
    (``tender_id`` is unique, the bid / no-bid scorecard reads and writes it)

``project_id`` and ``tender_id`` are plain UUIDs (no cross-module foreign key): a bid
we lost never became a project, and the tendering module stays swappable.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import JSON, Date, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class BidOutcome(Base):
    """One submitted bid and how it ended."""

    __tablename__ = "oe_win_loss_entry"
    __table_args__ = (Index("ux_win_loss_tender", "tender_id", unique=True),)

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    client_name: Mapped[str] = mapped_column(String(255), nullable=False, default="", index=True)
    trade: Mapped[str] = mapped_column(String(100), nullable=False, default="", index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    tender_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    submitted_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    our_price: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    winning_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    second_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    competitor_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lost_reason: Mapped[str | None] = mapped_column(String(30), nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
