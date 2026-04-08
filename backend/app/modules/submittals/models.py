"""Submittals ORM models.

Tables:
    oe_submittals_submittal — construction submittals with review/approval workflow
"""

import uuid

from sqlalchemy import JSON, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class Submittal(Base):
    """A construction submittal with multi-stage review and approval workflow."""

    __tablename__ = "oe_submittals_submittal"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    submittal_number: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    spec_section: Mapped[str | None] = mapped_column(String(100), nullable=True)
    submittal_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft", index=True)
    ball_in_court: Mapped[str | None] = mapped_column(GUID(), nullable=True)
    current_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    submitted_by_org: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reviewer_id: Mapped[str | None] = mapped_column(GUID(), nullable=True)
    approver_id: Mapped[str | None] = mapped_column(GUID(), nullable=True)
    date_submitted: Mapped[str | None] = mapped_column(String(20), nullable=True)
    date_required: Mapped[str | None] = mapped_column(String(20), nullable=True)
    date_returned: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Linked BOQ item IDs: array of UUID strings
    linked_boq_item_ids: Mapped[list] = mapped_column(  # type: ignore[assignment]
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
        return f"<Submittal {self.submittal_number} — {self.title[:40]} ({self.status})>"
