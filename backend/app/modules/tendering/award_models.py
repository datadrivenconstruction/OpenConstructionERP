# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Award terms and negotiation rounds of a tender package.

Tables:
    oe_tendering_award_terms - the structured terms the award is made on, one row per package
    oe_tendering_negotiation_round - one negotiated offer of one bidder, numbered per bid

The terms are what the contract draft takes: the offer they rest on (a round,
or the bid as submitted), discount, agreed lump sum, retention and its cap, and
the payment discount with its days. Percentages are stored as percent (3 = 3 %).
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class TenderNegotiationRound(Base):
    """One negotiated offer of a bidder: a revised lump sum or the priced lines with a discount."""

    __tablename__ = "oe_tendering_negotiation_round"
    __table_args__ = (UniqueConstraint("bid_id", "round_no", name="uq_oe_tendering_negotiation_round_bid_no"),)

    package_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_tendering_package.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    bid_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_tendering_bid.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    round_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # unit_price: the bid lines as priced; lump_sum: one figure for the whole package.
    pricing_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="unit_price")
    # The bid lines' sum when the round was recorded, kept so a later line edit shows.
    lines_total: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    lump_sum: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    discount_percent: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False, default=Decimal("0"))
    note: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    is_final: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    approved_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The commitment guard's answer at approval, as it was given.
    approval_verdict: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    def __repr__(self) -> str:
        return f"<TenderNegotiationRound bid={self.bid_id} #{self.round_no} final={self.is_final}>"


class TenderAwardTerms(Base):
    """The terms a package is awarded on. One row per package, frozen once the package is awarded."""

    __tablename__ = "oe_tendering_award_terms"

    package_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_tendering_package.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    bid_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_tendering_bid.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    round_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_tendering_negotiation_round.id", ondelete="SET NULL"),
        nullable=True,
    )
    discount_percent: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False, default=Decimal("0"))
    lump_sum: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    retention_percent: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), nullable=True)
    retention_cap_percent: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), nullable=True)
    payment_discount_percent: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), nullable=True)
    payment_discount_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    updated_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    def __repr__(self) -> str:
        return f"<TenderAwardTerms package={self.package_id} bid={self.bid_id}>"
