"""Formwork ORM models.

Tables:
    oe_formwork_system            — catalogue row (Doka, PERI, generic plywood, ...)
    oe_formwork_assignment        — links a project / BOQ position to a system
    oe_formwork_schedule_line     — optional pour-by-pour cycle under an assignment

Money columns use ``Numeric(18, 2)`` (the project's "money as Decimal" rule)
and serialise as strings via Pydantic in :mod:`app.modules.formwork.schemas`.

All NOT NULL columns carry an explicit ``server_default`` — without this the
v3119 fresh-install cascade reappears when ``Base.metadata.create_all`` runs
ahead of the migration (Python defaults are ignored by ``create_all``).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class FormworkSystem(Base):
    """Catalogue entry for one physical formwork system.

    A system is the reusable thing the contractor buys/rents: a Doka Framax
    panel set, a PERI Skydeck slab table, raw plywood + studs, etc. The
    ``unit_rate`` is the per-m2 acquisition cost; the actual cost charged
    to a BOQ position depends on how many times the system is reused on
    that assignment (see :class:`FormworkAssignment.computed_unit_cost`).
    """

    __tablename__ = "oe_formwork_system"

    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    system_type: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="wall",
        index=True,
    )
    supplier: Mapped[str | None] = mapped_column(String(255), nullable=True)
    material: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="plywood",
        index=True,
    )
    reuses_max: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    unit_rate: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=Decimal("0"),
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        nullable=True,
        index=True,
    )

    def __repr__(self) -> str:
        return f"<FormworkSystem {self.name} ({self.system_type}/{self.material})>"


class FormworkAssignment(Base):
    """Assigns a formwork system to a project (optionally to a BOQ position).

    ``computed_unit_cost`` and ``computed_total`` are persisted (not pure
    SQL-computed columns) so reports and downstream rollups can index/sort
    on them cheaply; the service layer recomputes them on every write.

    Formula:
        unit cost = unit_rate * (1 + waste_pct/100) / max(reuse_count, 1)
        total     = area_m2 * unit cost
    """

    __tablename__ = "oe_formwork_assignment"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Nullable: early-design estimates may not yet have a BOQ position
    # wired up. No FK to ``oe_boq_position`` — we keep it loose so the
    # row survives a re-import / re-numbering of the BOQ (resolution is
    # service-layer, mirroring contracts.counterparty_id pattern).
    boq_position_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        nullable=True,
        index=True,
    )
    formwork_system_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_formwork_system.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    area_m2: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=Decimal("0"),
    )
    reuse_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    waste_pct: Mapped[Decimal] = mapped_column(
        Numeric(6, 2),
        nullable=False,
        default=Decimal("5.00"),
    )
    computed_unit_cost: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=Decimal("0"),
    )
    computed_total: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=Decimal("0"),
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        nullable=True,
        index=True,
    )

    def __repr__(self) -> str:
        return f"<FormworkAssignment project={self.project_id} area={self.area_m2}m2 total={self.computed_total}>"


class FormworkScheduleLine(Base):
    """Optional pour-by-pour cycle line under one FormworkAssignment.

    Lets the estimator describe the climbing / re-use sequence
    (Level 02 walls, Level 03 walls, ...) without breaking the
    assignment apart. Reporting on these is deliberately deferred.
    """

    __tablename__ = "oe_formwork_schedule_line"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_formwork_assignment.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    pour_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    pour_date: Mapped[str | None] = mapped_column(Date, nullable=True)
    level_label: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    area_m2: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=Decimal("0"),
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<FormworkScheduleLine #{self.pour_no} {self.level_label} {self.area_m2}m2>"
