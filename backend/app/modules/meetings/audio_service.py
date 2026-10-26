# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Minutes from audio: record, transcribe, propose, confirm.

The flow a meeting secretary goes through:

1. Confirm that everybody in the room was told and agreed, then record in the
   browser or upload a file. Without consent nothing is stored.
2. The audio is transcribed through the configured speech provider
   (:mod:`app.modules.voice.speech`) with the project glossary as vocabulary
   hints. No provider: the browser's own recognition or typed minutes take
   over, and the recording waits for a transcript.
3. Known mis-hearings from the glossary are replaced; speaker labels can be
   renamed to the people they are.
4. The AI (or, without one, a keyword heuristic) proposes a summary, decisions,
   action items with owner, due date and linked record, open questions and
   spelling corrections, each with a confidence.
5. A person confirms or rejects each one. Confirmed items land through the
   existing services: the meeting summary and decisions feed the minutes
   builder, actions join the action register and open a task.

Audio is kept only as long as needed: it is deleted after transcription when
asked, on request, or by the daily retention sweep.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import publish_after_commit
from app.modules.meetings import audio_logic
from app.modules.meetings.audio_repository import GlossaryRepository, RecordingRepository
from app.modules.meetings.audio_schemas import (
    GlossaryTermCreate,
    GlossaryTermUpdate,
    ProposalReviewRequest,
    RecordingUpdate,
)
from app.modules.meetings.models import Meeting, MeetingGlossaryTerm, MeetingRecording

logger = logging.getLogger(__name__)

RETENTION_ENV = "OE_MEETINGS_AUDIO_RETENTION_DAYS"
DEFAULT_RETENTION_DAYS = 30
MAX_RETENTION_DAYS = 365
AI_FEEDBACK_SURFACE = "meeting_minutes"
_PROPOSAL_MAX_TOKENS = 3000
_PROPOSAL_TRANSCRIPT_CHARS = 30000

PROPOSAL_SYSTEM_PROMPT = (
    "You write minutes of construction project meetings from a transcript. Extract only what was "
    "actually said: never invent names, decisions, dates or tasks. Spell names, companies and terms "
    "exactly as the project glossary does. Respond with a single JSON object and nothing else."
)


def default_retention_days() -> int:
    """Server default for how long meeting audio is kept (``0`` keeps it)."""
    raw = (os.environ.get(RETENTION_ENV) or "").strip()
    if not raw:
        return DEFAULT_RETENTION_DAYS
    try:
        return max(0, min(MAX_RETENTION_DAYS, int(raw)))
    except ValueError:
        logger.warning("%s=%r is not a number, using %d", RETENTION_ENV, raw, DEFAULT_RETENTION_DAYS)
        return DEFAULT_RETENTION_DAYS


def effective_retention_days(requested: int | None) -> int:
    """The request may shorten the server window, never lengthen past it."""
    server = default_retention_days()
    if requested is None or requested <= 0:
        return server
    if server <= 0:
        return min(requested, MAX_RETENTION_DAYS)
    return min(requested, server)


def _language_name(code: str | None) -> str:
    try:
        from app.core.i18n import LOCALE_NAMES

        name = LOCALE_NAMES.get(code or "")
        if isinstance(name, str) and name:
            return name
    except Exception:  # noqa: BLE001 - a name is cosmetic, the code still works
        logger.debug("LOCALE_NAMES unavailable")
    return code or "the language of the transcript"


def build_proposal_prompt(transcript: str, glossary_block: str, people: list[str], language: str | None) -> str:
    """The user prompt for the minutes extraction pass."""
    clipped = transcript.strip()
    if len(clipped) > _PROPOSAL_TRANSCRIPT_CHARS:
        clipped = clipped[:_PROPOSAL_TRANSCRIPT_CHARS] + "\n[transcript truncated]"
    lang = _language_name(language)
    return (
        f"Write every text value in {lang}.\n"
        "Return a JSON object with exactly these keys:\n"
        '- "summary": a neutral summary of the meeting, 3 to 6 sentences.\n'
        '- "summary_confidence": number 0..1.\n'
        '- "decisions": array of {"text", "quote" (the words that show it), "confidence" 0..1}.\n'
        '- "action_items": array of {"task", "owner" (a person or company named in the meeting, "" if '
        'unclear), "due" (ISO date, or a phrase such as "next week" only if stated, else null), '
        '"linked_ref" (an RFI number like "RFI-12" or a BOQ position number like "03.02.010" if the task '
        'is about one, else null), "quote", "confidence" 0..1}.\n'
        '- "open_questions": array of {"text", "confidence" 0..1} for questions left unanswered.\n'
        '- "spelling_corrections": array of {"heard", "term"} where the transcript misspells a glossary '
        "term; heard must be copied exactly from the transcript.\n"
        '- "confidence": number 0..1 for the whole result.\n\n'
        f"Project glossary (correct spellings):\n{glossary_block or '(empty)'}\n\n"
        f"People in the meeting: {', '.join(people) or '(not listed)'}\n\n"
        f'Transcript:\n"""\n{clipped}\n"""'
    )


async def _ai_settings(session: Any, user_id: str | None) -> Any:
    if session is None or not user_id:
        return None
    try:
        from app.modules.ai.repository import AISettingsRepository

        return await AISettingsRepository(session).get_by_user_id(uuid.UUID(str(user_id)))
    except Exception as exc:  # noqa: BLE001 - never let a settings lookup break the flow
        logger.debug("AI settings lookup failed: %s", exc)
        return None


async def llm_available(session: Any, user_id: str | None) -> bool:
    """True when a text AI provider is configured for this caller."""
    try:
        from app.modules.ai.ai_client import resolve_provider_key_model
    except Exception:  # noqa: BLE001 - AI module optional
        return False
    try:
        resolve_provider_key_model(await _ai_settings(session, user_id))
    except ValueError:
        return False
    return True


async def run_proposal_llm(session: Any, user_id: str | None, prompt: str) -> dict[str, Any] | None:
    """One extraction pass through the shared AI client; None on any degrade."""
    try:
        from app.modules.ai.ai_client import call_ai, extract_json, resolve_provider_key_model
    except Exception as exc:  # noqa: BLE001 - AI module optional; degrade if unavailable
        logger.debug("AI client import failed: %s", exc)
        return None
    try:
        provider, api_key, model_override = resolve_provider_key_model(await _ai_settings(session, user_id))
    except ValueError:
        return None
    try:
        raw, _tokens = await call_ai(
            provider=provider,
            api_key=api_key,
            system=PROPOSAL_SYSTEM_PROMPT,
            prompt=prompt,
            max_tokens=_PROPOSAL_MAX_TOKENS,
            model=model_override,
        )
    except Exception as exc:  # noqa: BLE001 - provider error must degrade, not crash
        logger.warning("Minutes proposal call failed: %s", type(exc).__name__)
        return None
    parsed = extract_json(raw)
    return parsed if isinstance(parsed, dict) else None


def _is_uuid(value: Any) -> bool:
    try:
        uuid.UUID(str(value))
    except (ValueError, TypeError):
        return False
    return True


class MeetingAudioService:
    """Recording, transcription and proposal review for meeting minutes."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.recordings = RecordingRepository(session)
        self.glossary = GlossaryRepository(session)

    # ── Capabilities ────────────────────────────────────────────────────

    async def capabilities(self, user_id: str | None) -> dict[str, Any]:
        from app.modules.phonelog import transcription
        from app.modules.voice.speech import resolve_speech_provider

        provider = await resolve_speech_provider(self.session, user_id)
        return {
            "server_transcription": provider is not None,
            "provider": provider.name if provider is not None else None,
            "llm_available": await llm_available(self.session, user_id),
            "max_upload_mb": transcription.MAX_UPLOAD_BYTES // (1024 * 1024),
            "accepted_formats": sorted(transcription.ACCEPTED_AUDIO_EXTENSIONS),
            "default_retention_days": default_retention_days(),
            "max_retention_days": MAX_RETENTION_DAYS,
        }

    # ── Glossary ────────────────────────────────────────────────────────

    async def list_terms(self, project_id: uuid.UUID) -> list[MeetingGlossaryTerm]:
        return await self.glossary.list_for_project(project_id)

    async def _term_dicts(self, project_id: uuid.UUID) -> list[dict[str, Any]]:
        return [
            {
                "term": t.term,
                "kind": t.kind,
                "expansion": t.expansion,
                "aliases": list(t.aliases or []),
                "contact_id": t.contact_id,
            }
            for t in await self.glossary.list_for_project(project_id)
        ]

    async def add_term(
        self, project_id: uuid.UUID, data: GlossaryTermCreate, user_id: str | None
    ) -> MeetingGlossaryTerm:
        text = audio_logic.clean_term(data.term)
        if not text:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="The term is not usable")
        key = audio_logic.term_key(text)
        if await self.glossary.get_by_key(project_id, key) is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This term is already in the glossary")
        row = MeetingGlossaryTerm(
            project_id=project_id,
            term=text,
            term_key=key,
            kind=data.kind,
            expansion=data.expansion or None,
            aliases=audio_logic.clean_aliases(data.aliases, term=text),
            source="manual",
            created_by=user_id,
        )
        await self.glossary.add_many([row])
        await self.session.refresh(row)
        return row

    async def update_term(self, row: MeetingGlossaryTerm, data: GlossaryTermUpdate) -> MeetingGlossaryTerm:
        if data.term is not None:
            text = audio_logic.clean_term(data.term)
            if not text:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="The term is not usable")
            key = audio_logic.term_key(text)
            clash = await self.glossary.get_by_key(row.project_id, key)
            if clash is not None and clash.id != row.id:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This term is already in the glossary")
            row.term, row.term_key = text, key
        if data.kind is not None:
            row.kind = data.kind
        if data.expansion is not None:
            row.expansion = data.expansion or None
        if data.aliases is not None:
            row.aliases = audio_logic.clean_aliases(data.aliases, term=row.term)
        await self.session.flush()
        await self.session.refresh(row)
        return row

    async def delete_term(self, row: MeetingGlossaryTerm) -> None:
        await self.glossary.delete(row)

    async def _seed_candidates(self, project_id: uuid.UUID) -> list[dict[str, Any]]:
        """Gather names and terms the project already knows, module by module.

        Each source is optional: a module that is absent or fails contributes
        nothing instead of breaking the seed.
        """
        out: list[dict[str, Any]] = []
        contact_ids: set[str] = set()

        try:
            from app.modules.projects.models import Project

            name = await self.session.scalar(select(Project.name).where(Project.id == project_id))
            if name:
                out.append({"term": name, "kind": "term", "source": "project"})
        except Exception as exc:  # noqa: BLE001
            logger.debug("glossary seed: project name skipped: %s", exc)

        meetings = (
            (await self.session.execute(select(Meeting.attendees).where(Meeting.project_id == project_id)))
            .scalars()
            .all()
        )
        for attendees in meetings:
            for att in attendees or []:
                if not isinstance(att, dict):
                    continue
                uid = str(att.get("user_id") or "")
                if _is_uuid(uid):
                    contact_ids.add(uid)
                out.append(
                    {
                        "term": att.get("name"),
                        "kind": "person",
                        "source": "attendees",
                        "contact_id": uid if _is_uuid(uid) else None,
                    }
                )
                out.append({"term": att.get("company"), "kind": "company", "source": "attendees"})

        try:
            from app.modules.stakeholders.models import Stakeholder

            rows = (
                await self.session.execute(
                    select(Stakeholder.display_name, Stakeholder.contact_id).where(Stakeholder.project_id == project_id)
                )
            ).all()
            for display_name, contact_id in rows:
                out.append({"term": display_name, "kind": "company", "source": "stakeholders"})
                if contact_id:
                    contact_ids.add(str(contact_id))
        except Exception as exc:  # noqa: BLE001
            logger.debug("glossary seed: stakeholders skipped: %s", exc)

        if contact_ids:
            try:
                from app.modules.contacts.models import Contact

                ids = [uuid.UUID(c) for c in contact_ids]
                for contact in (await self.session.execute(select(Contact).where(Contact.id.in_(ids)))).scalars():
                    person = " ".join(p for p in (contact.first_name, contact.last_name) if p)
                    if person:
                        out.append(
                            {"term": person, "kind": "person", "source": "contacts", "contact_id": str(contact.id)}
                        )
                    if contact.company_name:
                        out.append({"term": contact.company_name, "kind": "company", "source": "contacts"})
            except Exception as exc:  # noqa: BLE001
                logger.debug("glossary seed: contacts skipped: %s", exc)

        try:
            from app.modules.boq.models import BOQ, Position
            from app.modules.boq.service import _is_section

            boqs = (await self.session.execute(select(BOQ.id, BOQ.name).where(BOQ.project_id == project_id))).all()
            for _boq_id, boq_name in boqs:
                out.append({"term": boq_name, "kind": "boq", "source": "boq"})
            if boqs:
                positions = (
                    (await self.session.execute(select(Position).where(Position.boq_id.in_([b[0] for b in boqs]))))
                    .scalars()
                    .all()
                )
                for pos in positions:
                    if _is_section(pos) and len(pos.description or "") <= 80:
                        out.append({"term": pos.description, "kind": "boq", "source": "boq"})
        except Exception as exc:  # noqa: BLE001
            logger.debug("glossary seed: BOQ skipped: %s", exc)
        return out

    async def seed_glossary(
        self, project_id: uuid.UUID, user_id: str | None
    ) -> tuple[list[MeetingGlossaryTerm], dict[str, int]]:
        """Add every project name and term the glossary does not have yet."""
        existing = {t.term_key for t in await self.glossary.list_for_project(project_id)}
        merged = audio_logic.merge_seed_terms(await self._seed_candidates(project_id), existing)
        rows = [
            MeetingGlossaryTerm(
                project_id=project_id,
                term=m["term"],
                term_key=m["term_key"],
                kind=m["kind"],
                expansion=m["expansion"],
                aliases=[],
                source=m["source"],
                contact_id=m["contact_id"],
                created_by=user_id,
            )
            for m in merged
        ]
        if rows:
            await self.glossary.add_many(rows)
        by_source: dict[str, int] = {}
        for m in merged:
            by_source[m["source"]] = by_source.get(m["source"], 0) + 1
        return rows, by_source

    # ── Recordings ──────────────────────────────────────────────────────

    async def get_recording(self, recording_id: uuid.UUID) -> MeetingRecording:
        row = await self.recordings.get(recording_id)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording not found")
        return row

    async def list_recordings(self, meeting_id: uuid.UUID) -> list[MeetingRecording]:
        return await self.recordings.list_for_meeting(meeting_id)

    async def _project_locale(self, project_id: uuid.UUID) -> str | None:
        try:
            from app.modules.projects.models import Project

            return await self.session.scalar(select(Project.locale).where(Project.id == project_id))
        except Exception:  # noqa: BLE001
            return None

    async def meeting_language(self, meeting: Meeting) -> str | None:
        """The language the minutes are written in: set on the meeting, else the project's."""
        meta = meeting.metadata_ or {}
        return audio_logic.language_code(meta.get("language")) or audio_logic.language_code(
            await self._project_locale(meeting.project_id)
        )

    def _remember_language(self, meeting: Meeting, code: str | None) -> None:
        if code and not (meeting.metadata_ or {}).get("language"):
            meeting.metadata_ = {**(meeting.metadata_ or {}), "language": code}

    async def create_recording(
        self,
        meeting: Meeting,
        *,
        content: bytes | None,
        filename: str | None,
        transcript: str,
        segments: list[dict[str, Any]] | None,
        source: str,
        language: str | None,
        consent: bool,
        delete_audio_after_transcription: bool,
        retention_days: int | None,
        user_id: str | None,
    ) -> MeetingRecording:
        """Store a recording (or a transcript) and transcribe it when possible."""
        from app.modules.phonelog import transcription

        if source not in audio_logic.RECORDING_SOURCES:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Unknown recording source")
        has_audio = bool(content)
        if audio_logic.consent_required(source, has_audio) and not consent:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Confirm that every participant was told about the recording and agreed",
            )
        if not has_audio and not transcript.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Upload a recording or provide a transcript",
            )

        now = datetime.now(UTC)
        lang = audio_logic.language_code(language) or await self.meeting_language(meeting)
        row = MeetingRecording(
            project_id=meeting.project_id,
            meeting_id=meeting.id,
            source=source,
            status="transcribed" if transcript.strip() else "pending",
            audio_storage_key="",
            delete_audio_after_transcription=bool(delete_audio_after_transcription),
            consent_confirmed_at=now if consent else None,
            consent_confirmed_by=user_id if consent else None,
            language=lang,
            transcript=transcript.strip(),
            segments=audio_logic.normalize_segments(segments or []),
            speakers={},
            proposals={},
            created_by=user_id,
            metadata_={},
        )

        if has_audio and content is not None:
            name = filename or "recording.webm"
            problem = transcription.check_audio_upload(name, len(content))
            if problem is not None:
                raise HTTPException(status_code=problem[0], detail=problem[1])
            ext = transcription.audio_extension(name)
            key = f"meetings/{meeting.project_id}/{meeting.id}/{uuid.uuid4().hex}.{ext}"
            from app.core.storage import get_storage_backend

            await get_storage_backend().put(key, content)
            row.audio_storage_key = key
            row.audio_filename = name[:255]
            row.audio_size_bytes = len(content)
            row.audio_expires_at = audio_logic.audio_expiry(now, effective_retention_days(retention_days))

        if not row.segments and row.transcript:
            row.segments = self._segments_from_text(row.transcript)

        await self.recordings.add(row)
        if has_audio and content is not None:
            await self._transcribe(row, content, user_id)
        else:
            await self._apply_glossary_aliases(row)
        self._remember_language(meeting, row.language)
        await self.session.flush()
        await self.session.refresh(row)
        publish_after_commit(
            self.session,
            "meeting.recording_added",
            {
                "meeting_id": str(meeting.id),
                "project_id": str(meeting.project_id),
                "recording_id": str(row.id),
                "source": row.source,
                "status": row.status,
            },
            source_module="meetings",
        )
        return row

    @staticmethod
    def _segments_from_text(text: str) -> list[dict[str, Any]]:
        from app.modules.meetings.router import _parse_plain_text

        return audio_logic.normalize_segments(_parse_plain_text(text))

    async def _apply_glossary_aliases(self, row: MeetingRecording) -> int:
        terms = await self._term_dicts(row.project_id)
        if not terms:
            return 0
        row.transcript, count = audio_logic.apply_aliases(row.transcript, terms)
        segments = []
        for seg in row.segments or []:
            text, n = audio_logic.apply_aliases(str(seg.get("text") or ""), terms)
            segments.append({**seg, "text": text})
            count += n
        row.segments = segments
        row.metadata_ = {**(row.metadata_ or {}), "glossary_replacements": count}
        return count

    async def _transcribe(self, row: MeetingRecording, content: bytes, user_id: str | None) -> None:
        from app.modules.voice.speech import resolve_speech_provider

        provider = await resolve_speech_provider(self.session, user_id)
        if provider is None:
            row.status = "awaiting_transcript" if not row.transcript else "transcribed"
            row.transcription_error = "no transcription provider configured"
            return
        hint = audio_logic.build_transcription_hint(await self._term_dicts(row.project_id))
        result = await provider.transcribe(
            content, row.audio_filename or "recording.webm", language=row.language, prompt=hint or None
        )
        row.provider = provider.name
        if not result.available:
            row.status = "failed" if not row.transcript else "transcribed"
            row.transcription_error = (result.error or "transcription failed")[:300]
            return
        row.transcript = result.text
        row.segments = audio_logic.normalize_segments(result.segments) or self._segments_from_text(result.text)
        row.language = audio_logic.language_code(result.language) or row.language
        row.duration_seconds = result.duration_seconds
        row.status = "transcribed"
        row.transcription_error = None
        await self._apply_glossary_aliases(row)
        if row.delete_audio_after_transcription:
            await self.delete_audio(row)

    async def retranscribe(self, row: MeetingRecording, user_id: str | None) -> MeetingRecording:
        """Run transcription again on the stored audio (e.g. after a glossary edit)."""
        if not row.audio_storage_key:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="The audio of this recording is gone")
        from app.core.storage import get_storage_backend

        content = await get_storage_backend().get(row.audio_storage_key)
        await self._transcribe(row, content, user_id)
        await self.session.flush()
        await self.session.refresh(row)
        return row

    async def update_recording(
        self, row: MeetingRecording, meeting: Meeting, data: RecordingUpdate
    ) -> MeetingRecording:
        if data.segments is not None:
            row.segments = audio_logic.normalize_segments([s.model_dump() for s in data.segments])
            if data.transcript is None:
                row.transcript = audio_logic.render_transcript(row.segments, {}, row.transcript)
        if data.transcript is not None:
            row.transcript = data.transcript.strip()
            if data.segments is None:
                row.segments = self._segments_from_text(row.transcript)
        if row.transcript and row.status in ("pending", "awaiting_transcript", "failed"):
            row.status = "transcribed"
        if data.speakers is not None:
            raw = {k: v.model_dump() for k, v in data.speakers.items()}
            row.speakers = audio_logic.normalize_speakers(raw, audio_logic.speaker_labels(row.segments or []))
        if data.language is not None:
            row.language = audio_logic.language_code(data.language)
            if row.language:
                meeting.metadata_ = {**(meeting.metadata_ or {}), "language": row.language}
        await self.session.flush()
        await self.session.refresh(row)
        return row

    async def delete_audio(self, row: MeetingRecording) -> MeetingRecording:
        """Delete the stored audio; the transcript and proposals stay."""
        key = row.audio_storage_key
        if key:
            from app.core.storage import get_storage_backend

            try:
                await get_storage_backend().delete(key)
            except Exception:  # noqa: BLE001 - keep the key so the sweep retries
                logger.warning("meetings audio: could not delete recording %s", row.id)
                return row
        row.audio_storage_key = ""
        row.audio_expires_at = None
        row.audio_deleted_at = datetime.now(UTC)
        await self.session.flush()
        return row

    async def delete_recording(self, row: MeetingRecording) -> None:
        await self.delete_audio(row)
        if row.audio_storage_key:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="The audio could not be deleted, try again"
            )
        await self.recordings.delete(row)

    # ── Proposals ───────────────────────────────────────────────────────

    async def _people(self, meeting: Meeting, row: MeetingRecording) -> list[dict[str, Any]]:
        people: list[dict[str, Any]] = []
        seen: set[str] = set()

        def add(name: Any, contact_id: Any) -> None:
            text = " ".join(str(name or "").split())
            if not text or text.casefold() in seen:
                return
            seen.add(text.casefold())
            people.append({"name": text, "contact_id": str(contact_id) if _is_uuid(contact_id) else None})

        for att in meeting.attendees or []:
            if isinstance(att, dict):
                add(att.get("name"), att.get("user_id"))
        for info in (row.speakers or {}).values():
            if isinstance(info, dict):
                add(info.get("name"), info.get("contact_id"))
        for term in await self.glossary.list_for_project(meeting.project_id):
            if term.kind in ("person", "company"):
                add(term.term, term.contact_id)
        return people

    async def _link_targets(self, project_id: uuid.UUID) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        rfis: list[dict[str, Any]] = []
        positions: list[dict[str, Any]] = []
        try:
            from app.modules.rfi.models import RFI

            rows = (
                await self.session.execute(
                    select(RFI.id, RFI.rfi_number, RFI.subject).where(RFI.project_id == project_id).limit(2000)
                )
            ).all()
            rfis = [{"id": r[0], "number": r[1], "subject": r[2]} for r in rows]
        except Exception as exc:  # noqa: BLE001
            logger.debug("proposal links: RFIs skipped: %s", exc)
        try:
            from app.modules.boq.models import BOQ, Position

            rows = (
                await self.session.execute(
                    select(Position.id, Position.ordinal, Position.description)
                    .join(BOQ, BOQ.id == Position.boq_id)
                    .where(BOQ.project_id == project_id)
                    .limit(20000)
                )
            ).all()
            positions = [{"id": r[0], "ordinal": r[1], "description": r[2]} for r in rows]
        except Exception as exc:  # noqa: BLE001
            logger.debug("proposal links: BOQ skipped: %s", exc)
        return rfis, positions

    async def propose(self, row: MeetingRecording, meeting: Meeting, user_id: str | None) -> MeetingRecording:
        """Build the AI (or heuristic) proposals for review. Replaces pending ones."""
        transcript = audio_logic.render_transcript(row.segments or [], row.speakers or {}, row.transcript)
        if not transcript.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="There is no transcript to build minutes from yet",
            )
        terms = await self._term_dicts(meeting.project_id)
        people = await self._people(meeting, row)
        language = row.language or await self.meeting_language(meeting)
        llm_result = await run_proposal_llm(
            self.session,
            user_id,
            build_proposal_prompt(
                transcript, audio_logic.build_glossary_block(terms), [p["name"] for p in people], language
            ),
        )
        heuristic = None
        if llm_result is None:
            from app.modules.meetings.router import _extract_meeting_data_heuristic, _parse_plain_text

            heuristic = _extract_meeting_data_heuristic(_parse_plain_text(transcript), "transcript.txt", transcript)
        rfis, positions = await self._link_targets(meeting.project_id)
        fresh = audio_logic.build_proposals(
            llm_result,
            heuristic=heuristic,
            people=people,
            rfis=rfis,
            positions=positions,
            meeting_date=meeting.meeting_date,
            transcript=row.transcript,
            glossary=terms,
            language=language,
        )
        # Reviewed items stay on record; only pending ones are replaced.
        kept = [i for i in (row.proposals or {}).get("items") or [] if i.get("status") != "pending"]
        for idx, item in enumerate(fresh["items"], start=len(kept) + 1):
            item["id"] = f"{item['kind'][0]}{idx}"
        fresh["items"] = kept + fresh["items"]
        row.proposals = fresh
        await self.session.flush()
        await self.session.refresh(row)
        return row

    async def review(
        self,
        row: MeetingRecording,
        meeting: Meeting,
        req: ProposalReviewRequest,
        user_id: str | None,
    ) -> dict[str, Any]:
        """Apply confirmed proposals through the existing services, record verdicts."""
        from app.modules.meetings.schemas import ActionRegisterItemCreate
        from app.modules.meetings.service import MeetingService

        proposals = dict(row.proposals or {})
        items = [dict(i) for i in proposals.get("items") or []]
        by_id = {i.get("id"): i for i in items}
        ai_generated = bool(proposals.get("ai_generated"))
        meeting_svc = MeetingService(self.session)
        confirmed = rejected = 0
        actions_created: list[str] = []
        tasks_created: list[str] = []
        errors: list[dict[str, str]] = []
        meta = dict(meeting.metadata_ or {})
        summary_parts: list[str] = []

        for edit in req.items:
            item = by_id.get(edit.id)
            if item is None or item.get("status") != "pending":
                errors.append({"id": edit.id, "error": "not a pending proposal"})
                continue
            if edit.decision == "reject":
                item["status"] = "rejected"
                rejected += 1
                await self._feedback(user_id, meeting.project_id, row.id, item, correct=False, enabled=ai_generated)
                continue
            merged = audio_logic.merge_review(item, edit.model_dump(exclude_unset=True))
            kind = merged.get("kind")
            if kind == "action":
                problems = audio_logic.action_confirm_problems(merged)
                if problems:
                    errors.append({"id": edit.id, "error": " ".join(problems)})
                    continue
                action = await meeting_svc.add_action(
                    meeting,
                    ActionRegisterItemCreate(
                        description=merged["text"][:1000],
                        owner_id=merged.get("owner_contact_id"),
                        owner_name=merged.get("owner_name") or None,
                        due_date=merged["due_date"],
                        status="open",
                    ),
                    user_id=user_id,
                )
                action_row = await meeting_svc.get_action(uuid.UUID(str(action["id"])))
                action_row.metadata_ = {
                    **(action_row.metadata_ or {}),
                    "source": "ai_minutes" if ai_generated else "transcript",
                    "recording_id": str(row.id),
                    "confidence": merged.get("confidence"),
                    "linked_entity": merged.get("linked_entity"),
                }
                merged["applied"] = {"action_id": str(action_row.id)}
                actions_created.append(str(action_row.id))
                if req.create_tasks:
                    task_id = await self._create_task(meeting, merged, user_id)
                    if task_id:
                        merged["applied"]["task_id"] = task_id
                        action_row.metadata_ = {**action_row.metadata_, "task_id": task_id}
                        tasks_created.append(task_id)
            elif kind == "summary":
                summary_parts.append(merged["text"])
            elif kind == "decision":
                decisions = list(meta.get("decisions") or [])
                decisions.append({"decision": merged["text"], "made_by": "", "source": "ai_minutes"})
                meta["decisions"] = decisions
            elif kind == "question":
                questions = list(meta.get("open_questions") or [])
                questions.append({"question": merged["text"], "source": "ai_minutes"})
                meta["open_questions"] = questions
            elif kind == "correction":
                heard, term = str(merged.get("heard") or ""), str(merged.get("term") or "")
                row.transcript, n = audio_logic.apply_correction(row.transcript, heard, term)
                segments = []
                for seg in row.segments or []:
                    text, m = audio_logic.apply_correction(str(seg.get("text") or ""), heard, term)
                    segments.append({**seg, "text": text})
                    n += m
                row.segments = segments
                merged["applied"] = {"replacements": n}
            merged["status"] = "confirmed"
            merged["reviewed_by"] = user_id
            merged["reviewed_at"] = datetime.now(UTC).isoformat()
            by_id[edit.id].clear()
            by_id[edit.id].update(merged)
            confirmed += 1
            await self._feedback(user_id, meeting.project_id, row.id, item, correct=True, enabled=ai_generated)

        if summary_parts:
            existing = (meeting.minutes or "").strip()
            meeting.minutes = "\n\n".join([p for p in [existing, *summary_parts] if p])[:100_000]
        meeting.metadata_ = meta
        proposals["items"] = items
        row.proposals = proposals
        await self.session.flush()
        await self.session.refresh(row)
        if confirmed or rejected:
            publish_after_commit(
                self.session,
                "meeting.minutes_proposals_reviewed",
                {
                    "meeting_id": str(meeting.id),
                    "project_id": str(meeting.project_id),
                    "recording_id": str(row.id),
                    "confirmed": confirmed,
                    "rejected": rejected,
                    "action_ids": actions_created,
                    "task_ids": tasks_created,
                },
                source_module="meetings",
            )
        return {
            "confirmed": confirmed,
            "rejected": rejected,
            "actions_created": actions_created,
            "tasks_created": tasks_created,
            "errors": errors,
        }

    async def _create_task(self, meeting: Meeting, item: dict[str, Any], user_id: str | None) -> str | None:
        """Open a task for a confirmed action through the Tasks service."""
        try:
            from app.modules.tasks.schemas import TaskCreate
            from app.modules.tasks.service import TaskService
        except Exception:  # noqa: BLE001 - tasks module optional
            return None
        link = item.get("linked_entity") or None
        contact = item.get("owner_contact_id")
        metadata: dict[str, Any] = {"source": "meeting_minutes_audio", "meeting_number": meeting.meeting_number}
        if link:
            metadata["linked_entity"] = link
        if not contact and item.get("owner_name"):
            metadata["assignee_name"] = item["owner_name"]
        try:
            async with self.session.begin_nested():
                task = await TaskService(self.session).create_task(
                    TaskCreate(
                        project_id=meeting.project_id,
                        task_type="task",
                        title=str(item["text"])[:500],
                        description=f"{meeting.meeting_number}: {meeting.title}"[:5000],
                        due_date=item.get("due_date"),
                        meeting_id=str(meeting.id),
                        status="open",
                        metadata=metadata,
                        assignee_contact_id=uuid.UUID(contact) if contact and _is_uuid(contact) else None,
                    ),
                    user_id=user_id,
                )
        except HTTPException as exc:
            logger.info("Task for meeting action not created: %s", exc.detail)
            return None
        except Exception:  # noqa: BLE001 - the action stays even when the task fails
            logger.exception("Task for meeting action not created")
            return None
        return str(task.id)

    async def validate_meeting(self, meeting: Meeting) -> Any:
        """Run the ``meetings`` rule set over one meeting: actions, minutes, recordings."""
        from app.core.validation.engine import validation_engine
        from app.modules.meetings.service import MeetingService

        meeting_svc = MeetingService(self.session)
        own, _brought = await meeting_svc.list_meeting_actions(meeting)
        minutes = await meeting_svc.get_minutes_row(meeting.id)
        recordings = [
            {
                "id": str(r.id),
                "source": r.source,
                "audio_storage_key": r.audio_storage_key,
                "audio_expires_at": r.audio_expires_at,
                "consent_confirmed_at": r.consent_confirmed_at.isoformat() if r.consent_confirmed_at else None,
                "proposals": r.proposals or {},
            }
            for r in await self.recordings.list_for_meeting(meeting.id)
        ]
        return await validation_engine.validate(
            data={
                "action_items": own,
                "content": (minutes.content if minutes is not None and isinstance(minutes.content, dict) else {}),
                "recordings": recordings,
            },
            rule_sets=["meetings"],
            target_type="meeting",
            target_id=str(meeting.id),
            project_id=str(meeting.project_id),
        )

    async def _feedback(
        self,
        user_id: str | None,
        project_id: uuid.UUID,
        recording_id: uuid.UUID,
        item: dict[str, Any],
        *,
        correct: bool,
        enabled: bool,
    ) -> None:
        """Record the verdict in the AI accuracy loop (AI-made proposals only)."""
        if not enabled or not _is_uuid(user_id):
            return
        try:
            from app.modules.ai_agents.accuracy_service import record_ai_feedback

            async with self.session.begin_nested():
                await record_ai_feedback(
                    self.session,
                    user_id=uuid.UUID(str(user_id)),
                    surface=AI_FEEDBACK_SURFACE,
                    correct=correct,
                    project_id=project_id,
                    ref=f"{recording_id}:{item.get('id')}:{item.get('kind')}",
                )
        except Exception as exc:  # noqa: BLE001 - feedback is best effort
            logger.debug("AI feedback not recorded: %s", exc)


async def prune_expired_meeting_audio(session: AsyncSession, *, now: datetime | None = None) -> int:
    """Delete meeting audio past its expiry. Returns how many were removed; caller commits."""
    svc = MeetingAudioService(session)
    removed = 0
    for row in await svc.recordings.list_expired_audio(now or datetime.now(UTC)):
        await svc.delete_audio(row)
        if not row.audio_storage_key:
            removed += 1
    if removed:
        logger.info("meetings audio retention: removed %d recordings", removed)
    return removed
