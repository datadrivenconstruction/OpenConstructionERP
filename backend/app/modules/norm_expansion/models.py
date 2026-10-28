# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Production-norm ORM models.

Tables:
    oe_norm_expansion_norm     - one work item's per-unit productivity
        coefficients (labor-hours, machine-hours) keyed by ``work_key``
    oe_norm_expansion_material - a material this norm consumes per unit

The library is unpriced on purpose: it stores hours and material quantities
per unit, never rates or money, so it never duplicates the priced recipes the
assemblies module already owns.

Coefficient columns use ``Numeric(18, 6)`` (real ``Decimal`` round-trips) and
carry an explicit ``server_default`` of ``"0"``. Without the server default a
fresh install built by ``Base.metadata.create_all`` (which ignores Python-side
defaults) would emit NOT NULL columns with no default and reject the seed.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base


class ProductionNorm(Base):
    """Per-unit productivity coefficients for one work item.

    A norm answers "how much labour, machine time and material does one unit
    of this work consume". Multiplying the coefficients by a work quantity
    (see :mod:`app.modules.norm_expansion.expand_math`) yields the unpriced
    resource demand behind a rate.
    """

    __tablename__ = "oe_norm_expansion_norm"

    work_key: Mapped[str] = mapped_column(
        String(120),
        unique=True,
        index=True,
        nullable=False,
        doc="Stable lookup key for the work item, e.g. 'plastering_internal'.",
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    unit: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="",
        server_default="",
        doc="Unit the work item is measured in (m2, m3, m, kg, pcs, ...).",
    )
    category: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="",
        server_default="",
        index=True,
    )
    labor_hours_per_unit: Mapped[Decimal] = mapped_column(
        Numeric(18, 6),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
        doc="Labour-hours consumed per unit of the work item.",
    )
    machine_hours_per_unit: Mapped[Decimal] = mapped_column(
        Numeric(18, 6),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
        doc="Machine-hours consumed per unit of the work item.",
    )
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="1",
    )

    materials: Mapped[list[NormMaterial]] = relationship(
        back_populates="norm",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="NormMaterial.sort_order",
    )

    def __repr__(self) -> str:
        return f"<ProductionNorm {self.work_key} ({self.unit})>"


class NormMaterial(Base):
    """A single material a production norm consumes per unit of work.

    The quantity is unpriced - a takeoff figure, not a cost. Pricing happens
    elsewhere (assemblies / cost matching) once the estimator has confirmed the
    demand.
    """

    __tablename__ = "oe_norm_expansion_material"

    norm_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_norm_expansion_norm.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    unit: Mapped[str] = mapped_column(String(20), nullable=False, default="", server_default="")
    qty_per_unit: Mapped[Decimal] = mapped_column(
        Numeric(18, 6),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
        doc="Quantity of the material consumed per unit of the work item.",
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    norm: Mapped[ProductionNorm] = relationship(back_populates="materials")

    def __repr__(self) -> str:
        return f"<NormMaterial {self.name} {self.qty_per_unit}/{self.unit}>"
