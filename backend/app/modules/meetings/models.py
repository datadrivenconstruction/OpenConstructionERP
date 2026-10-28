# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Meetings ORM models.

Tables:
    oe_meetings_meeting      - project meetings with agendas, attendees, and action items
    oe_meetings_attendance   - per-meeting attendance check-in records with optional signature
    oe_meetings_action_item  - tracked action items that carry forward across a recurring series
    oe_meetings_minutes      - human-confirmed draft minutes generated from a meeting
    oe_meetings_recording    - a meeting's audio recording, its transcript and the AI proposals
    oe_meetings_glossary_term - project vocabulary passed to transcription and the minutes AI
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base


class Meeting(Base):
    """A project meeting with agenda, attendees, and action items."""

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
    meeting_date: Mapped[str] = mapped_column(String(40), nullable=False)
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

    # ── Construction-suite style recurring series ───────────────────────
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

    # Attendance records - see MeetingAttendance.
    attendance_records: Mapped[list["MeetingAttendance"]] = relationship(
        "MeetingAttendance",
        back_populates="meeting",
        cascade="all, delete-orphan",
        lazy="select",
    )

    def __repr__(self) -> str:
        return f"<Meeting {self.meeting_number} ({self.meeting_type}/{self.status})>"


class MeetingAttendance(Base):
    """Per-meeting attendance check-in record.

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


class MeetingActionItem(Base):
    """A tracked action item that can carry forward across a recurring series.

    Distinct from the free-form ``Meeting.action_items`` JSON array: this is a
    first-class, individually-addressable row so one action can be tracked
    across every meeting in a series until it is closed. ``origin_meeting_id``
    is the meeting where the action was raised; ``series_id`` is copied from
    that meeting (``NULL`` for a one-off meeting). Open actions from an earlier
    meeting in the same series surface in later meetings as "brought forward"
    until their status becomes ``done`` or ``cancelled`` - closing the single
    row closes the action for the whole series.
    """

    __tablename__ = "oe_meetings_action_item"
    __table_args__ = (
        Index(
            "ix_oe_meetings_action_item_project_series",
            "project_id",
            "series_id",
        ),
        Index(
            "ix_oe_meetings_action_item_origin_meeting_id",
            "origin_meeting_id",
        ),
        Index(
            "ix_oe_meetings_action_item_status",
            "status",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Copied from the origin meeting: the master id for a series, NULL for a
    # one-off meeting. A single WHERE series_id = ? scoops the whole register.
    series_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    origin_meeting_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey(
            "oe_meetings_meeting.id",
            name="fk_oe_meetings_action_item_origin_meeting_id_meeting",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    description: Mapped[str] = mapped_column(Text, nullable=False)
    owner_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    owner_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # ISO 8601 date (YYYY-MM-DD). Kept as a plain string to match the rest of
    # the meetings module (Meeting.meeting_date, action_items JSON).
    due_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # open | in_progress | done | cancelled
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="open",
        server_default="open",
    )

    # The later meeting in which the action was closed (soft reference, no FK
    # so deleting that meeting never cascades away the historical action).
    closed_in_meeting_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
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
        return f"<MeetingActionItem {self.status} owner={self.owner_name or self.owner_id} due={self.due_date}>"


class MeetingMinutes(Base):
    """A human-confirmed draft minutes document generated from a meeting.

    One row per meeting (``meeting_id`` is unique). ``content`` is a structured
    JSON document (attendees present/absent, per-agenda discussion and
    decision, action items, next meeting date, summary) built by the pure
    :mod:`app.modules.meetings.logic` helpers. The minutes start life as a
    ``draft`` that a human reviews and edits; issuing flips ``status`` to
    ``issued`` and distribution notifies the attendees. Nothing is auto-issued
    (AI-augmented, human-confirmed).
    """

    __tablename__ = "oe_meetings_minutes"
    __table_args__ = (
        UniqueConstraint(
            "meeting_id",
            name="uq_oe_meetings_minutes_meeting_id",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey(
            "oe_meetings_meeting.id",
            name="fk_oe_meetings_minutes_meeting_id_meeting",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    # draft | issued
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="draft",
        server_default="draft",
    )
    content: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    next_meeting_date: Mapped[str | None] = mapped_column(String(40), nullable=True)

    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    issued_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    distributed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # List of recipient identifiers (user ids or names) the minutes were sent to.
    distributed_to: Mapped[list] = mapped_column(  # type: ignore[assignment]
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
        return f"<MeetingMinutes meeting={self.meeting_id} status={self.status}>"


class MeetingRecording(Base):
    """An audio recording (or a typed / browser-dictated transcript) of a meeting.

    The audio itself is optional and short-lived: it lives in the storage
    backend under ``audio_storage_key`` until the retention window passes, the
    user deletes it, or transcription finishes with ``delete_audio_after_transcription``
    set. The transcript, the editable speaker labels and the AI proposals stay.
    Recording audio requires ``consent_confirmed_at``: the person recording
    confirmed every participant was told and agreed.
    """

    __tablename__ = "oe_meetings_recording"
    __table_args__ = (
        Index("ix_oe_meetings_recording_meeting_id", "meeting_id"),
        Index("ix_oe_meetings_recording_audio_expiry", "audio_expires_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey(
            "oe_meetings_meeting.id",
            name="fk_oe_meetings_recording_meeting_id_meeting",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    # upload | browser_record | browser_speech | manual
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="upload")
    # pending | transcribed | awaiting_transcript | failed
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")

    audio_storage_key: Mapped[str] = mapped_column(String(500), nullable=False, default="", server_default="")
    audio_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    audio_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    audio_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    audio_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delete_audio_after_transcription: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )

    consent_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consent_confirmed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    # ISO 639-1 code of the spoken language (detected or chosen).
    language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    transcript: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    # [{start, end, text, speaker}] - speaker is a label the user can rename.
    segments: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    # {label: {name, contact_id}} - who each speaker label really is.
    speakers: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    transcription_error: Mapped[str | None] = mapped_column(String(300), nullable=True)

    # {generated_at, ai_generated, language, items: [{id, kind, text, confidence, status, ...}]}
    proposals: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )

    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )

    def __repr__(self) -> str:
        return f"<MeetingRecording meeting={self.meeting_id} status={self.status}>"


class MeetingGlossaryTerm(Base):
    """One entry of a project's meeting vocabulary.

    Names, companies, abbreviations and trade terms that a speech model gets
    wrong. Terms go to the transcription provider as hints and to the minutes
    AI as the correct spelling; ``aliases`` are known mis-hearings that are
    offered as corrections. Seeded entries keep their ``source`` so a re-seed
    refreshes them without touching terms a person typed.
    """

    __tablename__ = "oe_meetings_glossary_term"
    __table_args__ = (UniqueConstraint("project_id", "term_key", name="uq_oe_meetings_glossary_term_project_key"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    term: Mapped[str] = mapped_column(String(200), nullable=False)
    # Case- and whitespace-folded term, the uniqueness key.
    term_key: Mapped[str] = mapped_column(String(200), nullable=False)
    # person | company | abbreviation | term | boq | place
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="term")
    expansion: Mapped[str | None] = mapped_column(String(500), nullable=True)
    aliases: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    # manual | contacts | attendees | stakeholders | boq | project
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    contact_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    def __repr__(self) -> str:
        return f"<MeetingGlossaryTerm {self.term!r} ({self.kind})>"
