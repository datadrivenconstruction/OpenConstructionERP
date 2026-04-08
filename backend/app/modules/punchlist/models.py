"""Punch List ORM models.

Tables:
    oe_punchlist_item — punch list items tracking construction deficiencies
"""

import uuid

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class PunchItem(Base):
    """Punch list entry tracking a construction deficiency or quality issue."""

    __tablename__ = "oe_punchlist_item"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    location_x: Mapped[float | None] = mapped_column(Float, nullable=True)
    location_y: Mapped[float | None] = mapped_column(Float, nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="medium")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open", index=True)
    assigned_to: Mapped[str | None] = mapped_column(String(36), nullable=True)
    due_date: Mapped[str | None] = mapped_column(DateTime(timezone=True), nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    trade: Mapped[str | None] = mapped_column(String(100), nullable=True)
    photos: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<PunchItem {self.title[:40]} ({self.status}/{self.priority})>"
