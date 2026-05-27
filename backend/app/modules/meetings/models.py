"""‌⁠‍Meetings ORM models.

Tables:
    oe_meetings_meeting     — project meetings with agendas, attendees, and action items
    oe_meetings_attendance  — per-meeting attendance check-in records with optional signature
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base


class Meeting(Base):
    """‌⁠‍A project meeting with agenda, attendees, and action items."""

    __tablename__ = "oe_meetings_meeting"
    __table_args__ = (
        Index(
            "ix_oe_meetings_meeting_project_type",
            "project_id",
            "meeting_type",
        ),
        Index(
            "ix_oe_meetings_meeting_series_id",
            "series_id",
        ),
    )

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

    # Linked documents (cross-module references to oe_documents_document)
    document_ids: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )

    # ── Newforma-style recurring series ─────────────────────────────────
    # series_id stamps both the master AND every materialised occurrence,
    # so a single WHERE series_id = ? scoops the entire series. For a
    # one-off meeting this stays NULL.
    series_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # RFC 5545 RRULE (FREQ=WEEKLY;BYDAY=MO;COUNT=12). Only set on master.
    recurrence_rule: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_series_master: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )

    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # Attendance records — see MeetingAttendance.
    attendance_records: Mapped[list["MeetingAttendance"]] = relationship(
        "MeetingAttendance",
        back_populates="meeting",
        cascade="all, delete-orphan",
        lazy="select",
    )

    def __repr__(self) -> str:
        return f"<Meeting {self.meeting_number} ({self.meeting_type}/{self.status})>"


class MeetingAttendance(Base):
    """‌⁠‍Per-meeting attendance check-in record.

    Distinct from the JSON ``Meeting.attendees`` array because check-in
    is a transactional event (timestamped) and may carry a signature
    image blob on disk.  Either ``user_id`` (system user) or
    ``external_name`` (walk-in, non-system) identifies the attendee.
    """

    __tablename__ = "oe_meetings_attendance"
    __table_args__ = (
        UniqueConstraint(
            "meeting_id",
            "user_id",
            name="uq_oe_meetings_attendance_meeting_user",
        ),
        Index(
            "ix_oe_meetings_attendance_meeting_id",
            "meeting_id",
        ),
    )

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey(
            "oe_meetings_meeting.id",
            name="fk_oe_meetings_attendance_meeting_id_meeting",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    external_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    checked_in_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    signature_image_path: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    meeting: Mapped[Meeting] = relationship(
        "Meeting",
        back_populates="attendance_records",
    )

    def __repr__(self) -> str:
        who = self.user_id or self.external_name or "?"
        when = self.checked_in_at.isoformat() if self.checked_in_at else "pending"
        return f"<MeetingAttendance meeting={self.meeting_id} who={who} {when}>"
