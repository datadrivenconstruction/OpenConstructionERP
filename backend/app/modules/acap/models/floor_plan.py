"""Floor-plan versioned record — ORM model for persisted generated layouts.

One row per version per project.  ``version`` auto-increments within a project.
"""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy import select as sa_select
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class FloorPlanRecord(Base):
    """A single generated floor-plan version tied to a project."""

    __tablename__ = "oe_acap_floor_plan"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "version",
            name="uq_acap_floorplan_project_version",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    requirement_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    jumlah_lantai: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="generated")
    plan_json: Mapped[dict] = mapped_column(JSON, nullable=False)

    def __repr__(self) -> str:
        return f"<FloorPlanRecord project={self.project_id} v{self.version} [{self.status}]>"


async def next_version(session, project_id: uuid.UUID) -> int:
    """Return the next version number for *project_id* (max+1, default 1)."""
    from sqlalchemy import func

    stmt = (
        sa_select(func.coalesce(func.max(FloorPlanRecord.version) + 1, 1))
        .where(FloorPlanRecord.project_id == project_id)
    )
    result = await session.execute(stmt)
    return result.scalar_one()
