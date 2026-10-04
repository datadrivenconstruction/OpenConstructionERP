# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Price-index ORM models.

Tables:
    oe_price_index_series          - a named construction cost index series
    oe_price_index_point           - one period/value point within a series
    oe_price_index_location_factor - a regional cost factor keyed by region code
    oe_price_index_resource_index  - a resource-index value per region, quarter and group
    oe_price_index_overhead_norm   - NR and SP percentages of the wage fund per work type

The reference data is platform-wide (not project-scoped): an index series and
its regional factors are shared across every estimate. Every NOT NULL column
carries an explicit ``server_default`` because ``Base.metadata.create_all``
ignores Python-side defaults, and this schema is built via ``create_all`` on a
fresh install ahead of any migration.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base


class CostIndexSeries(Base):
    """A named construction cost index (a time series of period factors).

    A series holds many :class:`CostIndexPoint` rows, one per period. The
    temporal escalation factor between any two of those periods is their index
    ratio (see :func:`app.modules.price_index.index_math.resolve_factor`).
    """

    __tablename__ = "oe_price_index_series"

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
        index=True,
        default="",
        server_default="",
    )
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
    )

    points: Mapped[list[CostIndexPoint]] = relationship(
        back_populates="series",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="CostIndexPoint.period",
    )

    def __repr__(self) -> str:
        return f"<CostIndexSeries {self.name!r}>"


class CostIndexPoint(Base):
    """One ``(period, factor)`` observation inside a :class:`CostIndexSeries`.

    ``period`` is an ISO year-month string ``"YYYY-MM"``. ``factor`` is the
    index value at that period; the absolute base is arbitrary because only
    ratios between two periods are ever used, so a series may be normalised to
    ``1`` at any chosen base period or left on its published scale.
    """

    __tablename__ = "oe_price_index_point"
    __table_args__ = (UniqueConstraint("series_id", "period", name="uq_price_index_point_series_period"),)

    series_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_price_index_series.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    period: Mapped[str] = mapped_column(String(7), nullable=False, default="", server_default="")
    factor: Mapped[Decimal] = mapped_column(
        Numeric(18, 6),
        nullable=False,
        default=Decimal("1"),
        server_default="1",
    )

    series: Mapped[CostIndexSeries] = relationship(back_populates="points")

    def __repr__(self) -> str:
        return f"<CostIndexPoint {self.period} factor={self.factor}>"


class LocationFactor(Base):
    """A regional cost factor keyed by a free-form region code.

    The factor expresses how a region's construction costs sit relative to the
    national baseline of ``1`` (for example ``1.15`` for a high-cost metro,
    ``0.90`` for a low-cost rural area). Converting a rate from one region to
    another applies the ratio of the two factors (see
    :func:`app.modules.price_index.index_math.location_multiplier`).
    """

    __tablename__ = "oe_price_index_location_factor"

    region_code: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
        index=True,
        default="",
        server_default="",
    )
    label: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    factor: Mapped[Decimal] = mapped_column(
        Numeric(18, 6),
        nullable=False,
        default=Decimal("1"),
        server_default="1",
    )

    def __repr__(self) -> str:
        return f"<LocationFactor {self.region_code} factor={self.factor}>"


class ResourceIndexValue(Base):
    """One index of the resource-index method: a group, a region, a quarter.

    The Minstroy publishes these quarterly per region: an index for workers'
    wages, for machine operation, for machine operators' wages and for
    materials. A row is the value one letter gives for one group. ``source``
    names the letter; ``is_sample`` marks the rows the platform ships for
    demonstration, which are not official and have to be replaced.
    """

    __tablename__ = "oe_price_index_resource_index"
    __table_args__ = (
        UniqueConstraint(
            "region_code",
            "quarter",
            "resource_group",
            name="uq_price_index_resource_index_key",
        ),
    )

    region_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True, server_default="")
    # ``YYYY-Qn``, e.g. ``2026-Q1``.
    quarter: Mapped[str] = mapped_column(String(7), nullable=False, server_default="")
    # One of ``resource_index_math.INDEX_GROUPS``.
    resource_group: Mapped[str] = mapped_column(String(32), nullable=False, server_default="")
    index_value: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, server_default="1")
    source: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    is_sample: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")

    def __repr__(self) -> str:
        return f"<ResourceIndexValue {self.region_code} {self.quarter} {self.resource_group}={self.index_value}>"


class WorkTypeOverheadNorm(Base):
    """Overheads (NR) and estimated profit (SP) for one type of work.

    Both are percentages of the wage fund (workers' plus machine operators'
    wages), set per type of work by Minstroy orders 812/pr (NR) and 774/pr (SP).
    ``is_sample`` marks the rows the platform ships for demonstration.
    """

    __tablename__ = "oe_price_index_overhead_norm"

    work_type_code: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
        index=True,
        server_default="",
    )
    label: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    nr_pct: Mapped[Decimal] = mapped_column(Numeric(9, 4), nullable=False, server_default="0")
    sp_pct: Mapped[Decimal] = mapped_column(Numeric(9, 4), nullable=False, server_default="0")
    source: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    is_sample: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")

    def __repr__(self) -> str:
        return f"<WorkTypeOverheadNorm {self.work_type_code} NR={self.nr_pct} SP={self.sp_pct}>"
