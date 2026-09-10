# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Site-prep ORM models (pre-construction mobilisation and site-setup readiness).

Tables:
    oe_site_prep_plan  - one mobilisation plan per project (target start, status)
    oe_site_prep_item  - a single readiness item (access, welfare, utilities,
                         hoarding, temporary works, permits, inductions, ...)

Readiness itself is never stored: percentages, the commencement-gate status and
the blocked / overdue lists are derived from the items by the pure functions in
:mod:`app.modules.site_prep.readiness`. The tables foreign-key into
``oe_projects_project`` by id only (cascade on project delete) and never alter it.
GUID primary keys, timezone-aware ``created_at`` / ``updated_at`` and calendar
dates follow the platform column-type conventions.
"""

import uuid
from datetime import date

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db_types import SafeDate
from app.database import GUID, Base

# -- Mobilisation plan -------------------------------------------------------


class SitePrepPlan(Base):
    """A per-project pre-construction mobilisation plan.

    Holds the planned commencement date and a coarse lifecycle status
    (``draft`` -> ``active`` -> ``complete``) that the readiness items hang off.
    One plan per project (enforced by a unique constraint on ``project_id``); an
    item may reference it, but items can also exist without a plan so a site can
    start listing readiness items before the plan header is filled in.
    """

    __tablename__ = "oe_site_prep_plan"
    __table_args__ = (
        UniqueConstraint("project_id", name="uq_site_prep_plan_project"),
        Index("ix_site_prep_plan_project", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_start_date: Mapped[date | None] = mapped_column(SafeDate(), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="draft",
        server_default="draft",
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)

    items: Mapped[list["SitePrepItem"]] = relationship(
        "app.modules.site_prep.models.SitePrepItem",
        back_populates="plan",
        cascade="save-update, merge",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<SitePrepPlan project={self.project_id} status={self.status}>"


# -- Readiness item ----------------------------------------------------------


class SitePrepItem(Base):
    """One pre-construction readiness item on a project.

    ``category`` places the item in a mobilisation bucket (access, welfare,
    temporary utilities, security / hoarding, temporary works, environmental
    controls, logistics / laydown, permits / consents, inductions / training,
    other) and ``status`` tracks it from ``not_started`` through ``ready``.
    ``is_gate`` marks a hard prerequisite to commence on site: the project is not
    gate-ready until every gate item is ``ready`` (or ``not_applicable``). The
    direction and the derived readiness numbers come from
    :mod:`app.modules.site_prep.readiness`, never from this row directly.
    """

    __tablename__ = "oe_site_prep_item"
    __table_args__ = (
        Index("ix_site_prep_item_project", "project_id"),
        Index("ix_site_prep_item_project_category", "project_id", "category"),
        Index("ix_site_prep_item_project_status", "project_id", "status"),
        Index("ix_site_prep_item_plan", "plan_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Optional link to the project's mobilisation plan. SET NULL on delete so an
    # item survives the removal of the plan header it referenced.
    plan_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_site_prep_plan.id", ondelete="SET NULL"),
        nullable=True,
    )
    category: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="other",
        server_default="other",
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="not_started",
        server_default="not_started",
    )
    responsible_party: Mapped[str | None] = mapped_column(String(255), nullable=True)
    due_date: Mapped[date | None] = mapped_column(SafeDate(), nullable=True)
    completed_date: Mapped[date | None] = mapped_column(SafeDate(), nullable=True)
    is_gate: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)

    plan: Mapped["SitePrepPlan | None"] = relationship(
        "app.modules.site_prep.models.SitePrepPlan",
        back_populates="items",
        lazy="raise_on_sql",
    )

    def __repr__(self) -> str:
        return f"<SitePrepItem {self.title!r} ({self.category}/{self.status}) project={self.project_id}>"
