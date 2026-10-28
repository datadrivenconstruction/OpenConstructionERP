# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Temporary-works ORM models (safety-critical governance register).

Tables:
    oe_temp_works_item    - one temporary-works item on a project (falsework,
                            propping, excavation support, facade retention, crane
                            base, ...), carrying its lifecycle status, design
                            check category and the people responsible.
    oe_temp_works_permit  - a permit issued against an item by the Temporary
                            Works Coordinator (permit to load / strike /
                            dismantle), the record that authorises loading or
                            striking the works.

Clearance is never stored: whether an item is cleared to load or strike, how far
design clearance has progressed, which items are overdue, and whether any item is
bearing load without a valid permit are all derived from the rows by the pure
functions in :mod:`app.modules.temporary_works.register`. Both tables foreign-key
into ``oe_projects_project`` by id only (cascade on project delete) and never
alter it; a permit additionally foreign-keys into its item (cascade on item
delete). The permit carries its own ``project_id`` so every query is
project-scoped without a join. GUID primary keys, timezone-aware ``created_at`` /
``updated_at`` and calendar dates follow the platform column-type conventions.
Vocabulary columns (type, status, category, permit type) are stored as plain
strings, not DB enums, so a new value never needs a schema migration; the allowed
values are enforced at the API edge and in the pure register core.
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

# -- Temporary-works item ----------------------------------------------------


class TemporaryWorksItem(Base):
    """One temporary-works item on a project.

    ``tw_type`` places the item in a temporary-works family (falsework,
    formwork, propping, excavation support, scaffold, facade retention, crane
    base, edge protection, dewatering, hoarding, other). ``status`` tracks it
    through the governance lifecycle from ``identified`` to ``removed`` (with
    ``on_hold`` as a side state). ``design_check_category`` records the required
    rigour of the independent design check (0 to 3). The clearance decisions and
    the derived register numbers come from
    :mod:`app.modules.temporary_works.register`, never from this row directly.

    The soft-link columns (``formwork_assignment_id``, ``design_document_id``,
    ``check_certificate_document_id``, ``schedule_activity_id``, ``twc_user_id``)
    reference rows owned by other modules and deliberately carry no foreign key,
    so this safety register never blocks or cascades another module's deletes.
    """

    __tablename__ = "oe_temp_works_item"
    __table_args__ = (
        Index("ix_temp_works_item_project", "project_id"),
        Index("ix_temp_works_item_project_status", "project_id", "status"),
        Index("ix_temp_works_item_project_type", "project_id", "tw_type"),
        UniqueConstraint(
            "project_id",
            "reference",
            name="uq_temp_works_item_project_reference",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
    )
    reference: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    tw_type: Mapped[str] = mapped_column(String(40), nullable=False)
    # Independent design check category (0-3); null until it is categorised.
    design_check_category: Mapped[str | None] = mapped_column(String(4), nullable=True)
    designer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    checker_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    twc_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Soft link to the Temporary Works Coordinator's user row (no FK).
    twc_user_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="identified",
        server_default="identified",
    )
    required_load_date: Mapped[date | None] = mapped_column(SafeDate(), nullable=True)
    required_strike_date: Mapped[date | None] = mapped_column(SafeDate(), nullable=True)
    design_due_date: Mapped[date | None] = mapped_column(SafeDate(), nullable=True)
    location: Mapped[str | None] = mapped_column(String(500), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Soft links to rows owned by other modules (no FK - see class docstring).
    formwork_assignment_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    design_document_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    check_certificate_document_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    schedule_activity_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)

    permits: Mapped[list["TemporaryWorksPermit"]] = relationship(
        "app.modules.temporary_works.models.TemporaryWorksPermit",
        back_populates="item",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<TemporaryWorksItem {self.reference!r} ({self.tw_type}/{self.status}) project={self.project_id}>"


# -- Permit ------------------------------------------------------------------


class TemporaryWorksPermit(Base):
    """A permit issued against a temporary-works item by the coordinator.

    ``permit_type`` is the authorisation this permit grants (permit to load /
    strike / dismantle) and ``status`` tracks it from ``draft`` to ``closed``.
    The two prerequisite flags (``prereq_design_check_accepted``,
    ``prereq_inspection_passed``) record the safety checks the coordinator
    confirmed before issuing a permit to load; the pure register core only treats
    an item as cleared to load when a valid permit to load carries both. The
    permit carries its own ``project_id`` (copied from its item's project) so
    every listing and rollup query is project-scoped without a join, and it
    foreign-keys into its item so it is deleted with the item.
    """

    __tablename__ = "oe_temp_works_permit"
    __table_args__ = (
        Index("ix_temp_works_permit_project", "project_id"),
        Index("ix_temp_works_permit_item", "item_id"),
        Index("ix_temp_works_permit_project_status", "project_id", "status"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_temp_works_item.id", ondelete="CASCADE"),
        nullable=False,
    )
    permit_number: Mapped[str] = mapped_column(String(40), nullable=False)
    permit_type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="draft",
        server_default="draft",
    )
    # The Temporary Works Coordinator who issued the permit (free text).
    issued_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    issued_at: Mapped[date | None] = mapped_column(SafeDate(), nullable=True)
    valid_from: Mapped[date | None] = mapped_column(SafeDate(), nullable=True)
    valid_to: Mapped[date | None] = mapped_column(SafeDate(), nullable=True)
    closed_at: Mapped[date | None] = mapped_column(SafeDate(), nullable=True)
    closed_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # Soft link to the inspection-before-use record (no FK).
    inspection_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    prereq_design_check_accepted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    prereq_inspection_passed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    conditions: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)

    item: Mapped["TemporaryWorksItem"] = relationship(
        "app.modules.temporary_works.models.TemporaryWorksItem",
        back_populates="permits",
    )

    def __repr__(self) -> str:
        return f"<TemporaryWorksPermit {self.permit_number!r} ({self.permit_type}/{self.status}) item={self.item_id}>"
