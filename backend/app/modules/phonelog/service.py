# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Phone-log service - capture a verbal instruction and read a project's log.

The capture path runs the pure ``phonelog.normalize`` engine over the raw input
so every stored row is canonical (direction, channel, parties, duration,
summary, and the instruction-bearing sentences pulled from the transcript), then
persists it and publishes a ``phone_log.created`` event mirroring the
correspondence module so downstream indexers and timelines can pick it up.

``get_session`` commits after the request completes, so this layer flushes and
never commits - the caller owns the transaction boundary.
"""

import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.phonelog import transcription
from app.modules.phonelog.models import PhoneLog
from app.modules.phonelog.normalize import PhoneLogInput, normalize
from app.modules.phonelog.schemas import PhoneLogCreate, PhoneLogFinalize

logger = logging.getLogger(__name__)


async def _safe_publish(name: str, data: dict, source_module: str = "oe_phonelog") -> None:
    """Publish an event, swallowing errors so the capture path never breaks.

    Mirrors correspondence: an event-bus hiccup must not fail the write that the
    user just made - the record is the point, the event is best-effort.
    """
    try:
        from app.core.events import event_bus

        event_bus.publish_detached(name, data, source_module=source_module)
    except Exception as exc:
        logger.debug("Event publish failed for %s: %s", name, exc)


async def create_phone_log(
    session: AsyncSession,
    data: PhoneLogCreate,
    *,
    user_id: str | None = None,
) -> PhoneLog:
    """Normalize a raw capture and persist it as a dispute-ready phone-log row."""
    normalized = normalize(
        PhoneLogInput(
            raw_parties=data.raw_parties,
            direction=data.direction,
            started_at=data.started_at,
            ended_at=data.ended_at,
            duration_seconds=data.duration_seconds,
            transcript=data.transcript,
            summary=data.summary,
            channel=data.channel,
        )
    )

    row = PhoneLog(
        project_id=data.project_id,
        direction=normalized.direction,
        channel=normalized.channel,
        parties=list(normalized.parties),
        occurred_at=data.started_at or None,
        duration_seconds=normalized.duration_seconds,
        # Keep the transcript verbatim - it is the underlying evidence.
        transcript=data.transcript,
        summary=normalized.summary,
        instructions=list(normalized.instructions),
        word_count=normalized.word_count,
        created_by=user_id,
        metadata_=data.metadata,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)

    # PII discipline: log only structural fields. Transcript / summary / parties
    # can carry personal data and must not reach structured-log sinks.
    logger.info(
        "Phone log captured: %s (%s/%s) for project %s",
        row.id,
        row.direction,
        row.channel,
        data.project_id,
    )
    await _safe_publish(
        "phone_log.created",
        {
            "project_id": str(data.project_id),
            "phone_log_id": str(row.id),
            "direction": row.direction,
            "channel": row.channel,
        },
    )
    return row


async def transcribe_recording(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    file_content: bytes,
    filename: str,
    occurred_at: str | None = None,
    direction_hint: str | None = None,
    user_id: str | None = None,
) -> PhoneLog:
    """Store a recording, transcribe it, and build a DRAFT protocol row.

    The returned row is a draft the user reviews and confirms via
    :func:`finalize_phone_log`; it is never a final logged record. AI is optional:
    when transcription is unavailable the recording is still stored and the row is
    created with status ``awaiting_transcript`` and an empty transcript so the
    user can paste one by hand via the normal capture path. Nothing here raises on
    a missing provider or a provider failure.
    """
    # 1. Persist the recording under a unique, project-scoped storage key.
    ext = transcription.audio_extension(filename)
    object_id = uuid.uuid4().hex
    key = f"phonelog/{project_id}/{object_id}.{ext}" if ext else f"phonelog/{project_id}/{object_id}"
    from app.core.storage import get_storage_backend

    await get_storage_backend().put(key, file_content)

    # 2. Transcribe (graceful: no key or a provider failure -> empty transcript).
    result = transcription.TranscriptionResult()
    api_key = await transcription.resolve_openai_key(session, user_id)
    if api_key:
        result = await transcription.transcribe_audio(file_content, filename, api_key=api_key)
    transcript = result.text

    # 3. Deterministic normalize pass over the transcript plus the caller hints.
    normalized = normalize(
        PhoneLogInput(
            raw_parties="",
            direction=direction_hint or "",
            started_at=occurred_at,
            duration_seconds=result.duration_seconds,
            transcript=transcript,
            summary="",
            channel="voice_note",
        )
    )

    # 4. Optional structured-protocol extraction (only with a transcript + LLM).
    llm_result = await transcription.extract_protocol(transcript, session, user_id) if transcript else None
    protocol = transcription.build_protocol(llm_result=llm_result, normalized=normalized, transcript=transcript)

    parties = list(protocol.get("participants") or normalized.parties)
    status = "draft" if transcript else "awaiting_transcript"
    metadata = {
        "source": "recording",
        "original_filename": filename,
        "protocol": protocol,
        "transcription": {
            "available": result.available,
            "model": transcription.TRANSCRIBE_MODEL if result.available else None,
            "language": result.language,
            "error": result.error,
        },
    }

    row = PhoneLog(
        project_id=project_id,
        direction=normalized.direction,
        channel=normalized.channel,
        parties=parties,
        occurred_at=occurred_at or None,
        duration_seconds=normalized.duration_seconds,
        transcript=transcript,
        summary=normalized.summary,
        instructions=list(normalized.instructions),
        word_count=normalized.word_count,
        audio_storage_key=key,
        status=status,
        created_by=user_id,
        metadata_=metadata,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)

    # PII discipline: log only structural fields, never transcript / parties.
    logger.info(
        "Phone log recording ingested: %s (status=%s, transcribed=%s) for project %s",
        row.id,
        status,
        "yes" if transcript else "no",
        project_id,
    )
    await _safe_publish(
        "phone_log.recording_ingested",
        {
            "project_id": str(project_id),
            "phone_log_id": str(row.id),
            "status": status,
            "transcribed": bool(transcript),
        },
    )
    return row


async def finalize_phone_log(
    session: AsyncSession,
    phone_log_id: uuid.UUID,
    data: PhoneLogFinalize,
) -> PhoneLog | None:
    """Confirm a reviewed draft into a normal, logged phone-log record.

    Parties, direction, channel, and duration are re-normalized from the reviewed
    input; the transcript and the edited protocol are stored as confirmed. The
    reviewed instructions win, falling back to the transcript-derived ones so a
    confirm never silently drops instructions. Returns None when the row is gone.
    """
    row = await get_phone_log(session, phone_log_id)
    if row is None:
        return None

    normalized = normalize(
        PhoneLogInput(
            raw_parties=data.raw_parties,
            direction=data.direction,
            started_at=data.occurred_at,
            duration_seconds=data.duration_seconds,
            transcript=data.transcript,
            summary=data.summary,
            channel=data.channel,
        )
    )

    row.direction = normalized.direction
    row.channel = normalized.channel
    row.parties = list(normalized.parties)
    row.occurred_at = data.occurred_at or row.occurred_at
    if normalized.duration_seconds is not None:
        row.duration_seconds = normalized.duration_seconds
    row.transcript = data.transcript
    row.summary = normalized.summary
    row.instructions = list(data.instructions) if data.instructions else list(normalized.instructions)
    row.word_count = normalized.word_count

    # Merge the reviewed protocol into metadata, keeping the transcription record,
    # and re-sync the protocol's participants / summary / instructions with the
    # confirmed values so the stored protocol stays self-consistent. A whole-dict
    # reassignment is used so the JSON column change is detected and persisted.
    metadata = dict(row.metadata_ or {})
    protocol = dict(metadata.get("protocol") or {})
    if data.protocol:
        protocol.update(data.protocol)
    protocol["participants"] = list(normalized.parties)
    protocol["summary"] = normalized.summary
    protocol["instructions"] = list(row.instructions)
    metadata["protocol"] = protocol
    row.metadata_ = metadata

    row.status = "logged"
    await session.flush()
    await session.refresh(row)

    logger.info("Phone log draft confirmed: %s for project %s", row.id, row.project_id)
    await _safe_publish(
        "phone_log.created",
        {
            "project_id": str(row.project_id),
            "phone_log_id": str(row.id),
            "direction": row.direction,
            "channel": row.channel,
        },
    )
    return row


async def delete_phone_log(session: AsyncSession, phone_log_id: uuid.UUID) -> bool:
    """Delete a phone-log row and its stored recording. Returns False if missing.

    Used to discard a draft the user chose not to keep. The stored recording is
    best-effort removed; a stray file must never fail the row delete.
    """
    row = await get_phone_log(session, phone_log_id)
    if row is None:
        return False
    key = getattr(row, "audio_storage_key", "") or ""
    await session.delete(row)
    await session.flush()
    if key:
        try:
            from app.core.storage import get_storage_backend

            await get_storage_backend().delete(key)
        except Exception as exc:  # noqa: BLE001 - a stray file must not fail the delete
            logger.debug("Recording delete failed for %s: %s", key, exc)
    return True


async def list_phone_logs(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    offset: int = 0,
    limit: int = 50,
    direction: str | None = None,
    channel: str | None = None,
) -> tuple[list[PhoneLog], int]:
    """Return a project's phone logs (newest first) and the total match count."""
    stmt = select(PhoneLog).where(PhoneLog.project_id == project_id)
    if direction:
        stmt = stmt.where(PhoneLog.direction == direction)
    if channel:
        stmt = stmt.where(PhoneLog.channel == channel)

    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        (await session.execute(stmt.order_by(PhoneLog.created_at.desc()).offset(offset).limit(limit))).scalars().all()
    )
    return list(rows), int(total)


async def get_phone_log(session: AsyncSession, phone_log_id: uuid.UUID) -> PhoneLog | None:
    """Fetch a single phone log by id, or None when it does not exist."""
    return (await session.execute(select(PhoneLog).where(PhoneLog.id == phone_log_id))).scalar_one_or_none()
