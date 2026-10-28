# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Voice-capture API routes (mounted at /api/v1/voice).

Endpoints:
    GET  /targets   - list the supported target types (diary_note, defect, task)
    POST /draft     - turn a recording OR a transcript + a target type into a
                      structured DRAFT the user reviews and confirms

The module is stateless - it never writes a row. The draft it returns is saved
(only after human review) through the target feature's own create endpoint, so
the "AI suggests, human confirms" boundary lives in the target UI. Authorization
is project-scoped: ``/draft`` runs verify_project_access against the project the
draft is for before doing any work, matching the phone-log and value modules.
"""

import logging
import uuid

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status

from app.core.rate_limiter import upload_limiter
from app.dependencies import CurrentUserId, SessionDep, verify_project_access
from app.modules.phonelog import transcription as phonelog_transcription
from app.modules.voice import service, structuring
from app.modules.voice.schemas import TranscriptionInfo, VoiceDraftResponse

router = APIRouter(tags=["voice"])
logger = logging.getLogger(__name__)


@router.get("/targets", response_model=list[str])
async def list_targets() -> list[str]:
    """List the target types the voice capture can structure a note into."""
    return list(structuring.target_types())


@router.post("/draft", response_model=VoiceDraftResponse)
async def create_voice_draft(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    target_type: str = Query(..., description="One of: diary_note, defect, task"),
    target_language: str | None = Query(
        default=None,
        description="UI locale code for the working language the draft is written in.",
    ),
    transcript: str = Form(default="", description="Typed/edited note when no recording is uploaded."),
    file: UploadFile | None = File(
        default=None,
        description="Optional audio or video recording of the spoken note.",
    ),
) -> VoiceDraftResponse:
    """Turn a recording or a transcript into a structured draft for review.

    Provide either an audio/video recording (transcribed first) or a ``transcript``
    text field; with a target type the server refines/translates the note and
    extracts the target's fields into a draft. Nothing is saved - the draft is
    returned for the user to review, edit, and confirm through the target
    feature's own create action. Degrades gracefully: without a transcription
    provider an uploaded recording yields no transcript (use the typed path), and
    without an LLM provider the draft is built by a deterministic heuristic.
    """
    await verify_project_access(project_id, user_id, session)

    if structuring.target_spec(target_type) is None:
        allowed = ", ".join(structuring.target_types())
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown target type '{target_type}'. Expected one of: {allowed}.",
        )

    text = (transcript or "").strip()
    transcription_info = TranscriptionInfo()

    if file is not None:
        allowed, _retry = upload_limiter.is_allowed(str(user_id))
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many uploads. Please wait a moment and try again.",
                headers={"Retry-After": "60"},
            )

        filename = file.filename or "recording"
        # Read at most one byte past the cap so an oversized file is rejected
        # without buffering the whole body into memory (mirrors phonelog).
        content = await file.read(phonelog_transcription.MAX_UPLOAD_BYTES + 1)
        problem = phonelog_transcription.check_audio_upload(filename, len(content))
        if problem is not None:
            raise HTTPException(status_code=problem[0], detail=problem[1])

        result = await service.transcribe(session, content, filename, str(user_id) if user_id else None)
        transcription_info = TranscriptionInfo(
            available=result.available,
            model=phonelog_transcription.TRANSCRIBE_MODEL if result.available else None,
            language=result.language,
            error=result.error,
        )
        # A successful transcript wins; if transcription was unavailable, fall
        # back to any transcript the caller also sent (a hybrid record+type flow).
        if result.text:
            text = result.text

    if not text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=("Nothing to structure. Upload a recording that can be transcribed, or type the note text."),
        )

    draft = await service.build_draft(
        session,
        target_type=target_type,
        text=text,
        target_language=target_language,
        user_id=str(user_id) if user_id else None,
        transcription_language=transcription_info.language,
    )
    return VoiceDraftResponse.from_draft(
        draft,
        transcript=text,
        target_language=target_language,
        transcription=transcription_info,
    )
