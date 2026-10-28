# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Allowances & contingency register ORM models.

Tables:
    oe_allowances_allowance   - one allowance carried in the estimate but not yet
                                measured (a provisional sum, a prime-cost sum, or
                                a design / construction contingency)
    oe_allowances_drawdown    - one amount drawn against an allowance as scope firms up

``held_amount`` and ``amount`` are ``NUMERIC(18, 4)`` so the Python layer always
sees a :class:`decimal.Decimal` (matching the CVR and costs money columns). Money
is never a float: the service quantizes to 2dp and the schemas emit it as
Decimal-as-string on the wire. Both money columns carry a ``server_default`` of
``"0"`` so the schema built by ``create_all`` is complete without a data migration.
"""

import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base


class Allowance(Base):
    """One allowance held in a project's estimate ahead of firm measurement.

    ``allowance_type`` is one of ``provisional_sum`` / ``pc_sum`` / ``contingency``
    (validated in the schema, so the column stays a plain short string here).
    ``held_amount`` is the amount carried, denominated in ``currency`` (an ISO 4217
    code, blank until set so the UI renders the number without mislabelling it).
    The running spend against the allowance lives in its :class:`AllowanceDrawdown`
    rows; remaining is always derived (held minus the drawdowns), never stored.
    """

    __tablename__ = "oe_allowances_allowance"
    __table_args__ = (Index("ix_allowances_allowance_project_type", "project_id", "allowance_type"),)

    # Scoped to a project; the row cascades away with the project it belongs to.
    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    label: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # provisional_sum | pc_sum | contingency (guarded in the schema layer).
    allowance_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="provisional_sum",
        server_default="provisional_sum",
        index=True,
    )
    held_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    # ISO 4217 code the held amount is denominated in. Empty string until set
    # (mirrors the CVR "no silent EUR default" rule - the UI renders amounts
    # without a symbol rather than mislabelling them).
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="", server_default="")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    drawdowns: Mapped[list["AllowanceDrawdown"]] = relationship(
        back_populates="allowance",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="AllowanceDrawdown.created_at",
    )

    def __repr__(self) -> str:
        return f"<Allowance {self.label or self.allowance_type} held={self.held_amount}>"


class AllowanceDrawdown(Base):
    """One amount drawn against an allowance as scope firms up.

    A drawdown records that part of an allowance has now been committed or spent.
    ``amount`` is positive money in the parent allowance's currency; ``note`` is
    the free-text reason (which package the sum was released to, etc.). Remaining
    on the allowance is the held amount minus the sum of these rows; over-drawing
    is allowed and flagged as advisory, never blocked.
    """

    __tablename__ = "oe_allowances_drawdown"
    __table_args__ = (Index("ix_allowances_drawdown_allowance_created", "allowance_id", "created_at"),)

    allowance_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_allowances_allowance.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    allowance: Mapped["Allowance"] = relationship(back_populates="drawdowns")

    def __repr__(self) -> str:
        return f"<AllowanceDrawdown allowance={self.allowance_id} amount={self.amount}>"
