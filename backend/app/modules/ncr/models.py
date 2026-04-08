"""NCR ORM models.

Tables:
    oe_ncr_ncr — non-conformance reports with root cause analysis and corrective actions
"""

import uuid

from sqlalchemy import JSON, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class NCR(Base):
    """A Non-Conformance Report with root cause analysis and corrective/preventive actions."""

    __tablename__ = "oe_ncr_ncr"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ncr_number: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    ncr_type: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    root_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    root_cause_category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    corrective_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    preventive_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="identified", index=True)
    cost_impact: Mapped[str | None] = mapped_column(String(50), nullable=True)
    schedule_impact_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    location_description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    linked_inspection_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    change_order_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<NCR {self.ncr_number} — {self.title[:40]} ({self.status})>"
