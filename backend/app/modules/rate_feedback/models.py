# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Rate-feedback proposals: what closed projects say a cost item should cost."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base

STATUS_PENDING = "pending"
STATUS_ACCEPTED = "accepted"
STATUS_REJECTED = "rejected"
STATUS_SUPERSEDED = "superseded"


class RateFeedbackProposal(Base):
    """One suggested update to one cost item, awaiting an estimator's decision."""

    __tablename__ = "oe_rate_feedback_proposal"
    __table_args__ = (Index("ix_oe_rate_feedback_proposal_item_status", "cost_item_id", "status"),)

    cost_item_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("oe_costs_item.id", ondelete="CASCADE"))
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    current_rate: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    suggested_rate: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    variance_pct: Mapped[Decimal | None] = mapped_column(Numeric(9, 2), nullable=True)
    current_hours_per_unit: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    observed_hours_per_unit: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    hours_variance_pct: Mapped[Decimal | None] = mapped_column(Numeric(9, 2), nullable=True)
    project_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    line_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    spread_pct: Mapped[Decimal | None] = mapped_column(Numeric(9, 2), nullable=True)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=Decimal("0"))
    project_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)  # type: ignore[assignment]
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=STATUS_PENDING, index=True)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    applied_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
