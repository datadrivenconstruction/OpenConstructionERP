"""RFI ORM models.

Tables:
    oe_rfi_rfi — requests for information with response tracking and impact assessment
"""

import uuid

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class RFI(Base):
    """A Request for Information with response tracking and impact assessment."""

    __tablename__ = "oe_rfi_rfi"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rfi_number: Mapped[str] = mapped_column(String(20), nullable=False)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    raised_by: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    assigned_to: Mapped[str | None] = mapped_column(GUID(), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft", index=True)
    ball_in_court: Mapped[str | None] = mapped_column(GUID(), nullable=True)
    official_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    responded_by: Mapped[str | None] = mapped_column(GUID(), nullable=True)
    responded_at: Mapped[str | None] = mapped_column(String(20), nullable=True)
    cost_impact: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cost_impact_value: Mapped[str | None] = mapped_column(String(50), nullable=True)
    schedule_impact: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    schedule_impact_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    date_required: Mapped[str | None] = mapped_column(String(20), nullable=True)
    response_due_date: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Linked drawing IDs: array of document/drawing UUID strings
    linked_drawing_ids: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )

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
        return f"<RFI {self.rfi_number} — {self.subject[:40]} ({self.status})>"
