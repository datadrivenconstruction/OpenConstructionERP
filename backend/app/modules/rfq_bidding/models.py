"""RFQ Bidding ORM models.

Tables:
    oe_rfq_rfq  — Request for Quotation definitions
    oe_rfq_bid  — Bids submitted against an RFQ
"""

import uuid

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base


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
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft")
    issued_to_contacts: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # Relationships
    bids: Mapped[list["RFQBid"]] = relationship(
        back_populates="rfq",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<RFQ {self.rfq_number} ({self.status})>"


class RFQBid(Base):
    """A bid submitted by a vendor against an RFQ."""

    __tablename__ = "oe_rfq_bid"

    rfq_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_rfq_rfq.id", ondelete="CASCADE"),
        nullable=False,
    )
    bidder_contact_id: Mapped[str] = mapped_column(String(36), nullable=False)
    bid_amount: Mapped[str] = mapped_column(String(50), nullable=False)
    currency_code: Mapped[str] = mapped_column(String(10), nullable=False, default="EUR")
    submitted_at: Mapped[str | None] = mapped_column(String(20), nullable=True)
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

    # Relationships
    rfq: Mapped["RFQ"] = relationship(back_populates="bids")

    def __repr__(self) -> str:
        return f"<RFQBid {self.bidder_contact_id} amount={self.bid_amount}>"
