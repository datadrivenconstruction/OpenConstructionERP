# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Subcontract levies, payment discount and bidder search ORM models.

Tables:
    oe_subcontractors_levy_catalogue   - the company's levy list (name, basis, default rate)
    oe_subcontractors_subcontract_terms - deduction terms of one subcontract (agreement and/or contract)
    oe_subcontractors_subcontract_levy  - one levy agreed on a subcontract
    oe_subcontractors_firm_location     - coordinates of a firm's address, for the radius search
    oe_subcontractors_favourite         - a firm marked as favourite for a trade

Levy rates are company configuration: core ships no rate, a country pack may
ship catalogue names, and the company enters the percentages it agrees.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db_types import MoneyType
from app.database import GUID, Base


class LevyCatalogueItem(Base):
    """One levy the company charges its subcontractors, with its default rate."""

    __tablename__ = "oe_subcontractors_levy_catalogue"
    __table_args__ = (UniqueConstraint("code", name="uq_oe_subcontractors_levy_catalogue_code"),)

    code: Mapped[str] = mapped_column(String(60), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # ``percent`` of the invoiced work value, or a ``fixed`` amount per invoice.
    basis: Mapped[str] = mapped_column(String(20), nullable=False, default="percent", server_default="percent")
    default_percent: Mapped[Decimal | None] = mapped_column(Numeric(7, 3), nullable=True)
    default_fixed_amount: Mapped[Decimal | None] = mapped_column(MoneyType(), nullable=True)
    # ``each_invoice`` or ``final_account`` (charged once on the final account).
    applies_at: Mapped[str] = mapped_column(
        String(20), nullable=False, default="each_invoice", server_default="each_invoice"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # ``company`` or ``pack:<slug>`` when imported from a country pack.
    source: Mapped[str] = mapped_column(String(60), nullable=False, default="company", server_default="company")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<LevyCatalogueItem {self.code} {self.basis} {self.default_percent}>"


class SubcontractTerms(Base):
    """Deduction terms of one subcontract: retention cap, order, payment discount, levies.

    Keyed by the subcontract agreement and/or the contracts-module contract that
    writes the same subcontract, so the award can store terms on whichever
    record it creates first. Both are plain GUIDs at the ORM level.
    """

    __tablename__ = "oe_subcontractors_subcontract_terms"
    __table_args__ = (
        UniqueConstraint("agreement_id", name="uq_oe_subcontractors_subcontract_terms_agreement"),
        UniqueConstraint("contract_id", name="uq_oe_subcontractors_subcontract_terms_contract"),
    )

    agreement_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_subcontractors_agreement.id", ondelete="CASCADE"),
        nullable=True,
    )
    contract_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # Retention stops when it reaches this percent of the contract sum. NULL = no cap.
    retention_cap_percent: Mapped[Decimal | None] = mapped_column(Numeric(7, 3), nullable=True)
    payment_discount_percent: Mapped[Decimal | None] = mapped_column(Numeric(7, 3), nullable=True)
    payment_discount_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # The discount is in the signed subcontract, not only taken at payment.
    payment_discount_agreed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    # ``manual`` or ``award`` (written by the tender award).
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual", server_default="manual")
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    levies: Mapped[list[SubcontractLevy]] = relationship(
        back_populates="terms",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="SubcontractLevy.sort_order",
    )

    def __repr__(self) -> str:
        return f"<SubcontractTerms agreement={self.agreement_id} contract={self.contract_id}>"


class SubcontractLevy(Base):
    """One levy agreed on a subcontract, copied from the catalogue or typed in."""

    __tablename__ = "oe_subcontractors_subcontract_levy"

    terms_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_subcontractors_subcontract_terms.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    catalogue_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    code: Mapped[str] = mapped_column(String(60), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    basis: Mapped[str] = mapped_column(String(20), nullable=False, default="percent", server_default="percent")
    rate_percent: Mapped[Decimal | None] = mapped_column(Numeric(7, 3), nullable=True)
    fixed_amount: Mapped[Decimal | None] = mapped_column(MoneyType(), nullable=True)
    applies_at: Mapped[str] = mapped_column(
        String(20), nullable=False, default="each_invoice", server_default="each_invoice"
    )
    # ``gross`` (default) or ``net_after_retention``: what a percentage levy is taken on.
    levy_base: Mapped[str] = mapped_column(String(30), nullable=False, default="gross", server_default="gross")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    terms: Mapped[SubcontractTerms] = relationship(back_populates="levies", lazy="raise_on_sql")

    def __repr__(self) -> str:
        return f"<SubcontractLevy {self.code} {self.rate_percent}>"


class FirmLocation(Base):
    """Coordinates of a subcontractor's address (geocoded or entered by hand)."""

    __tablename__ = "oe_subcontractors_firm_location"
    __table_args__ = (UniqueConstraint("subcontractor_id", name="uq_oe_subcontractors_firm_location_sub"),)

    subcontractor_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_subcontractors_subcontractor.id", ondelete="CASCADE"),
        nullable=False,
    )
    lat: Mapped[Decimal] = mapped_column(Numeric(10, 7), nullable=False)
    lon: Mapped[Decimal] = mapped_column(Numeric(10, 7), nullable=False)
    # ``geocoder`` or ``manual``.
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual", server_default="manual")
    precision: Mapped[str | None] = mapped_column(String(20), nullable=True)
    address_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    located_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<FirmLocation sub={self.subcontractor_id} {self.lat},{self.lon}>"


class SubcontractorFavourite(Base):
    """A firm the company prefers for one trade."""

    __tablename__ = "oe_subcontractors_favourite"
    __table_args__ = (UniqueConstraint("subcontractor_id", "trade", name="uq_oe_subcontractors_favourite_trade"),)

    subcontractor_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_subcontractors_subcontractor.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    trade: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    def __repr__(self) -> str:
        return f"<SubcontractorFavourite sub={self.subcontractor_id} trade={self.trade}>"
