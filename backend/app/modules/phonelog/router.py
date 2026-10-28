# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Phone-log API routes (mounted at /api/v1/phonelog).

Endpoints:
    GET    /                     - list a project's phone logs (newest first)
    POST   /                     - capture a phone call / voice note / verbal instruction
    POST   /transcribe           - upload a recording, get back a DRAFT protocol to review
    GET    /{phone_log_id}       - fetch one phone log
    GET    /{phone_log_id}/audio - stream the stored recording for playback
    PATCH  /{phone_log_id}       - confirm a reviewed draft into a logged record
    DELETE /{phone_log_id}       - discard a draft (or delete a record) and its recording

Authorization is project-scoped: every route runs verify_project_access against
the row's project before doing anything, which is the IDOR gate. The module does
not register fine-grained RBAC permissions - project access is the contract,
matching the value module and avoiding silent-deny from an unregistered
permission string.
"""

import logging
import uuid

from fastapi import APIRouter, File, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import RedirectResponse, StreamingResponse

from app.core.rate_limiter import upload_limiter
from app.dependencies import CurrentUserId, SessionDep, verify_project_access
from app.modules.phonelog import service, transcription
from app.modules.phonelog.schemas import PhoneLogCreate, PhoneLogFinalize, PhoneLogResponse

router = APIRouter(tags=["phonelog"])
logger = logging.getLogger(__name__)


def _to_response(row: object) -> PhoneLogResponse:
    return PhoneLogResponse(
        id=row.id,  # type: ignore[attr-defined]
        project_id=row.project_id,  # type: ignore[attr-defined]
        direction=row.direction,  # type: ignore[attr-defined]
        channel=row.channel,  # type: ignore[attr-defined]
        parties=list(getattr(row, "parties", None) or []),
        occurred_at=row.occurred_at,  # type: ignore[attr-defined]
        duration_seconds=row.duration_seconds,  # type: ignore[attr-defined]
        transcript=row.transcript,  # type: ignore[attr-defined]
        summary=row.summary,  # type: ignore[attr-defined]
        instructions=list(getattr(row, "instructions", None) or []),
        word_count=row.word_count,  # type: ignore[attr-defined]
        audio_storage_key=getattr(row, "audio_storage_key", "") or "",
        status=row.status,  # type: ignore[attr-defined]
        created_by=row.created_by,  # type: ignore[attr-defined]
        metadata=getattr(row, "metadata_", {}) or {},
        created_at=row.created_at,  # type: ignore[attr-defined]
        updated_at=row.updated_at,  # type: ignore[attr-defined]
    )


@router.get("/", response_model=list[PhoneLogResponse])
async def list_phone_logs(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    direction: str | None = Query(default=None),
    channel: str | None = Query(default=None),
) -> list[PhoneLogResponse]:
    await verify_project_access(project_id, user_id, session)
    items, _ = await service.list_phone_logs(
        session,
        project_id,
        offset=offset,
        limit=limit,
        direction=direction,
        channel=channel,
    )
    return [_to_response(item) for item in items]


@router.post("/", response_model=PhoneLogResponse, status_code=201)
async def create_phone_log(
    data: PhoneLogCreate,
    user_id: CurrentUserId,
    session: SessionDep,
) -> PhoneLogResponse:
    await verify_project_access(data.project_id, user_id, session)
    row = await service.create_phone_log(session, data, user_id=user_id)
    return _to_response(row)


@router.post("/transcribe", response_model=PhoneLogResponse, status_code=201)
async def transcribe_recording(
    user_id: CurrentUserId,
    session: SessionDep,
    file: UploadFile = File(..., description="Audio or video recording of a call, meeting, or site talk"),
    project_id: uuid.UUID = Query(...),
    occurred_at: str | None = Query(default=None),
    direction: str | None = Query(default=None),
) -> PhoneLogResponse:
    """Upload a recording and get back a DRAFT protocol for review.

    Accepts an audio or video recording a speech-to-text provider takes directly
    (mp3, m4a, wav, webm, mp4, mpeg, mpga). The recording is stored, transcribed
    when a provider is configured, and turned into a draft protocol (transcript,
    participants, summary, decisions, action items, instructions) the user reviews
    and confirms before it is saved. When transcription is unavailable the draft
    is still created with status ``awaiting_transcript`` so a transcript can be
    pasted by hand. Nothing here is auto-saved as a final record.
    """
    await verify_project_access(project_id, user_id, session)

    allowed, _retry = upload_limiter.is_allowed(str(user_id))
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many uploads. Please wait a moment and try again.",
            headers={"Retry-After": "60"},
        )

    filename = file.filename or "recording"
    # Read at most one byte past the cap so an oversized file is rejected without
    # buffering the whole body into memory.
    content = await file.read(transcription.MAX_UPLOAD_BYTES + 1)
    problem = transcription.check_audio_upload(filename, len(content))
    if problem is not None:
        raise HTTPException(status_code=problem[0], detail=problem[1])

    row = await service.transcribe_recording(
        session,
        project_id=project_id,
        file_content=content,
        filename=filename,
        occurred_at=occurred_at,
        direction_hint=direction,
        user_id=str(user_id) if user_id else None,
    )
    return _to_response(row)


@router.get("/{phone_log_id}", response_model=PhoneLogResponse)
async def get_phone_log(
    phone_log_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> PhoneLogResponse:
    row = await service.get_phone_log(session, phone_log_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Phone log not found")
    await verify_project_access(row.project_id, str(user_id), session)
    return _to_response(row)


@router.get("/{phone_log_id}/audio")
async def get_phone_log_audio(
    phone_log_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> Response:
    """Stream the stored recording for playback, scoped to the row's project."""
    row = await service.get_phone_log(session, phone_log_id)
    if row is None or not getattr(row, "audio_storage_key", ""):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")
    await verify_project_access(row.project_id, str(user_id), session)

    from app.core.storage import get_storage_backend

    backend = get_storage_backend()
    key = row.audio_storage_key
    media_type = transcription.mime_for(key)

    # S3-style backends return a presigned URL; the local backend streams bytes.
    presigned = backend.url_for(key)
    if presigned:
        return RedirectResponse(url=presigned, status_code=307)
    if not await backend.exists(key):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording file not found")
    return StreamingResponse(backend.open_stream(key), media_type=media_type)


@router.patch("/{phone_log_id}", response_model=PhoneLogResponse)
async def confirm_phone_log(
    phone_log_id: uuid.UUID,
    data: PhoneLogFinalize,
    user_id: CurrentUserId,
    session: SessionDep,
) -> PhoneLogResponse:
    """Confirm a reviewed draft into a normal, logged phone-log record.

    This is the human-confirm step: the reviewed transcript, parties, timing, and
    the edited structured protocol are saved and the record's status flips to
    ``logged``.
    """
    row = await service.get_phone_log(session, phone_log_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Phone log not found")
    await verify_project_access(row.project_id, str(user_id), session)
    updated = await service.finalize_phone_log(session, phone_log_id, data)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Phone log not found")
    return _to_response(updated)


@router.delete("/{phone_log_id}", status_code=204)
async def delete_phone_log(
    phone_log_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> Response:
    """Discard a draft (or delete a record) together with its stored recording."""
    row = await service.get_phone_log(session, phone_log_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Phone log not found")
    await verify_project_access(row.project_id, str(user_id), session)
    await service.delete_phone_log(session, phone_log_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
