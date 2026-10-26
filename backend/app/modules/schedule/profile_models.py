# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Scheduling profiles: the CPM settings a project schedules with.

One table, ``oe_schedule_scheduling_profile``. A profile belongs to a project;
at most one per project is its default. A schedule names the profile it uses
in ``Schedule.metadata_["scheduling_profile_id"]`` and falls back to the
project default, then to the built-in settings (see
:mod:`app.modules.schedule.profile_service`). Imported from ``models.py`` so
the table registers on ``Base.metadata``.
"""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class SchedulingProfile(Base):
    """A named set of CPM options (see :class:`app.core.cpm_profile.SchedulingOptions`)."""

    __tablename__ = "oe_schedule_scheduling_profile"
    __table_args__ = (Index("ix_sched_profile_project_name", "project_id", "name"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    progress_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, default="retained_logic", server_default="retained_logic"
    )
    lag_calendar: Mapped[str] = mapped_column(String(20), nullable=False, default="elapsed", server_default="elapsed")
    open_ends: Mapped[str] = mapped_column(
        String(20), nullable=False, default="project_finish", server_default="project_finish"
    )
    critical_rule: Mapped[str] = mapped_column(
        String(20), nullable=False, default="total_float", server_default="total_float"
    )
    critical_float_threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return f"<SchedulingProfile {self.name!r} {self.progress_mode}/{self.critical_rule}>"
