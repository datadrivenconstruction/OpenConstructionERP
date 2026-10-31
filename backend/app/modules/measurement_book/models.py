# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Measurement book ORM model.

Table oe_measurement_book_entry: one dated measurement of one BOQ position.
The quantity is stored as computed when the entry was written, next to the
dimensions it came from, so a checker sees both the number and how it arose.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class MeasurementBookEntry(Base):
    """One dated measurement of one BOQ position."""

    __tablename__ = "oe_measurement_book_entry"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False, index=True
    )
    boq_position_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_boq_position.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entry_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    location: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    length: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    breadth: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    height: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    number: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    # Set instead of dimensions for items measured by count or read off a ticket.
    direct_quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    measured_by: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # unchecked, checked or disputed. Only checked entries count towards the running bill.
    check_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="unchecked", server_default="unchecked", index=True
    )
    # The checker's own re-measured quantity; NULL means the measured quantity was accepted as is.
    check_quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    checked_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    bill_ref: Mapped[str | None] = mapped_column(String(40), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    def __repr__(self) -> str:
        return f"<MeasurementBookEntry {self.entry_date} {self.quantity}>"
