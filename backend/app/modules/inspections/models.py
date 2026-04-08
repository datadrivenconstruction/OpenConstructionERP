"""Inspections ORM models.

Tables:
    oe_inspections_inspection — quality inspections with checklists and pass/fail results
"""

import uuid

from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class QualityInspection(Base):
    """A quality inspection record with checklist and pass/fail result."""

    __tablename__ = "oe_inspections_inspection"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    inspection_number: Mapped[str] = mapped_column(String(20), nullable=False)
    inspection_type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(String(500), nullable=True)
    wbs_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    inspector_id: Mapped[str | None] = mapped_column(GUID(), nullable=True)
    inspection_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="scheduled", index=True)
    result: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Checklist: [{id, category, question, response_type, response, notes, critical}]
    checklist_data: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )

    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<QualityInspection {self.inspection_number} ({self.inspection_type}/{self.status})>"
