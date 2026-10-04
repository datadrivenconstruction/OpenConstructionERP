# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Tendering ORM models.

Tables:
    oe_tendering_package - tender/bid packages linked to a project and BOQ
    oe_tendering_bid - individual bids submitted against a package
    oe_tendering_bid_invitation - per-recipient price-entry links (token hashed)
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base


class TenderPackage(Base):
    """A tender package groups BOQ positions for subcontractor bidding."""

    __tablename__ = "oe_tendering_package"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        nullable=False,
        index=True,
    )
    boq_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft", index=True)
    deadline: Mapped[str | None] = mapped_column(String(100), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # Relationships
    bids: Mapped[list["TenderBid"]] = relationship(
        back_populates="package",
        cascade="all, delete-orphan",
        lazy="raise",
    )

    def __repr__(self) -> str:
        return f"<TenderPackage {self.name} ({self.status})>"


class TenderBid(Base):
    """A bid submitted by a company for a tender package."""

    __tablename__ = "oe_tendering_bid"

    package_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_tendering_package.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_email: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    total_amount: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="EUR")
    submitted_at: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    line_items: Mapped[list] = mapped_column(  # type: ignore[assignment]
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

    # Relationships
    package: Mapped["TenderPackage"] = relationship(back_populates="bids")

    def __repr__(self) -> str:
        return f"<TenderBid {self.company_name} ({self.status})>"


class TenderBidInvitation(Base):
    """A personal web link that lets one invited firm price one tender package.

    The bidder has no account: the link itself is the credential. Only the
    sha256 of the token is stored, the token is shown once when the link is
    made. One row is one link; making a new link for the same recipient
    revokes the older row and carries its draft and bid over, so the firm keeps
    what it typed.

    ``draft`` holds the firm's own unit prices (``{"unit_prices": {...},
    "notes": ...}``) until it submits; submitting writes a ``TenderBid`` through
    the regular bid path and records its id in ``bid_id``. No ORM relationship
    is declared, every reader goes by id.
    """

    __tablename__ = "oe_tendering_bid_invitation"

    package_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_tendering_package.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The id of the entry in the package's ``metadata.recipients`` list.
    recipient_id: Mapped[str] = mapped_column(String(64), nullable=False, default="", index=True)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    email: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    draft_saved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    bid_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_tendering_bid.id", ondelete="SET NULL"),
        nullable=True,
    )
    draft: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    def __repr__(self) -> str:
        return f"<TenderBidInvitation {self.company_name} package={self.package_id}>"
