# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠RFQ Bidding ORM models.

An RFQ goes out to several suppliers and the quotes come back on different
terms. Ranking them means putting them on one basis first, so the register
stores the things that basis is made of rather than a single headline number:

Tables:
    oe_rfq_rfq            - Request for Quotation definitions
    oe_rfq_line           - the priced scope, one row per item quoted against
    oe_rfq_bid            - a quote header: headline amount, currency, standing
    oe_rfq_bid_line       - one supplier's price for one scope line
    oe_rfq_bid_adjustment - an inclusion or exclusion that moves the comparable
                            total (freight, taxes, installation, a discount)
    oe_rfq_award          - the decision record: who won, on what basis, and
                            whether the winner was the top-ranked quote

Money discipline
----------------
``RFQBid.bid_amount`` is a Decimal *string* column and stays one: it predates
this register and rows carry values written that way. Everything added here
uses :class:`~app.core.db_types.MoneyType` (``NUMERIC(18, 2)``) for money and
``Numeric`` for quantities, rates and factors. No amount is ever a float, and
nothing in this module converts a currency without a rate that was recorded on
the quote it applies to.
"""

import uuid
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db_types import MoneyType
from app.database import GUID, Base
from app.modules.rfq_bidding.constants import (
    ADJUSTMENT_KINDS,
    ADJUSTMENT_SOURCES,
    BID_STATUSES,
    EVALUATION_METHODS,
)

__all__ = [
    "ADJUSTMENT_KINDS",
    "ADJUSTMENT_SOURCES",
    "BID_STATUSES",
    "EVALUATION_METHODS",
    "RFQ",
    "RFQAward",
    "RFQBid",
    "RFQBidAdjustment",
    "RFQBidLine",
    "RFQLine",
]


class RFQ(Base):
    """A Request for Quotation issued to vendors/subcontractors."""

    __tablename__ = "oe_rfq_rfq"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        nullable=False,
        index=True,
    )
    rfq_number: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    scope_of_work: Mapped[str | None] = mapped_column(Text, nullable=True)
    submission_deadline: Mapped[str | None] = mapped_column(String(20), nullable=True)
    currency_code: Mapped[str] = mapped_column(String(10), nullable=False, default="EUR")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft", index=True)
    issued_to_contacts: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # ── Cost Spine linkage (v6.4) ────────────────────────────────────────
    # Additive list of cost-line UUIDs (as strings) this RFQ sources. An RFQ
    # bundles several scope items so the link is many-valued, unlike the
    # single-FK columns on PO/contract lines.
    cost_line_ids: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    # ── Award basis ──────────────────────────────────────────────────────
    # How the returned quotes are ranked, and whether a quote that prices only
    # part of the scope may be ranked at all. Both decide the outcome, so they
    # belong to the RFQ that was issued rather than to the moment of awarding.
    evaluation_method: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="lowest_price",
        server_default="lowest_price",
    )
    technical_weight: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    require_full_scope: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )

    # Relationships
    bids: Mapped[list["RFQBid"]] = relationship(
        back_populates="rfq",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    lines: Mapped[list["RFQLine"]] = relationship(
        back_populates="rfq",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="RFQLine.line_no",
    )

    def __repr__(self) -> str:
        return f"<RFQ {self.rfq_number} ({self.status})>"


class RFQLine(Base):
    """One item of the scope suppliers are asked to price.

    The line is the common basis of the comparison. Without it a quote covering
    half the scope reads as the cheapest offer, which is the failure this
    register exists to prevent.
    """

    __tablename__ = "oe_rfq_line"
    __table_args__ = (UniqueConstraint("rfq_id", "line_no", name="uq_oe_rfq_line_rfq_no"),)

    rfq_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_rfq_rfq.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    # An optional line is priced separately and never counted against a
    # supplier's scope coverage, so an alternate cannot make a full quote look
    # partial.
    is_optional: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    #: Cost Spine linkage for this single item; the RFQ-level ``cost_line_ids``
    #: stays the bundle view.
    cost_line_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    rfq: Mapped["RFQ"] = relationship(back_populates="lines", lazy="raise_on_sql")
    bid_lines: Mapped[list["RFQBidLine"]] = relationship(
        back_populates="rfq_line",
        cascade="all, delete-orphan",
        lazy="raise_on_sql",
    )

    def __repr__(self) -> str:
        return f"<RFQLine {self.line_no} {self.unit}>"


class RFQBid(Base):
    """A bid submitted by a vendor against an RFQ."""

    __tablename__ = "oe_rfq_bid"

    rfq_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_rfq_rfq.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    bidder_contact_id: Mapped[str] = mapped_column(String(36), nullable=False)
    bid_amount: Mapped[str] = mapped_column(String(50), nullable=False)
    currency_code: Mapped[str] = mapped_column(String(10), nullable=False, default="EUR")
    submitted_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    validity_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    technical_score: Mapped[str | None] = mapped_column(String(10), nullable=True)
    commercial_score: Mapped[str | None] = mapped_column(String(10), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_awarded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    # ── Standing ─────────────────────────────────────────────────────────
    # Whether this quote may be ranked, which is not the same question as
    # whether it won. A quote that arrived after the deadline is recorded
    # rather than lost: the buyer either admits it, in writing and on the
    # record, or it stays visible in the table and out of the ranking.
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="received",
        server_default="received",
        index=True,
    )
    is_late: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    admitted_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    admitted_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    admission_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    late_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    disqualified_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    withdrawn_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    withdrawn_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # ── Conversion basis ─────────────────────────────────────────────────
    # Units of the RFQ currency per one unit of this quote's currency, frozen
    # at the rate the buyer actually compared on. The FX register publishes
    # rate sets; a quote records the one it was converted at, so the ranking
    # stays reproducible after the market moves.
    exchange_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    exchange_rate_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    exchange_rate_source: Mapped[str | None] = mapped_column(String(60), nullable=True)

    # Relationships
    rfq: Mapped["RFQ"] = relationship(back_populates="bids", lazy="raise_on_sql")
    lines: Mapped[list["RFQBidLine"]] = relationship(
        back_populates="bid",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    adjustments: Mapped[list["RFQBidAdjustment"]] = relationship(
        back_populates="bid",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<RFQBid {self.bidder_contact_id} amount={self.bid_amount}>"


class RFQBidLine(Base):
    """One supplier's price for one line of the RFQ scope.

    ``rfq_line_id`` is nullable on purpose: a supplier may price something the
    buyer did not ask for, and an extra that is silently dropped is how a
    headline total stops agreeing with the detail behind it.
    """

    __tablename__ = "oe_rfq_bid_line"

    bid_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_rfq_bid.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rfq_line_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_rfq_line.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit: Mapped[str] = mapped_column(String(20), nullable=False, default="", server_default="")
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    unit_rate: Mapped[Decimal] = mapped_column(
        MoneyType(),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    amount: Mapped[Decimal] = mapped_column(
        MoneyType(),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    #: How many RFQ units make one of this supplier's units. Required when the
    #: units differ; without it the two rates are not the same measurement and
    #: the line is reported rather than converted on a guess.
    unit_conversion_factor: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    #: The supplier stated they do not price this line. An excluded line and a
    #: missing line are both gaps in coverage; the difference is that one of
    #: them was answered.
    is_excluded: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    bid: Mapped["RFQBid"] = relationship(back_populates="lines", lazy="raise_on_sql")
    rfq_line: Mapped["RFQLine | None"] = relationship(back_populates="bid_lines", lazy="raise_on_sql")

    def __repr__(self) -> str:
        return f"<RFQBidLine bid={self.bid_id} amount={self.amount}>"


class RFQBidAdjustment(Base):
    """An inclusion or exclusion that moves a quote's comparable total.

    Suppliers quote on their own terms: one price includes delivery to site,
    the next leaves it out and says so in a covering note. Ranking the two
    headline numbers compares different things. Each adjustment records what
    the item is, what it costs and whether the quote's own amount already
    carries it, so the comparison can add back exactly what is missing.
    """

    __tablename__ = "oe_rfq_bid_adjustment"

    bid_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_rfq_bid.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Signed: a discount is negative. Stored in ``currency_code``, which is
    #: either the quote's currency or the RFQ's; anything else cannot be
    #: converted and is reported.
    amount: Mapped[Decimal] = mapped_column(
        MoneyType(),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    currency_code: Mapped[str] = mapped_column(String(10), nullable=False, default="EUR", server_default="EUR")
    #: ``True`` when the quote's headline amount already carries this item, so
    #: the comparison leaves it alone and only records what was covered.
    included_in_bid: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="bidder", server_default="bidder")

    bid: Mapped["RFQBid"] = relationship(back_populates="adjustments", lazy="raise_on_sql")

    def __repr__(self) -> str:
        return f"<RFQBidAdjustment {self.kind} {self.amount}>"


class RFQAward(Base):
    """Why one quote won, recorded at the moment it did.

    One row per RFQ. ``basis`` holds the ranked table as it stood when the
    decision was taken: every quote, its headline amount and currency, the rate
    it was converted at, the adjustments applied, its scope coverage and
    whether it was comparable at all. Recomputing that table later gives a
    different answer as soon as a quote is edited, so the answer is kept rather
    than re-derived.
    """

    __tablename__ = "oe_rfq_award"
    __table_args__ = (UniqueConstraint("rfq_id", name="uq_oe_rfq_award_rfq"),)

    rfq_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_rfq_rfq.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    bid_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_rfq_bid.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    awarded_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    awarded_at: Mapped[str] = mapped_column(String(40), nullable=False)
    method: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="lowest_price",
        server_default="lowest_price",
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The quote the comparison ranked first, which is not always the one the
    #: buyer chose. Keeping both is what makes an override visible.
    recommended_bid_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    is_override: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    awarded_amount: Mapped[Decimal] = mapped_column(
        MoneyType(),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    awarded_currency: Mapped[str] = mapped_column(String(10), nullable=False, default="EUR", server_default="EUR")
    basis: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")  # type: ignore[assignment]

    def __repr__(self) -> str:
        return f"<RFQAward rfq={self.rfq_id} bid={self.bid_id}>"
