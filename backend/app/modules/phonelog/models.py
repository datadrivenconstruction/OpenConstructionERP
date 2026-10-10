# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Phone-log ORM model.

Tables:
    oe_phonelog_phone_log - a captured phone call, voice note, or verbal
    instruction, normalized into a dispute-ready record (canonical direction
    and channel, a clean party list, a reliable duration, a short summary, and
    the instruction-bearing sentences pulled out of the transcript) and tied to
    a project. The raw transcript is kept verbatim as the underlying evidence,
    and for a record ingested from a recording the audio itself is stored too
    (see ``audio_storage_key`` for where it goes and how long it lives).
"""

import uuid

from sqlalchemy import JSON, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class PhoneLog(Base):
    """A normalized capture of a verbal instruction (phone call, voice note, or chat)."""

    __tablename__ = "oe_phonelog_phone_log"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Canonical direction (inbound / outbound / internal / unknown) and channel
    # (phone / voice_note / chat / other), both produced by phonelog.normalize.
    direction: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unknown", server_default="unknown", index=True
    )
    channel: Mapped[str] = mapped_column(
        String(20), nullable=False, default="phone", server_default="phone", index=True
    )
    # The people on the call, cleaned and de-duplicated. JSON array of strings.
    parties: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    # When the call happened, kept as the caller-supplied ISO-8601 string (the
    # capture's start). Preserved as text so a record never loses the moment a
    # verbal instruction was given, which is what disputes turn on.
    occurred_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # The spoken content verbatim (the evidence) and a short glanceable summary.
    transcript: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    summary: Mapped[str] = mapped_column(String(500), nullable=False, default="", server_default="")
    # Instruction-bearing sentences extracted from the transcript. JSON array.
    instructions: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    word_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # Storage key of the recording this row was built from. Written by
    # service.transcribe_recording at upload, before transcription runs, as
    # "phonelog/<project_id>/<uuid>[.<ext>]", and populated whether or not
    # transcription succeeds: a row with an empty transcript still has audio
    # behind it. Empty only for rows captured by typing a transcript in.
    # Recordings expire: retention.prune_expired_recordings deletes the object
    # once it is older than OE_PHONELOG_AUDIO_RETENTION_DAYS (default 90, 0 =
    # keep) and clears this key, leaving the row and transcript in place.
    # service.delete_phone_log also removes the object with the record. That delete is best-effort
    # and swallows its failure at debug level, so an object can outlive its row
    # unnoticed. Archiving a project does not reach either: PhoneLog is not in
    # the cascade list in projects.service.delete_project.
    audio_storage_key: Mapped[str] = mapped_column(String(512), nullable=False, default="", server_default="")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="logged", server_default="logged", index=True
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
        return f"<PhoneLog {self.id} ({self.direction}/{self.channel}) project={self.project_id}>"
