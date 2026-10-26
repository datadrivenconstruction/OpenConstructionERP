# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Schemas for minutes from audio: capabilities, glossary, recordings, proposals."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

_KIND_PATTERN = r"^(person|company|abbreviation|term|boq|place)$"


class SpeechCapabilities(BaseModel):
    """What this server can do with a recording, so the UI offers the right path."""

    server_transcription: bool
    provider: str | None = None
    llm_available: bool
    max_upload_mb: int
    accepted_formats: list[str]
    default_retention_days: int
    max_retention_days: int


class GlossaryTermCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    term: str = Field(..., min_length=2, max_length=120)
    kind: str = Field(default="term", pattern=_KIND_PATTERN)
    expansion: str | None = Field(default=None, max_length=500)
    aliases: list[str] = Field(default_factory=list, max_length=20)


class GlossaryTermUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    term: str | None = Field(default=None, min_length=2, max_length=120)
    kind: str | None = Field(default=None, pattern=_KIND_PATTERN)
    expansion: str | None = Field(default=None, max_length=500)
    aliases: list[str] | None = Field(default=None, max_length=20)


class GlossaryTermResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    term: str
    kind: str
    expansion: str | None = None
    aliases: list[str] = Field(default_factory=list)
    source: str
    contact_id: str | None = None
    created_at: datetime


class GlossarySeedResponse(BaseModel):
    added: int
    by_source: dict[str, int]
    terms: list[GlossaryTermResponse]


class SpeakerInfo(BaseModel):
    name: str = Field(default="", max_length=200)
    contact_id: str | None = Field(default=None, max_length=36)


class TranscriptSegment(BaseModel):
    start: float | None = Field(default=None, ge=0)
    end: float | None = Field(default=None, ge=0)
    text: str = Field(..., min_length=1, max_length=4000)
    speaker: str = Field(default="", max_length=100)


class RecordingUpdate(BaseModel):
    """Human edits to a transcript: text, segments, speaker names, language."""

    model_config = ConfigDict(str_strip_whitespace=True)

    transcript: str | None = Field(default=None, max_length=400_000)
    segments: list[TranscriptSegment] | None = Field(default=None, max_length=5000)
    speakers: dict[str, SpeakerInfo] | None = None
    language: str | None = Field(default=None, max_length=10)


class RecordingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    meeting_id: uuid.UUID
    source: str
    status: str
    has_audio: bool
    audio_filename: str | None = None
    audio_size_bytes: int | None = None
    duration_seconds: int | None = None
    audio_expires_at: datetime | None = None
    audio_deleted_at: datetime | None = None
    delete_audio_after_transcription: bool
    consent_confirmed_at: datetime | None = None
    language: str | None = None
    transcript: str
    segments: list[dict[str, Any]] = Field(default_factory=list)
    speakers: dict[str, Any] = Field(default_factory=dict)
    provider: str | None = None
    transcription_error: str | None = None
    proposals: dict[str, Any] = Field(default_factory=dict)
    glossary_replacements: int = 0
    created_at: datetime


class ProposalEdit(BaseModel):
    """A reviewer's verdict on one proposal, with optional edits."""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: str = Field(..., min_length=1, max_length=20)
    decision: str = Field(..., pattern=r"^(confirm|reject)$")
    text: str | None = Field(default=None, max_length=6000)
    owner_name: str | None = Field(default=None, max_length=200)
    owner_contact_id: str | None = Field(default=None, max_length=36)
    due_date: str | None = Field(default=None, max_length=20)
    linked_entity: dict[str, Any] | None = None
    heard: str | None = Field(default=None, max_length=200)
    term: str | None = Field(default=None, max_length=200)


class ProposalReviewRequest(BaseModel):
    items: list[ProposalEdit] = Field(..., min_length=1, max_length=200)
    #: Also open a task in the Tasks module for every confirmed action.
    create_tasks: bool = True


class ProposalReviewResponse(BaseModel):
    recording: RecordingResponse
    confirmed: int
    rejected: int
    actions_created: list[str] = Field(default_factory=list)
    tasks_created: list[str] = Field(default_factory=list)
    errors: list[dict[str, str]] = Field(default_factory=list)


class MeetingValidationResult(BaseModel):
    """One rule outcome of a meeting's validation run."""

    rule_id: str
    severity: str
    passed: bool
    message: str
    element_ref: str | None = None


class MeetingValidationResponse(BaseModel):
    """Traffic light for one meeting: actions, minutes readiness, recordings."""

    status: str
    score: float | None = None
    errors: int
    warnings: int
    results: list[MeetingValidationResult] = Field(default_factory=list)
