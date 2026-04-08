"""Schedule ORM models.

Tables:
    oe_schedule_schedule      — project schedule (container for activities)
    oe_schedule_activity      — individual activities / tasks in the schedule (WBS hierarchy)
    oe_schedule_work_order    — work orders linked to activities
    oe_schedule_relationship  — CPM dependency relationships between activities
    oe_schedule_baseline      — schedule baseline snapshots for planned-vs-actual comparison
    oe_schedule_progress      — progress update records for activities
"""

import uuid

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base


class Schedule(Base):
    """Project schedule — groups activities for 4D planning."""

    __tablename__ = "oe_schedule_schedule"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    schedule_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="master", server_default="master"
    )  # master / baseline / revision / what_if
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    start_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    end_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft")
    data_date: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # current data/status date
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), nullable=True
    )
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # Relationships
    activities: Mapped[list["Activity"]] = relationship(
        back_populates="schedule",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="Activity.sort_order",
    )

    def __repr__(self) -> str:
        return f"<Schedule {self.name} ({self.status})>"


class Activity(Base):
    """Individual activity / task in a schedule with WBS hierarchy."""

    __tablename__ = "oe_schedule_activity"

    schedule_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_schedule_schedule.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_schedule_activity.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    wbs_code: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    start_date: Mapped[str] = mapped_column(String(20), nullable=False)
    end_date: Mapped[str] = mapped_column(String(20), nullable=False)
    duration_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress_pct: Mapped[str] = mapped_column(String(10), nullable=False, default="0")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="not_started", index=True)
    activity_type: Mapped[str] = mapped_column(String(50), nullable=False, default="task")
    dependencies: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    resources: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    boq_position_ids: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    color: Mapped[str] = mapped_column(String(20), nullable=False, default="#0071e3")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # ── CPM result columns (Phase 13) ────────────────────────────────────
    early_start: Mapped[str | None] = mapped_column(String(20), nullable=True)
    early_finish: Mapped[str | None] = mapped_column(String(20), nullable=True)
    late_start: Mapped[str | None] = mapped_column(String(20), nullable=True)
    late_finish: Mapped[str | None] = mapped_column(String(20), nullable=True)
    total_float: Mapped[int | None] = mapped_column(Integer, nullable=True)
    free_float: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_critical: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )

    # ── Constraints ──────────────────────────────────────────────────────────
    constraint_type: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # as_soon_as_possible / as_late_as_possible / must_start_on / must_finish_on
    #   start_no_earlier / start_no_later / finish_no_earlier / finish_no_later
    constraint_date: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # ISO date

    # Auto-generated activity code
    activity_code: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # ACT-001, ACT-002

    # BIM integration
    bim_element_ids: Mapped[dict | None] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=True
    )  # list of element IDs for 4D

    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # Relationships
    schedule: Mapped[Schedule] = relationship(back_populates="activities")
    children: Mapped[list["Activity"]] = relationship(
        back_populates="parent",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    parent: Mapped["Activity | None"] = relationship(
        back_populates="children",
        remote_side="Activity.id",
        lazy="selectin",
    )
    work_orders: Mapped[list["WorkOrder"]] = relationship(
        back_populates="activity",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Activity {self.wbs_code} — {self.name[:40]}>"


class WorkOrder(Base):
    """Work order linked to a schedule activity."""

    __tablename__ = "oe_schedule_work_order"

    activity_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_schedule_activity.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    assembly_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        nullable=True,
    )
    boq_position_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        nullable=True,
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    assigned_to: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    planned_start: Mapped[str | None] = mapped_column(String(20), nullable=True)
    planned_end: Mapped[str | None] = mapped_column(String(20), nullable=True)
    actual_start: Mapped[str | None] = mapped_column(String(20), nullable=True)
    actual_end: Mapped[str | None] = mapped_column(String(20), nullable=True)
    planned_cost: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    actual_cost: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="planned")
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # Relationships
    activity: Mapped[Activity] = relationship(back_populates="work_orders")

    def __repr__(self) -> str:
        return f"<WorkOrder {self.code} ({self.status})>"


class ScheduleRelationship(Base):
    """Explicit CPM dependency relationship between two activities.

    Stores predecessor/successor links with relationship type (FS, FF, SS, SF)
    and optional lag in days.  Used by the CPM engine for forward/backward pass
    calculations.
    """

    __tablename__ = "oe_schedule_relationship"
    __table_args__ = (
        UniqueConstraint("predecessor_id", "successor_id", name="uq_schedule_rel_pred_succ"),
    )

    schedule_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_schedule_schedule.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    predecessor_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_schedule_activity.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    successor_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_schedule_activity.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    relationship_type: Mapped[str] = mapped_column(
        String(10), nullable=False, default="FS"
    )
    lag_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return (
            f"<ScheduleRelationship {self.predecessor_id}->{self.successor_id} "
            f"({self.relationship_type} lag={self.lag_days})>"
        )


class ScheduleBaseline(Base):
    """Snapshot of all schedule activities at a point in time.

    Baselines allow comparison between planned vs. actual progress.
    Each schedule/project may have multiple baselines (e.g. original,
    revision 1, revision 2).  Only one baseline is active at a time.
    """

    __tablename__ = "oe_schedule_baseline"

    schedule_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        nullable=True,
        index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    baseline_date: Mapped[str] = mapped_column(String(20), nullable=False)
    snapshot_data: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        nullable=True,
    )
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<ScheduleBaseline {self.name} ({self.baseline_date})>"


class ProgressUpdate(Base):
    """Progress update record for a schedule activity.

    Tracks actual progress, start/finish dates, remaining duration,
    and approval workflow (draft -> submitted -> approved).
    """

    __tablename__ = "oe_schedule_progress"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        nullable=False,
        index=True,
    )
    activity_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        nullable=True,
    )
    update_date: Mapped[str] = mapped_column(String(20), nullable=False)
    progress_pct: Mapped[str | None] = mapped_column(String(10), nullable=True)
    actual_start: Mapped[str | None] = mapped_column(String(20), nullable=True)
    actual_finish: Mapped[str | None] = mapped_column(String(20), nullable=True)
    remaining_duration: Mapped[str | None] = mapped_column(String(10), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft")
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        nullable=True,
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        nullable=True,
    )
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<ProgressUpdate {self.update_date} ({self.status})>"
