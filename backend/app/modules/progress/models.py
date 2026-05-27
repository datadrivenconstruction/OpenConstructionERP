# OpenConstructionERP — DataDrivenConstruction (DDC)
# DDC-CWICR-OE-2026
"""Progress tracking ORM models.

Tables:
    oe_progress_entry  — append-only percent-complete observations per BOQ position
    oe_progress_plan   — planned S-curve data points per project / BOQ
"""

import uuid

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class ProgressEntry(Base):
    """Append-only field measurement of percent-complete for a BOQ position.

    Design rationale
    ─────────────────
    * ``percent_complete`` is stored as NUMERIC(6,3) so 0.000 – 100.000 never
      suffer floating-point rounding. A CHECK constraint enforces the range at
      the DB level (belt + braces alongside the Pydantic [0, 100] validator).
    * Entries are *append-only*: to correct a mistake, record a new entry.
      The service layer always queries the *latest* entry for a position when
      computing current progress.
    * ``geo_lat`` / ``geo_lon`` capture the worker's location at record-time
      (optional — phone may not provide GPS in all conditions).
    * ``rework_cost`` is stored as VARCHAR so money is never a float.
    """

    __tablename__ = "oe_progress_entry"
    __table_args__ = (
        CheckConstraint(
            "percent_complete >= 0 AND percent_complete <= 100",
            name="ck_progress_entry_pct_range",
        ),
        CheckConstraint(
            "geo_lat IS NULL OR (geo_lat >= -90 AND geo_lat <= 90)",
            name="ck_progress_entry_lat_range",
        ),
        CheckConstraint(
            "geo_lon IS NULL OR (geo_lon >= -180 AND geo_lon <= 180)",
            name="ck_progress_entry_lon_range",
        ),
        Index("ix_progress_entry_position_recorded", "boq_position_id", "recorded_at"),
        Index("ix_progress_entry_project_recorded", "project_id", "recorded_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Optional link to a BOQ position; NULL means a project-level entry
    boq_position_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_boq_position.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    # Period label, e.g. "2026-W21" or "2026-05". Free-form string so it
    # works with any schedule granularity (week, month, custom sprint).
    period_label: Mapped[str] = mapped_column(String(20), nullable=False)
    percent_complete: Mapped[float] = mapped_column(
        Numeric(6, 3),
        nullable=False,
        default=0,
        server_default="0",
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    recorded_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    recorded_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    # Geo pin from the field worker's device
    geo_lat: Mapped[float | None] = mapped_column(Numeric(10, 7), nullable=True)
    geo_lon: Mapped[float | None] = mapped_column(Numeric(10, 7), nullable=True)
    # Photo attachment paths (JSON array of strings)
    photos: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<ProgressEntry position={self.boq_position_id} period={self.period_label} pct={self.percent_complete}>"


class ProgressPlan(Base):
    """Planned S-curve data point for a project / BOQ.

    Each row is one (period_label, planned_cumulative_pct) entry that
    together with ``ProgressEntry`` rows lets the service compute the
    actual vs planned S-curve.
    """

    __tablename__ = "oe_progress_plan"
    __table_args__ = (
        CheckConstraint(
            "planned_pct >= 0 AND planned_pct <= 100",
            name="ck_progress_plan_pct_range",
        ),
        Index("ix_progress_plan_project_period", "project_id", "period_label"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    period_label: Mapped[str] = mapped_column(String(20), nullable=False)
    # Cumulative planned % at end of this period (0.000 – 100.000)
    planned_pct: Mapped[float] = mapped_column(
        Numeric(6, 3),
        nullable=False,
        default=0,
        server_default="0",
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<ProgressPlan project={self.project_id} period={self.period_label} planned={self.planned_pct}>"
