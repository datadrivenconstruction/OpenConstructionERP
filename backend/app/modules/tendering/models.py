"""Tendering ORM models.

Tables:
    oe_tendering_package — tender/bid packages linked to a project and BOQ
    oe_tendering_bid — individual bids submitted against a package
"""

import uuid

from sqlalchemy import JSON, ForeignKey, String, Text
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
    deadline: Mapped[str | None] = mapped_column(String(20), nullable=True)
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
    submitted_at: Mapped[str | None] = mapped_column(String(20), nullable=True)
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
