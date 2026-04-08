"""Tasks ORM models.

Tables:
    oe_tasks_task — project tasks with checklists, assignments, and status tracking
"""

import uuid

from sqlalchemy import JSON, Boolean, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class Task(Base):
    """A project task with checklist, assignment, and due date tracking."""

    __tablename__ = "oe_tasks_task"
    __table_args__ = (
        Index("ix_task_project_status", "project_id", "status"),
        Index("ix_task_responsible_status", "responsible_id", "status"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Checklist: [{id, text, completed}]
    checklist: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )

    responsible_id: Mapped[str | None] = mapped_column(GUID(), nullable=True, index=True)

    # Persons involved: array of UUID strings
    persons_involved: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )

    due_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    milestone_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    meeting_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft", index=True)
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="normal")
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_private: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<Task {self.title[:40]} ({self.task_type}/{self.status})>"
