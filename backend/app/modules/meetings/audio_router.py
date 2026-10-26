# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Minutes-from-audio routes, mounted under /api/v1/meetings.

GET    /speech/capabilities/               - what transcription / AI this server offers
GET    /minutes/pdf-languages/             - languages the minutes PDF prints in
GET    /glossary/?project_id=              - project meeting glossary
POST   /glossary/?project_id=              - add a term
POST   /glossary/seed/?project_id=         - add names and terms the project already knows
PATCH  /glossary/{term_id}                 - edit a term
DELETE /glossary/{term_id}                 - remove a term
GET    /{meeting_id}/recordings/           - recordings of a meeting
POST   /{meeting_id}/recordings/           - upload audio or a transcript (consent required)
PATCH  /recordings/{id}                    - edit transcript, segments, speaker names, language
POST   /recordings/{id}/transcribe/        - transcribe the stored audio again
POST   /recordings/{id}/propose/           - AI proposals: summary, decisions, actions, questions
POST   /recordings/{id}/review/            - confirm / reject proposals
GET    /recordings/{id}/audio              - play the stored audio
DELETE /recordings/{id}/audio              - delete the audio, keep the transcript
DELETE /recordings/{id}                    - delete the recording entirely
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import RedirectResponse, Response, StreamingResponse

from app.core.rate_limiter import upload_limiter
from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.meetings.audio_schemas import (
    GlossarySeedResponse,
    GlossaryTermCreate,
    GlossaryTermResponse,
    GlossaryTermUpdate,
    MeetingValidationResponse,
    MeetingValidationResult,
    ProposalReviewRequest,
    ProposalReviewResponse,
    RecordingResponse,
    RecordingUpdate,
    SpeechCapabilities,
)
from app.modules.meetings.audio_service import MeetingAudioService
from app.modules.meetings.models import MeetingRecording

router = APIRouter(tags=["meetings"])


def _svc(session: SessionDep) -> MeetingAudioService:
    return MeetingAudioService(session)


def _uid(user_id: Any) -> str | None:
    return str(user_id) if user_id else None


def recording_response(row: MeetingRecording) -> RecordingResponse:
    return RecordingResponse(
        id=row.id,
        project_id=row.project_id,
        meeting_id=row.meeting_id,
        source=row.source,
        status=row.status,
        has_audio=bool(row.audio_storage_key),
        audio_filename=row.audio_filename,
        audio_size_bytes=row.audio_size_bytes,
        duration_seconds=row.duration_seconds,
        audio_expires_at=row.audio_expires_at,
        audio_deleted_at=row.audio_deleted_at,
        delete_audio_after_transcription=row.delete_audio_after_transcription,
        consent_confirmed_at=row.consent_confirmed_at,
        language=row.language,
        transcript=row.transcript or "",
        segments=list(row.segments or []),
        speakers=dict(row.speakers or {}),
        provider=row.provider,
        transcription_error=row.transcription_error,
        proposals=dict(row.proposals or {}),
        glossary_replacements=int((row.metadata_ or {}).get("glossary_replacements") or 0),
        created_at=row.created_at,
    )


async def _meeting_for(session: SessionDep, meeting_id: uuid.UUID, user_id: Any) -> Any:
    from app.modules.meetings.service import MeetingService

    meeting = await MeetingService(session).get_meeting(meeting_id)
    await verify_project_access(meeting.project_id, str(user_id), session)
    return meeting


async def _recording_for(
    session: SessionDep, svc: MeetingAudioService, recording_id: uuid.UUID, user_id: Any
) -> tuple[MeetingRecording, Any]:
    row = await svc.get_recording(recording_id)
    meeting = await _meeting_for(session, row.meeting_id, user_id)
    return row, meeting


# ── Capabilities ─────────────────────────────────────────────────────────────


@router.get(
    "/speech/capabilities/",
    response_model=SpeechCapabilities,
    dependencies=[Depends(RequirePermission("meetings.read"))],
)
async def speech_capabilities(
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    svc: MeetingAudioService = Depends(_svc),
) -> SpeechCapabilities:
    """Tell the UI whether the server can transcribe and run the minutes AI."""
    return SpeechCapabilities(**await svc.capabilities(_uid(user_id)))


@router.get(
    "/minutes/pdf-languages/",
    response_model=list[str],
    dependencies=[Depends(RequirePermission("meetings.read"))],
)
async def minutes_pdf_languages() -> list[str]:
    """Languages the minutes PDF can be printed in."""
    from app.modules.meetings.pdf import minutes_pdf_languages as languages

    return languages()


# ── Glossary ─────────────────────────────────────────────────────────────────


@router.get(
    "/glossary/",
    response_model=list[GlossaryTermResponse],
    dependencies=[Depends(RequirePermission("meetings.read"))],
)
async def list_glossary(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    svc: MeetingAudioService = Depends(_svc),
) -> list[GlossaryTermResponse]:
    await verify_project_access(project_id, str(user_id), session)
    return [GlossaryTermResponse.model_validate(t) for t in await svc.list_terms(project_id)]


@router.post(
    "/glossary/",
    response_model=GlossaryTermResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("meetings.update"))],
)
async def add_glossary_term(
    data: GlossaryTermCreate,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    svc: MeetingAudioService = Depends(_svc),
) -> GlossaryTermResponse:
    await verify_project_access(project_id, str(user_id), session)
    return GlossaryTermResponse.model_validate(await svc.add_term(project_id, data, _uid(user_id)))


@router.post(
    "/glossary/seed/",
    response_model=GlossarySeedResponse,
    dependencies=[Depends(RequirePermission("meetings.update"))],
)
async def seed_glossary(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    svc: MeetingAudioService = Depends(_svc),
) -> GlossarySeedResponse:
    """Add attendee, contact, stakeholder, company, project and BOQ section names."""
    await verify_project_access(project_id, str(user_id), session)
    rows, by_source = await svc.seed_glossary(project_id, _uid(user_id))
    terms = await svc.list_terms(project_id)
    return GlossarySeedResponse(
        added=len(rows),
        by_source=by_source,
        terms=[GlossaryTermResponse.model_validate(t) for t in terms],
    )


async def _term_for(session: SessionDep, svc: MeetingAudioService, term_id: uuid.UUID, user_id: Any) -> Any:
    row = await svc.glossary.get(term_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Glossary term not found")
    await verify_project_access(row.project_id, str(user_id), session)
    return row


@router.patch(
    "/glossary/{term_id}",
    response_model=GlossaryTermResponse,
    dependencies=[Depends(RequirePermission("meetings.update"))],
)
async def update_glossary_term(
    term_id: uuid.UUID,
    data: GlossaryTermUpdate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    svc: MeetingAudioService = Depends(_svc),
) -> GlossaryTermResponse:
    row = await _term_for(session, svc, term_id, user_id)
    return GlossaryTermResponse.model_validate(await svc.update_term(row, data))


@router.delete(
    "/glossary/{term_id}",
    status_code=204,
    dependencies=[Depends(RequirePermission("meetings.update"))],
)
async def delete_glossary_term(
    term_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    svc: MeetingAudioService = Depends(_svc),
) -> Response:
    row = await _term_for(session, svc, term_id, user_id)
    await svc.delete_term(row)
    return Response(status_code=204)


# ── Recordings ───────────────────────────────────────────────────────────────


@router.get(
    "/{meeting_id}/recordings/",
    response_model=list[RecordingResponse],
    dependencies=[Depends(RequirePermission("meetings.read"))],
)
async def list_recordings(
    meeting_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    svc: MeetingAudioService = Depends(_svc),
) -> list[RecordingResponse]:
    await _meeting_for(session, meeting_id, user_id)
    return [recording_response(r) for r in await svc.list_recordings(meeting_id)]


@router.get(
    "/{meeting_id}/validation/",
    response_model=MeetingValidationResponse,
    dependencies=[Depends(RequirePermission("meetings.read"))],
)
async def validate_meeting(
    meeting_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    svc: MeetingAudioService = Depends(_svc),
) -> MeetingValidationResponse:
    """Traffic light: action ownership, minutes readiness, consent, retention, reviewed proposals."""
    meeting = await _meeting_for(session, meeting_id, user_id)
    report = await svc.validate_meeting(meeting)
    return MeetingValidationResponse(
        status=str(report.status),
        score=report.score,
        errors=len(report.errors),
        warnings=len(report.warnings),
        results=[
            MeetingValidationResult(
                rule_id=r.rule_id,
                severity=str(r.severity),
                passed=r.passed,
                message=r.message,
                element_ref=r.element_ref,
            )
            for r in report.results
        ],
    )


def _parse_segments(raw: str) -> list[dict[str, Any]] | None:
    if not raw.strip():
        return None
    try:
        value = json.loads(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="segments must be a JSON array") from exc
    if not isinstance(value, list):
        raise HTTPException(status_code=400, detail="segments must be a JSON array")
    return value


@router.post(
    "/{meeting_id}/recordings/",
    response_model=RecordingResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("meetings.update"))],
)
async def create_recording(
    meeting_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    consent_confirmed: bool = Form(default=False),
    source: str = Form(default="upload"),
    language: str = Form(default=""),
    transcript: str = Form(default="", max_length=400_000),
    segments: str = Form(default="", max_length=2_000_000),
    delete_audio_after_transcription: bool = Form(default=False),
    retention_days: int | None = Form(default=None, ge=0, le=365),
    file: UploadFile | None = File(default=None),
    svc: MeetingAudioService = Depends(_svc),
) -> RecordingResponse:
    """Add a recording or a transcript to a meeting.

    Audio needs ``consent_confirmed``. It is transcribed with the configured
    speech provider; with none the recording waits for a transcript typed or
    dictated in the browser.
    """
    from app.modules.phonelog import transcription

    meeting = await _meeting_for(session, meeting_id, user_id)
    content: bytes | None = None
    filename: str | None = None
    if file is not None:
        allowed, _retry = upload_limiter.is_allowed(str(user_id))
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many uploads. Please wait a moment and try again.",
                headers={"Retry-After": "60"},
            )
        filename = file.filename or "recording.webm"
        # One byte past the cap is enough to reject without buffering the whole body.
        content = await file.read(transcription.MAX_UPLOAD_BYTES + 1)
    row = await svc.create_recording(
        meeting,
        content=content,
        filename=filename,
        transcript=transcript,
        segments=_parse_segments(segments),
        source=source,
        language=language or None,
        consent=consent_confirmed,
        delete_audio_after_transcription=delete_audio_after_transcription,
        retention_days=retention_days,
        user_id=_uid(user_id),
    )
    return recording_response(row)


@router.patch(
    "/recordings/{recording_id}",
    response_model=RecordingResponse,
    dependencies=[Depends(RequirePermission("meetings.update"))],
)
async def update_recording(
    recording_id: uuid.UUID,
    data: RecordingUpdate,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    svc: MeetingAudioService = Depends(_svc),
) -> RecordingResponse:
    row, meeting = await _recording_for(session, svc, recording_id, user_id)
    return recording_response(await svc.update_recording(row, meeting, data))


@router.post(
    "/recordings/{recording_id}/transcribe/",
    response_model=RecordingResponse,
    dependencies=[Depends(RequirePermission("meetings.update"))],
)
async def retranscribe_recording(
    recording_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    svc: MeetingAudioService = Depends(_svc),
) -> RecordingResponse:
    row, _meeting = await _recording_for(session, svc, recording_id, user_id)
    return recording_response(await svc.retranscribe(row, _uid(user_id)))


@router.post(
    "/recordings/{recording_id}/propose/",
    response_model=RecordingResponse,
    dependencies=[Depends(RequirePermission("meetings.update"))],
)
async def propose_minutes(
    recording_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    svc: MeetingAudioService = Depends(_svc),
) -> RecordingResponse:
    """Propose summary, decisions, actions and open questions for review."""
    row, meeting = await _recording_for(session, svc, recording_id, user_id)
    return recording_response(await svc.propose(row, meeting, _uid(user_id)))


@router.post(
    "/recordings/{recording_id}/review/",
    response_model=ProposalReviewResponse,
    dependencies=[Depends(RequirePermission("meetings.update"))],
)
async def review_proposals(
    recording_id: uuid.UUID,
    body: ProposalReviewRequest,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    svc: MeetingAudioService = Depends(_svc),
) -> ProposalReviewResponse:
    """Confirm or reject proposals; confirmed actions become tracked actions and tasks."""
    row, meeting = await _recording_for(session, svc, recording_id, user_id)
    result = await svc.review(row, meeting, body, _uid(user_id))
    return ProposalReviewResponse(recording=recording_response(row), **result)


@router.get(
    "/recordings/{recording_id}/audio",
    dependencies=[Depends(RequirePermission("meetings.read"))],
)
async def get_recording_audio(
    recording_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    svc: MeetingAudioService = Depends(_svc),
) -> Response:
    from app.core.storage import get_storage_backend
    from app.modules.phonelog import transcription

    row, _meeting = await _recording_for(session, svc, recording_id, user_id)
    if not row.audio_storage_key:
        raise HTTPException(status_code=404, detail="The audio of this recording is gone")
    backend = get_storage_backend()
    presigned = backend.url_for(row.audio_storage_key)
    if presigned:
        return RedirectResponse(url=presigned, status_code=307)
    if not await backend.exists(row.audio_storage_key):
        raise HTTPException(status_code=404, detail="Recording file not found")
    return StreamingResponse(
        backend.open_stream(row.audio_storage_key), media_type=transcription.mime_for(row.audio_storage_key)
    )


@router.delete(
    "/recordings/{recording_id}/audio",
    response_model=RecordingResponse,
    dependencies=[Depends(RequirePermission("meetings.update"))],
)
async def delete_recording_audio(
    recording_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    svc: MeetingAudioService = Depends(_svc),
) -> RecordingResponse:
    """Delete the stored audio now; the transcript and proposals stay."""
    row, _meeting = await _recording_for(session, svc, recording_id, user_id)
    await svc.delete_audio(row)
    if row.audio_storage_key:
        raise HTTPException(status_code=409, detail="The audio could not be deleted, try again")
    await session.refresh(row)
    return recording_response(row)


@router.delete(
    "/recordings/{recording_id}",
    status_code=204,
    dependencies=[Depends(RequirePermission("meetings.update"))],
)
async def delete_recording(
    recording_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    svc: MeetingAudioService = Depends(_svc),
) -> Response:
    row, _meeting = await _recording_for(session, svc, recording_id, user_id)
    await svc.delete_recording(row)
    return Response(status_code=204)
