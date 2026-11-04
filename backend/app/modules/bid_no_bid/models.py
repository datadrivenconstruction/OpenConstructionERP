# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Bid / no-bid ORM models.

Tables:
    oe_bid_no_bid_scorecard - one scorecard per tender: weights, ratings, threshold and decision.
    The bid outcome is not stored here: it lives in ``oe_win_loss_entry`` (linked by ``tender_id``).
    oe_bid_no_bid_event     - the audit trail: every change with who and when.

``tender_id`` and ``opportunity_id`` are soft links (no foreign key) like the other registers.
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class BidNoBidScorecard(Base):
    """The go / no-go scorecard of one tender."""

    __tablename__ = "oe_bid_no_bid_scorecard"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tender_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, unique=True)
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    weights: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    scores: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    notes: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=60, server_default="60")
    decision: Mapped[str] = mapped_column(String(10), nullable=False, default="", server_default="")
    decision_reason: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    decided_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)


class BidNoBidEvent(Base):
    """One line of the audit trail."""

    __tablename__ = "oe_bid_no_bid_event"
    __table_args__ = (Index("ix_bid_no_bid_event_card_created", "scorecard_id", "created_at"),)

    scorecard_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_bid_no_bid_scorecard.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    user_name: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
