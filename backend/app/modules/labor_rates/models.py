# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Labor rate ORM models.

Tables:
    oe_labor_rates_template     - a reusable all-in labor rate build-up (a base
        wage plus a list of on-cost components), owned by a user.
    oe_labor_rates_oncost       - one on-cost component of a template
        (percentage or fixed amount).
    oe_labor_rates_crew_member  - one trade line of a saved crew, grouped by
        ``crew_id``, carrying its own all-in rate for blending.

Numeric columns carry a ``server_default`` so raw-SQL inserts and the
``create_all`` bootstrap always get a defined value; money and factors are
stored as ``Numeric`` and round-trip as ``Decimal``.
"""

import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base


class LaborRateTemplate(Base):
    """A reusable all-in labor rate build-up owned by a user.

    A template holds the productive base wage and its currency; the on-cost
    components that burden that wage into a fully loaded hourly rate are stored
    as child :class:`OnCostComponent` rows.
    """

    __tablename__ = "oe_labor_rates_template"

    # Owner scope for per-tenant isolation. NULL is a legacy / platform-wide
    # row readable only by admins (mirrors the assemblies module).
    owner_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    base_wage: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"), server_default="0")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="", server_default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")

    components: Mapped[list["OnCostComponent"]] = relationship(
        back_populates="template",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="OnCostComponent.sort_order",
    )

    def __repr__(self) -> str:  # pragma: no cover - debug repr
        return f"<LaborRateTemplate {self.name[:40]} base={self.base_wage} {self.currency}>"


class OnCostComponent(Base):
    """One on-cost component of a labor rate template.

    ``kind`` is ``percentage`` (a percentage of the base wage) or ``fixed`` (a
    flat currency amount per hour). ``value`` holds the percentage or the fixed
    amount accordingly.
    """

    __tablename__ = "oe_labor_rates_oncost"

    template_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_labor_rates_template.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="percentage", server_default="percentage")
    value: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"), server_default="0")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    template: Mapped[LaborRateTemplate] = relationship(back_populates="components")

    def __repr__(self) -> str:  # pragma: no cover - debug repr
        return f"<OnCostComponent {self.label[:30]} {self.kind}={self.value}>"


class CrewMember(Base):
    """One trade line of a saved crew, grouped by ``crew_id``.

    A crew is a logical grouping of trade lines identified by ``crew_id``; each
    line carries a headcount ``count`` and its own ``all_in_rate`` so the crew
    can be blended into a composite hourly rate.
    """

    __tablename__ = "oe_labor_rates_crew_member"

    # Owner scope for per-tenant isolation (see LaborRateTemplate.owner_id).
    owner_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    # Logical crew grouping id. Not a foreign key - there is no separate crew
    # table; members that share a crew_id form one crew.
    crew_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    trade: Mapped[str] = mapped_column(String(120), nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    all_in_rate: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, default=Decimal("0"), server_default="0"
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="", server_default="")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    def __repr__(self) -> str:  # pragma: no cover - debug repr
        return f"<CrewMember {self.trade[:30]} x{self.count} @ {self.all_in_rate}>"
