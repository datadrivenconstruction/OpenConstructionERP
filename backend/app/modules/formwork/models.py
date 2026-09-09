# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Formwork ORM models.

Tables:
    oe_formwork_system            - catalogue row (framed wall panel, slab deck, ...)
    oe_formwork_assignment        - links a project / BOQ position to a system
    oe_formwork_schedule_line     - optional pour-by-pour cycle under an assignment

Money columns use ``Numeric(18, 2)`` (the project's "money as Decimal" rule)
and serialise as strings via Pydantic in :mod:`app.modules.formwork.schemas`.

Every NOT NULL column carries an explicit Python-side ``default`` so an ORM
insert never depends on a DB-side default, and the matching migration
(``v3132_formwork_init`` plus ``v3262_formwork_rate_buildup``) carries the
equivalent ``server_default`` so raw-SQL inserts and column backfills on an
existing database are safe too. The four rate columns ``v3262`` added carry
that ``server_default`` on the model as well, because ``create_all`` is the
build path every embedded and self-hosted install boots on, it reads the model
and never the revision, and a column it builds without the DEFAULT the revision
declared is what the boot repair ``formwork_rate_buildup_not_null`` then
reports as a schema repair on a database that is seconds old. Losing either
half is how the v3119 fresh-install cascade happened, so keep both in step. The migrations that
carry this table are ``v3132_formwork_init``, ``v3262_formwork_rate_buildup``,
``v3271_formwork_debrand`` and ``v3300_formwork_system_choice``.

Relationship loading is declared explicitly on every ``relationship()`` per
``.claude/rules/backend-modules.md``: the pour cycle is the point of an
assignment, so it loads ``selectin``; every back-reference and every
rarely-walked collection is ``raise_on_sql``, which still allows a free read
off an already-loaded instance but refuses to emit lazy SQL from the async
session.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base


class FormworkSystem(Base):
    """Catalogue entry for one physical formwork system.

    A system is the reusable thing the contractor buys/rents: a framed steel
    panel set, an aluminium slab table, raw plywood + studs, etc.

    A formwork rate has two components and only one of them amortises:

    * ``unit_rate`` - per-m2 acquisition (or full-job hire) cost of the panels
      themselves. Buy the set once, use it ``reuse_count`` times, so this is
      what gets divided down.
    * ``erect_strike_rate`` - per-m2 labour and consumables (release agent,
      ties, cones, cleaning) paid EVERY time the panels are set and struck.
      This never amortises: forming 1000 m2 over ten uses of a 100 m2 set
      costs ten sets of erect-and-strike labour, not one.

    Pricing only the first component is the classic way to under-price a
    concrete-heavy job, so both are carried here and reported separately on
    the assignment (see :class:`FormworkAssignment`).

    ``strip_time_days`` is the minimum age of the pour before the panels can
    be struck and moved to the next lift. It sets the floor on the pour cycle,
    so a schedule that turns the same set around faster than this is not
    buildable - the ``formwork.strip_time_respected`` validation rule checks
    exactly that.

    Three columns describe the system as a *choice* rather than as a price,
    because choosing between systems is the decision this module exists to
    support and a catalogue that carries only a rate cannot support it:

    * ``rate_basis`` says what ``unit_rate`` MEANS, and it is the one of the
      three that changes the arithmetic. A purchase rate buys the panels once
      and amortises over the reuses; a per-use hire rate and an all-in
      supply-and-fix subcontract rate are already per-use and must not be
      divided a second time. See :func:`app.modules.formwork.service.compute_cost`.
    * ``typical_reuses`` is the planning figure - what this system usually
      delivers on a normal job - as opposed to ``reuses_max``, which is the
      physical limit the panels survive. Nullable on purpose: NULL reads as
      "no published figure", which is honestly different from zero, and the
      chooser falls back to ``reuses_max`` for the hint.
    * ``cycle_days`` is the pour-to-pour turnaround the system delivers with a
      normal crew. It is NOT ``strip_time_days``: striking is the floor on the
      cycle, the cycle is strip plus clean, move, set and align. A climbing
      system strikes in 3 days and still turns around in 7.
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
    # Labour + consumables per m2 of formed area, charged once per use and
    # therefore NOT divided by ``reuse_count``. Defaults to zero so every row
    # written before this column existed keeps its original priced total.
    erect_strike_rate: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    # Minimum days from pour to strike. Drives the cycle-feasibility check.
    strip_time_days: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    # What ``unit_rate`` means. "purchase" amortises over the reuses; the
    # per-use bases do not. Defaults to "purchase" so every row written before
    # this column existed keeps the arithmetic it was priced with.
    rate_basis: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="purchase",
        server_default="purchase",
        index=True,
    )
    # Planning reuse figure. NULL means "no published figure" - deliberately
    # nullable rather than 0, so a caller never has to guess whether zero is a
    # real answer or a missing one.
    typical_reuses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Pour-to-pour turnaround in days, crew-normal. Strip time is its floor.
    cycle_days: Mapped[Decimal] = mapped_column(
        Numeric(6, 2),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        nullable=True,
        index=True,
    )

    # Rarely walked from this side and unbounded in size (one catalogue row can
    # back every assignment on every project), so it is ``raise_on_sql``: the
    # re-pricing path queries the assignment table directly with a filter and
    # a limit instead of dragging the whole collection into memory.
    assignments: Mapped[list[FormworkAssignment]] = relationship(
        back_populates="system",
        lazy="raise_on_sql",
    )

    def __repr__(self) -> str:
        return f"<FormworkSystem {self.name} ({self.system_type}/{self.material})>"


class FormworkAssignment(Base):
    """Assigns a formwork system to a project (optionally to a BOQ position).

    ``computed_*`` columns are persisted (not pure SQL-computed columns) so
    reports and downstream rollups can index/sort on them cheaply; the service
    layer recomputes them on every write to the assignment AND on every write
    to the catalogue system it points at.

    Formula:
        material unit cost = unit_rate * (1 + waste_pct/100) / max(reuse_count, 1)
        labour unit cost   = erect_strike_rate
        unit cost          = material unit cost + labour unit cost
        total              = area_m2 * unit cost

    Waste is applied to the material component only: over-ordering covers
    panel offcuts and damage, it does not buy extra erect-and-strike labour.
    The two components are stored separately because that split is the first
    thing a quantity surveyor checks when a formwork rate looks wrong.
    """

    __tablename__ = "oe_formwork_assignment"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Nullable: early-design estimates may not yet have a BOQ position
    # wired up. No FK to ``oe_boq_position`` - we keep it loose so the
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
    # The two halves of ``computed_unit_cost``, persisted so a report can show
    # the rate build-up without re-deriving it from the catalogue.
    material_unit_cost: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    labour_unit_cost: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
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

    # The pour cycle IS the point of an assignment - every detail read and
    # every cycle computation walks it - so it loads eagerly with one extra
    # SELECT. ``delete-orphan`` keeps the lines with their parent.
    schedule_lines: Mapped[list[FormworkScheduleLine]] = relationship(
        back_populates="assignment",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="FormworkScheduleLine.pour_no",
    )
    # Many-to-one back up to the catalogue. The FK is already in the column, so
    # an implicit walk up here would be a lazy SELECT from the async session -
    # exactly the crash the loading policy exists to prevent. Callers that need
    # the system row order it explicitly with ``selectinload``.
    system: Mapped[FormworkSystem] = relationship(
        back_populates="assignments",
        lazy="raise_on_sql",
    )

    def __repr__(self) -> str:
        return f"<FormworkAssignment project={self.project_id} area={self.area_m2}m2 total={self.computed_total}>"


class FormworkScheduleLine(Base):
    """One pour of the cycle under a :class:`FormworkAssignment`.

    Lets the estimator describe the climbing / re-use sequence (Level 02
    walls, Level 03 walls, ...) without breaking the assignment apart.

    The cycle is not decoration: the largest single pour is the panel set the
    contractor actually has to buy or hire, and the total pour area divided by
    that set size is the reuse count the rate may honestly be amortised over.
    ``FormworkService.analyse_cycle`` derives both, and
    ``derive_from_schedule`` writes them back onto the assignment.
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
    # Annotated ``date``, not ``str``: the column is DATE and the ORM hands
    # back a ``datetime.date``, so the old ``str`` hint made every reader of
    # this attribute type-check against the wrong thing.
    pour_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    level_label: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    area_m2: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=Decimal("0"),
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Child back-reference: FK is already in ``assignment_id``, so walking up
    # implicitly would fire lazy SQL. ``raise_on_sql`` still allows the free
    # read when the parent came in through ``schedule_lines``.
    assignment: Mapped[FormworkAssignment] = relationship(
        back_populates="schedule_lines",
        lazy="raise_on_sql",
    )

    def __repr__(self) -> str:
        return f"<FormworkScheduleLine #{self.pour_no} {self.level_label} {self.area_m2}m2>"
