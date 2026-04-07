"""Schedule ORM models.

Tables:
    oe_schedule_schedule      — project schedule (container for activities)
    oe_schedule_activity      — individual activities / tasks in the schedule (WBS hierarchy)
    oe_schedule_work_order    — work orders linked to activities
    oe_schedule_relationship  — CPM dependency relationships between activities
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
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    start_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    end_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft")
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
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="not_started")
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
