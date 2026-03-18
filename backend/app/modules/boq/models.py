"""BOQ ORM models.

Tables:
    oe_boq_boq — bill of quantities (one per project scope)
    oe_boq_position — individual line items within a BOQ
    oe_boq_markup — markup/overhead lines applied to a BOQ
"""

import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base


class BOQ(Base):
    """Bill of Quantities — groups positions for a project."""

    __tablename__ = "oe_boq_boq"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft")
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # Relationships
    positions: Mapped[list["Position"]] = relationship(
        back_populates="boq",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="Position.sort_order",
    )
    markups: Mapped[list["BOQMarkup"]] = relationship(
        back_populates="boq",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="BOQMarkup.sort_order",
    )

    def __repr__(self) -> str:
        return f"<BOQ {self.name} ({self.status})>"


class Position(Base):
    """Single line item in a BOQ — the core estimation entity."""

    __tablename__ = "oe_boq_position"

    boq_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_boq_boq.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_boq_position.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    ordinal: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    unit_rate: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    total: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    classification: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="manual")
    confidence: Mapped[str | None] = mapped_column(String(10), nullable=True)
    cad_element_ids: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    validation_status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="pending"
    )
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Relationships
    boq: Mapped[BOQ] = relationship(back_populates="positions")
    children: Mapped[list["Position"]] = relationship(
        back_populates="parent",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    parent: Mapped["Position | None"] = relationship(
        back_populates="children",
        remote_side="Position.id",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Position {self.ordinal} — {self.description[:40]}>"


class BOQMarkup(Base):
    """Markup line applied to a BOQ (overhead, profit, tax, contingency).

    Represents a single markup/overhead line that is applied on top of the
    direct cost (sum of position totals).  Markups are ordered by ``sort_order``
    and can be applied as a percentage of the direct cost, a fixed amount, or
    cumulatively (percentage of direct cost + preceding markups).

    Columns:
        boq_id — owning BOQ
        name — human-readable label, e.g. "Site Overhead (BGK)"
        markup_type — "percentage" | "fixed" | "per_unit"
        category — semantic grouping: overhead, profit, tax, contingency, …
        percentage — stored as string for SQLite compatibility (e.g. "8.0")
        fixed_amount — used when markup_type is "fixed"
        apply_to — "direct_cost" (default) or "cumulative"
        sort_order — evaluation order (ascending)
        is_active — soft toggle
    """

    __tablename__ = "oe_boq_markup"

    boq_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_boq_boq.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    markup_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="percentage"
    )
    category: Mapped[str] = mapped_column(
        String(100), nullable=False, default="overhead"
    )
    percentage: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    fixed_amount: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    apply_to: Mapped[str] = mapped_column(
        String(50), nullable=False, default="direct_cost"
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # Relationships
    boq: Mapped[BOQ] = relationship(back_populates="markups")

    def __repr__(self) -> str:
        return f"<BOQMarkup {self.name} ({self.markup_type}: {self.percentage}%)>"
