# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Phone-log Pydantic schemas - request/response models.

The create schema accepts a raw, free-form capture: the caller posts whatever it
has (a party line, an informal direction hint, a couple of timestamps or a
duration, the transcript, an optional summary) and the server normalizes it via
app.modules.phonelog.normalize before storing. The response carries the cleaned,
canonical record.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PhoneLogCreate(BaseModel):
    """Capture a phone call / voice note / verbal instruction for a project."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    # Free text ("John Doe (us) -> Acme site office") or an explicit list of
    # names. Normalized into a clean, de-duplicated party list server-side.
    raw_parties: str | list[str] = Field(default="")
    # Informal hints; mapped onto canonical values by the normalizer. A blank
    # channel is treated as a phone call (the most common verbal channel).
    direction: str = Field(default="", max_length=40)
    channel: str = Field(default="", max_length=40)
    # ISO-8601 timestamps used to derive the duration when no explicit
    # duration is given. started_at is also kept as the record's occurred_at.
    started_at: str | None = Field(default=None, max_length=40)
    ended_at: str | None = Field(default=None, max_length=40)
    duration_seconds: int | None = Field(default=None, ge=0)
    transcript: str = Field(default="", max_length=20000)
    summary: str = Field(default="", max_length=2000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PhoneLogFinalize(BaseModel):
    """Confirm a recording draft into a normal, logged phone-log record.

    The recording ingestion path (`POST /transcribe`) stores the recording and
    returns a DRAFT the user reviews and edits. This schema carries the reviewed,
    human-confirmed values back: parties, direction, timing, the transcript, and
    the edited structured protocol. Parties / direction / channel are still
    normalized server-side; the transcript, the reviewed instructions, and the
    protocol are stored as confirmed. Nothing here is applied until the user
    submits it, which is the "AI suggests, human confirms" boundary.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    direction: str = Field(default="", max_length=40)
    channel: str = Field(default="voice_note", max_length=40)
    raw_parties: str | list[str] = Field(default="")
    occurred_at: str | None = Field(default=None, max_length=40)
    duration_seconds: int | None = Field(default=None, ge=0)
    # A transcribed recording can be long, so allow more than the manual-capture
    # path; it is stored verbatim in a Text column as the underlying evidence.
    transcript: str = Field(default="", max_length=200000)
    summary: str = Field(default="", max_length=2000)
    # Human-reviewed instruction sentences. When empty, the server re-derives
    # them from the transcript so a confirm never silently drops instructions.
    instructions: list[str] = Field(default_factory=list)
    # The edited structured protocol (participants, summary, decisions, action
    # items, confidence). Stored under metadata_["protocol"].
    protocol: dict[str, Any] = Field(default_factory=dict)


class PhoneLogResponse(BaseModel):
    """A normalized phone-log record returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    direction: str
    channel: str
    parties: list[str] = Field(default_factory=list)
    occurred_at: str | None = None
    duration_seconds: int | None = None
    transcript: str = ""
    summary: str = ""
    instructions: list[str] = Field(default_factory=list)
    word_count: int = 0
    audio_storage_key: str = ""
    status: str = "logged"
    created_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime
