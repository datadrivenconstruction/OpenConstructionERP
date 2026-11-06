# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Voice-capture Pydantic schemas - request/response models (Pydantic v2).

The voice module is stateless: it turns a recording (or a transcript) plus a
target type into a structured DRAFT the caller reviews and then saves through the
target feature's own create endpoint. Nothing here is persisted, so there is only
a response model (plus a light transcription-info block) - no create/update
schema and no ORM model.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TranscriptionInfo(BaseModel):
    """How the recording was transcribed (mirrors phonelog's transcription block).

    ``available`` is False when no speech-to-text provider was configured or the
    call failed - in that case the raw/typed transcript path still works, so the
    feature stays usable. ``error`` carries a short, non-sensitive reason.
    """

    available: bool = False
    model: str | None = None
    language: str | None = None
    error: str | None = None


class VoiceDraftResponse(BaseModel):
    """A structured draft built from a spoken or typed note.

    ``fields`` is a flat map of the target's field names to cleaned string values
    (enum fields already clamped to the exact set the target schema accepts), so
    the frontend maps them straight onto the target feature's create payload.
    ``ai_generated`` is False on the graceful-degradation path (no/failed LLM),
    where the fields come from the deterministic heuristic and ``confidence`` is
    null. Nothing is saved until the user confirms.
    """

    model_config = ConfigDict(from_attributes=True)

    target_type: str
    fields: dict[str, str] = Field(default_factory=dict)
    # The transcript the draft was built from - returned so the UI can show it
    # for review and re-structure from an edited version without re-uploading.
    transcript: str = ""
    # The note rewritten as clean, translated prose (raw transcript when no LLM).
    refined_text: str = ""
    confidence: float | None = None
    ai_generated: bool = False
    detected_language: str | None = None
    target_language: str | None = None
    transcription: TranscriptionInfo = Field(default_factory=TranscriptionInfo)

    @classmethod
    def from_draft(
        cls,
        draft: dict[str, Any],
        *,
        transcript: str,
        target_language: str | None,
        transcription: TranscriptionInfo,
    ) -> VoiceDraftResponse:
        """Build the response from a ``structuring.assemble_draft`` dict."""
        return cls(
            target_type=str(draft.get("target_type", "")),
            fields={str(k): str(v) for k, v in (draft.get("fields") or {}).items()},
            transcript=transcript,
            refined_text=str(draft.get("refined_text", "")),
            confidence=draft.get("confidence"),
            ai_generated=bool(draft.get("ai_generated", False)),
            detected_language=draft.get("detected_language"),
            target_language=target_language,
            transcription=transcription,
        )


class VoiceCapabilities(BaseModel):
    """What the server can do for voice input, so the browser picks its engine.

    ``server_transcription`` is True when a speech-to-text provider is configured
    for this caller; the browser then may fall back to it where its own speech
    recognition is missing. Audio sent to it is transcribed and dropped.
    """

    server_transcription: bool = False
    provider: str | None = None
    max_upload_bytes: int = 0
    max_seconds: int = 0


class DictationResponse(BaseModel):
    """The text of one dictated message. Nothing is stored."""

    model_config = ConfigDict(extra="forbid")

    text: str = ""
    language: str | None = None
    available: bool = False
    error: str | None = Field(default=None, description="Short, non-sensitive reason when nothing came back.")
