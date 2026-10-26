# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Defects-liability ORM models (post-handover warranty and DLP register).

Tables:
    oe_dlp_warranty - one warranty / defects-liability-period entry on a project
                      (a covered element, its responsible subcontractor and work
                      package, the warranty type and the key dates, above all the
                      DLP end date that decides when retention can be released).
    oe_dlp_defect   - one defect notice raised against a warranty while the
                      defects liability period runs (who must fix what by when,
                      and whether it has been rectified).

Retention-release readiness is never stored: whether an entry is expiring or
expired, how many defects are open or overdue, the per-subcontractor health and -
the key signal - whether a warranty's DLP has ended with no outstanding defects
(and is therefore clear for the final retention money) are all derived from the
rows by the pure functions in :mod:`app.modules.defects_liability.register`. Both
tables foreign-key into ``oe_projects_project`` by id only (cascade on project
delete) and never alter it; a defect additionally foreign-keys into its warranty
(cascade on warranty delete) and carries its own ``project_id`` so every query is
project-scoped without a join.

The soft-link columns (``subcontractor_id``, ``contract_id``, ``document_id`` on
a warranty; ``punchlist_id``, ``ncr_id`` on a defect) reference rows owned by
other modules and deliberately carry no foreign key, so this register never
blocks or cascades another module's deletes. GUID primary keys, timezone-aware
``created_at`` / ``updated_at`` and calendar dates follow the platform
column-type conventions. Vocabulary columns (warranty type, warranty status,
defect status, defect severity) are stored as plain strings, not DB enums, so a
new value never needs a schema migration; the allowed values are enforced at the
API edge and in the pure register core.
"""

import uuid
from datetime import date

from sqlalchemy import (
    JSON,
    Float,
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

# -- Warranty / DLP entry ----------------------------------------------------


class DlpWarranty(Base):
    """One warranty / defects-liability-period entry on a project.

    ``warranty_type`` places the entry in a family (workmanship, manufacturer,
    latent_defect, extended, other). ``status`` tracks it through the
    post-handover lifecycle from ``in_dlp`` to ``closed`` (with ``expiring`` and
    ``expired`` as running states and ``on_hold`` as a side state). ``dlp_end_date``
    is the key date: once it has passed with no outstanding defects, the entry is
    clear for the final retention money to be released. The derived readiness
    signal and register numbers come from
    :mod:`app.modules.defects_liability.register`, never from this row directly.

    ``limitation_regime`` is nullable and stays that way unless somebody chooses
    one. It names the legal regime the warranty period was derived from (see
    :mod:`app.modules.defects_liability.limitation`), so the entry can say why it
    ends when it ends instead of asserting a date with no reason. An entry with no
    regime behaves exactly as it did before the column existed.

    The soft-link columns (``subcontractor_id``, ``contract_id``, ``document_id``)
    reference rows owned by other modules and deliberately carry no foreign key.
    ``retention_release_date`` records when the final retention was actually
    released and is distinct from the derived readiness flag (which is computed
    from ``dlp_end_date`` and the outstanding defects).
    """

    __tablename__ = "oe_dlp_warranty"
    __table_args__ = (
        Index("ix_dlp_warranty_project", "project_id"),
        Index("ix_dlp_warranty_project_status", "project_id", "status"),
        Index("ix_dlp_warranty_project_subcontractor", "project_id", "subcontractor_id"),
        UniqueConstraint(
            "project_id",
            "reference",
            name="uq_dlp_warranty_project_reference",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
    )
    reference: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    # What the warranty covers, e.g. "Roof membrane", "AHU-3", "Curtain wall zone B".
    element_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The liable subcontractor: an optional soft link to a subcontractor row (no
    # FK - see class docstring) plus its captured name for grouping and display.
    subcontractor_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    subcontractor_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    work_package: Mapped[str | None] = mapped_column(String(120), nullable=True)
    warranty_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    handover_date: Mapped[date | None] = mapped_column(SafeDate(), nullable=True)
    warranty_start_date: Mapped[date | None] = mapped_column(SafeDate(), nullable=True)
    warranty_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    warranty_end_date: Mapped[date | None] = mapped_column(SafeDate(), nullable=True)
    # Which legal regime the period above came from, or NULL when nobody chose
    # one. NULL is the state every entry starts in and the state every existing
    # row stays in: no regime means no period is derived, no date is rewritten
    # and nothing is said about why the warranty ends when it ends. The
    # vocabulary is ALL_LIMITATION_REGIMES in
    # :mod:`app.modules.defects_liability.limitation`, stored as a plain string
    # like every other vocabulary column here so a new regime never needs a
    # schema change. Deliberately no server default: a default would be this
    # module picking a jurisdiction's law for every project on earth.
    limitation_regime: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # The defects liability period end - the key date the readiness flag turns on.
    # A limitation regime never touches this column. It is contractual (it decides
    # when retention is released) rather than statutory, and deriving it from a
    # Verjährungsfrist would move the retention-release signal for everyone who
    # opts in. The regime derives warranty_months and warranty_end_date only.
    dlp_end_date: Mapped[date | None] = mapped_column(SafeDate(), nullable=True)
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="in_dlp",
        server_default="in_dlp",
    )
    # When the final retention was actually released (distinct from the derived
    # readiness flag, which is computed from dates + outstanding defects).
    retention_release_date: Mapped[date | None] = mapped_column(SafeDate(), nullable=True)
    # Soft links to rows owned by other modules (no FK - see class docstring).
    contract_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    document_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)

    defects: Mapped[list["DlpDefect"]] = relationship(
        "app.modules.defects_liability.models.DlpDefect",
        back_populates="warranty",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<DlpWarranty {self.reference!r} ({self.status}) project={self.project_id}>"


# -- Defect notice -----------------------------------------------------------


class DlpDefect(Base):
    """One defect notice raised against a warranty during its DLP.

    ``severity`` places the defect on a scale (minor, major, critical) and
    ``status`` tracks it from ``open`` to ``closed`` (with ``rectifying`` in
    between, and ``rejected`` for a notice the responsible party disputes and
    that is not upheld). Only ``open`` and ``rectifying`` defects count as
    outstanding in the pure register core, so a warranty is clear for retention
    release once none of its defects remain in those two states. The defect
    carries its own ``project_id`` (copied from its warranty's project) so every
    listing and rollup query is project-scoped without a join, and it foreign-keys
    into its warranty so it is deleted with the warranty.

    The soft-link columns (``punchlist_id``, ``ncr_id``) reference rows owned by
    other modules and deliberately carry no foreign key.
    """

    __tablename__ = "oe_dlp_defect"
    __table_args__ = (
        Index("ix_dlp_defect_project", "project_id"),
        Index("ix_dlp_defect_warranty", "warranty_id"),
        Index("ix_dlp_defect_project_status", "project_id", "status"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
    )
    warranty_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_dlp_warranty.id", ondelete="CASCADE"),
        nullable=False,
    )
    reference: Mapped[str] = mapped_column(String(40), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str | None] = mapped_column(String(20), nullable=True)
    raised_date: Mapped[date | None] = mapped_column(SafeDate(), nullable=True)
    due_date: Mapped[date | None] = mapped_column(SafeDate(), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="open",
        server_default="open",
    )
    rectified_date: Mapped[date | None] = mapped_column(SafeDate(), nullable=True)
    responsible_party: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Soft links to a punch-list item and a non-conformance report (no FK).
    punchlist_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    ncr_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # Photo evidence: one dict per photo, each the gallery photo id plus its
    # evidence record (hash, capture location with accuracy, time, orientation).
    photos: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    # WGS84 map pin; absent means "no pin", not (0, 0).
    geo_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    geo_lon: Mapped[float | None] = mapped_column(Float, nullable=True)

    warranty: Mapped["DlpWarranty"] = relationship(
        "app.modules.defects_liability.models.DlpWarranty",
        back_populates="defects",
    )

    def __repr__(self) -> str:
        return f"<DlpDefect {self.reference!r} ({self.status}) warranty={self.warranty_id}>"
