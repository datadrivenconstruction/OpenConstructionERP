"""Meetings ORM models.

Tables:
    oe_meetings_meeting — project meetings with agendas, attendees, and action items
"""

import uuid

from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class Meeting(Base):
    """A project meeting with agenda, attendees, and action items."""

    __tablename__ = "oe_meetings_meeting"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    meeting_number: Mapped[str] = mapped_column(String(20), nullable=False)
    meeting_type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    meeting_date: Mapped[str] = mapped_column(String(20), nullable=False)
    location: Mapped[str | None] = mapped_column(String(500), nullable=True)
    chairperson_id: Mapped[str | None] = mapped_column(GUID(), nullable=True)

    # Attendees: [{user_id, name, company, status: present/absent/excused}]
    attendees: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )

    # Agenda items: [{number, topic, presenter, entity_type, entity_id, notes}]
    agenda_items: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )

    # Action items: [{description, owner_id, due_date, status: open/completed/cancelled}]
    action_items: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )

    minutes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft", index=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<Meeting {self.meeting_number} ({self.meeting_type}/{self.status})>"
