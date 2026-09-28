# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Record Publishing service - one-tap "publish a record and distribute it".

A project accumulates contemporaneous records - the daily site diary today,
meeting minutes and inspection reports next - that periodically need to leave
the platform as a single signed PDF sent to a named set of people who then
acknowledge receipt. Historically that was three manual steps (render the
record, upload it as a file, raise a transmittal). This service collapses them
into one action.

It is a thin orchestrator over primitives that already exist, so it needs no
new tables:

* Each record kind registers a *renderer* that turns a source id into
  ``RenderedRecord`` (project, subject, canonical name, PDF bytes). The daily
  diary renderer reuses ``DailyDiaryService.generate_diary_pdf``.
* The rendered PDF is stored under the transmittal's own storage prefix via the
  platform storage backend.
* A ``file_transmittals`` transmittal carries the formal send-record: the cover
  sheet, the recipient list, and the single-use acknowledgement tokens. Those
  tokens double as the bearer credential an external recipient uses to fetch the
  published PDF, mirroring the public acknowledgement endpoint.
* An optional saved ``file_distribution`` list can be expanded into recipients
  so a user can send to a reusable group in one click.

Cross-module reads are lazy imports so this module never hard-couples to the
source modules or the transmittals engine at import time.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException, status
from sqlalchemy import select

from app.modules.file_transmittals.models import FileTransmittalRecipient
from app.modules.file_transmittals.schemas import (
    TransmittalCreate,
    TransmittalItemCreate,
    TransmittalRecipientCreate,
)
from app.modules.file_transmittals.service import TransmittalService

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.record_publishing.schemas import PublishRecordRequest

logger = logging.getLogger(__name__)

# Storage prefix for the rendered record PDFs. One object per transmittal:
# ``published_records/{project_id}/{transmittal_id}.pdf``.
_RECORD_KEY_PREFIX = "published_records"
# Transmittal item kind for a published record (a generated report artefact).
_RECORD_FILE_KIND = "report"

# Same-origin URL templates the caller forwards to recipients. The ack URL is
# the public acknowledgement endpoint on the transmittals module; the record URL
# is this module's own token-gated download.
_ACK_URL_TEMPLATE = "/api/v1/file-transmittals/ack/{token}/"
_RECORD_URL_TEMPLATE = "/api/v1/record-publishing/record/{token}"


# ── Renderer contract ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class RenderedRecord:
    """The output of a per-kind record renderer.

    Attributes:
        project_id: Owning project (never taken from the client - always
            resolved from the source record so a caller cannot publish one
            project's record into another).
        subject: Human-readable transmittal subject.
        canonical_name: Download filename for the PDF (already sanitised).
        pdf_bytes: The rendered document (starts with ``b"%PDF"``).
        source_kind: The record kind that produced this.
        source_id: The source record id as a string.
    """

    project_id: uuid.UUID
    subject: str
    canonical_name: str
    pdf_bytes: bytes
    source_kind: str
    source_id: str


@dataclass(frozen=True)
class RecordSource:
    """A registered record kind: how to render it plus an optional after-hook.

    ``render`` resolves a source id to a :class:`RenderedRecord`. ``on_published``
    (when set) runs after a successful send with ``(session, source_id,
    transmittal_id)`` so the source record can record where it was published; it
    is best-effort and must never block the publish.
    """

    kind: str
    label: str
    render: Callable[[AsyncSession, uuid.UUID], Awaitable[RenderedRecord]]
    on_published: Callable[[AsyncSession, uuid.UUID, uuid.UUID], Awaitable[None]] | None = None


# ── Pure helpers (DB-free, unit-testable) ──────────────────────────────────


def record_storage_key(project_id: uuid.UUID | str, transmittal_id: uuid.UUID | str) -> str:
    """Build the deterministic storage key for a published record PDF."""
    return f"{_RECORD_KEY_PREFIX}/{project_id}/{transmittal_id}.pdf"


def ack_url(token: str) -> str:
    """Public acknowledgement URL for a recipient token."""
    return _ACK_URL_TEMPLATE.format(token=token)


def record_url(token: str) -> str:
    """Token-gated record download URL for a recipient token."""
    return _RECORD_URL_TEMPLATE.format(token=token)


def safe_filename(name: str, *, fallback: str = "record.pdf") -> str:
    """Sanitise ``name`` into a safe attachment filename ending in ``.pdf``.

    Keeps alphanumerics, dash, underscore and dot; collapses everything else to
    a single dash so a subject with slashes or quotes cannot break the
    ``Content-Disposition`` header. Always returns a non-empty ``*.pdf`` name.
    """
    raw = (name or "").strip()
    if not raw:
        return fallback
    cleaned_chars = [c if (c.isalnum() or c in ("-", "_", ".")) else "-" for c in raw]
    cleaned = "".join(cleaned_chars).strip("-._")
    # Collapse runs of dashes for readability.
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    if not cleaned:
        return fallback
    if not cleaned.lower().endswith(".pdf"):
        cleaned = f"{cleaned}.pdf"
    return cleaned[:255]


def _slugify(text: str) -> str:
    """Lower-case dash slug used to build canonical record filenames."""
    lowered = (text or "").strip().lower()
    out = [c if (c.isalnum() or c in ("-", "_")) else "-" for c in lowered]
    slug = "".join(out).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug


# ── Renderers + after-hooks (one per kind) ─────────────────────────────────


async def _render_daily_diary(session: AsyncSession, source_id: uuid.UUID) -> RenderedRecord:
    """Render a daily site diary into a distributable record PDF."""
    from app.modules.daily_diary.service import DailyDiaryService

    diary_service = DailyDiaryService(session)
    diary = await diary_service.get_diary(source_id)  # raises 404 when missing
    pdf_bytes, diary_date = await diary_service.generate_diary_pdf(source_id)
    label = "Daily Site Diary"
    subject = f"{label} - {diary_date}" if diary_date else label
    canonical = safe_filename(f"{_slugify(label)}-{_slugify(str(diary_date))}")
    return RenderedRecord(
        project_id=diary.project_id,
        subject=subject[:255],
        canonical_name=canonical,
        pdf_bytes=pdf_bytes,
        source_kind="daily_diary",
        source_id=str(source_id),
    )


async def _on_daily_diary_published(
    session: AsyncSession,
    source_id: uuid.UUID,
    transmittal_id: uuid.UUID,
) -> None:
    """Point the diary's ``pdf_export_ref`` at the transmittal that published it.

    ``pdf_export_ref`` shipped as a nullable soft-link that nothing ever set;
    wiring it here turns the diary into a record that knows where it was last
    published and distributed. Best-effort: a failure here never fails the
    publish, and ``pdf_export_ref`` is not part of the diary's immutable content
    hash, so setting it does not disturb a signed snapshot.
    """
    from app.modules.daily_diary.repository import DailyDiaryRepository

    try:
        await DailyDiaryRepository(session).update_fields(source_id, pdf_export_ref=transmittal_id)
    except Exception:  # noqa: BLE001 - best-effort back-reference
        logger.debug("Could not set diary %s pdf_export_ref after publish", source_id, exc_info=True)


async def _render_meeting_minutes(session: AsyncSession, source_id: uuid.UUID) -> RenderedRecord:
    """Render a meeting's confirmed minutes into a distributable record PDF.

    Publishes the human-confirmed minutes document, not the raw meeting row, so
    a caller cannot distribute a meeting that has not had its minutes drafted
    yet (422). Reuses the same ``build_minutes_pdf`` renderer as the meetings
    export endpoint, so the distributed PDF is byte-for-byte the export.
    """
    from app.modules.meetings.pdf import build_minutes_pdf, minutes_pdf_filename
    from app.modules.meetings.service import MeetingService
    from app.modules.projects.models import Project

    meeting = await MeetingService(session).get_meeting(source_id)  # raises 404 when missing
    minutes = await MeetingService(session).get_minutes_row(source_id)
    if minutes is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="This meeting has no confirmed minutes to publish yet",
        )

    proj_name = (
        await session.execute(select(Project.name).where(Project.id == meeting.project_id))
    ).scalar_one_or_none() or "Unknown Project"
    content = minutes.content if isinstance(minutes.content, dict) else {}
    # Plain snapshots of the fields the renderer reads, so no ORM row crosses into
    # the thread. Laying out the PDF is pure CPU, so it runs in a worker thread.
    meeting_snapshot = SimpleNamespace(
        title=meeting.title,
        meeting_date=meeting.meeting_date,
        meeting_number=meeting.meeting_number,
    )
    minutes_snapshot = SimpleNamespace(
        content=minutes.content,
        status=minutes.status,
        issued_at=minutes.issued_at,
    )
    pdf_bytes = await asyncio.to_thread(build_minutes_pdf, meeting_snapshot, minutes_snapshot, proj_name)

    number = str(content.get("meeting_number") or meeting.meeting_number or "").strip()
    title = str(content.get("title") or meeting.title or "").strip()
    subject = "Meeting Minutes"
    if number:
        subject = f"{subject} - #{number}"
    if title:
        subject = f"{subject}: {title}"
    return RenderedRecord(
        project_id=meeting.project_id,
        subject=subject[:255],
        canonical_name=safe_filename(minutes_pdf_filename(meeting, content)),
        pdf_bytes=pdf_bytes,
        source_kind="meeting",
        source_id=str(source_id),
    )


# Registry of publishable record kinds. Adding a kind (inspections next) is one
# entry here plus a renderer - the router, storage and distribution flow are all
# kind-agnostic.
_RECORD_SOURCES: dict[str, RecordSource] = {
    "daily_diary": RecordSource(
        kind="daily_diary",
        label="Daily Site Diary",
        render=_render_daily_diary,
        on_published=_on_daily_diary_published,
    ),
    "meeting": RecordSource(
        kind="meeting",
        label="Meeting Minutes",
        render=_render_meeting_minutes,
        on_published=None,
    ),
}


def supported_kinds() -> list[str]:
    """Return the record kinds that can currently be published, sorted."""
    return sorted(_RECORD_SOURCES)


# ── Service ─────────────────────────────────────────────────────────────────


class RecordPublishingService:
    """Orchestrates render -> store -> transmit for a project record."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def publish_and_distribute(
        self,
        req: PublishRecordRequest,
        *,
        user_id: str,
    ) -> dict[str, Any]:
        """Render a record, store it, and send it as an acknowledged transmittal.

        Returns a plain dict payload (the router maps it to the response model).
        Raises 422 for an unknown kind or an empty recipient set, and 404 when
        the source record, its project, or a named distribution list is not
        accessible to the caller.
        """
        source = _RECORD_SOURCES.get(req.source_kind)
        if source is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unsupported record kind '{req.source_kind}'",
            )

        rendered = await source.render(self.session, req.source_id)

        # IDOR guard: the caller must be able to reach the record's project.
        from app.dependencies import verify_project_access

        await verify_project_access(rendered.project_id, user_id, self.session)

        recipients = await self._collect_recipients(req, user_id)
        if not recipients:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="At least one recipient is required to publish and distribute a record",
            )

        tx_service = TransmittalService(self.session)
        create = TransmittalCreate(
            project_id=rendered.project_id,
            subject=rendered.subject,
            reason_code=req.reason_code,
            notes=req.notes,
            items=[
                TransmittalItemCreate(
                    file_kind=_RECORD_FILE_KIND,
                    file_id=rendered.source_id[:64],
                    canonical_name_snapshot=rendered.canonical_name,
                )
            ],
            recipients=recipients,
        )
        transmittal = await tx_service.create_draft(create, sender_id=user_id)

        # Persist the rendered PDF BEFORE sending: a storage failure here rolls
        # the whole (still-uncommitted) transaction back rather than leaving a
        # sent transmittal whose record download would 404.
        from app.core.storage import get_storage_backend

        key = record_storage_key(rendered.project_id, transmittal.id)
        await get_storage_backend().put(key, rendered.pdf_bytes)

        # Send: flips draft -> sent, mints ack tokens, writes the cover sheet.
        transmittal = await tx_service.send(transmittal.id)

        # Extract the response payload NOW, while the ORM state is fresh - the
        # after-hook below may expire attributes on write.
        payload = self._build_payload(transmittal, rendered)

        if source.on_published is not None:
            await source.on_published(self.session, req.source_id, transmittal.id)

        await self._record_audit(rendered, transmittal.id, transmittal.number, len(recipients), req.locale, user_id)
        await self.session.commit()
        return payload

    async def read_record(self, transmittal_id: uuid.UUID, user_id: str) -> tuple[bytes, str, str]:
        """Return ``(bytes, media_type, filename)`` for a project member."""
        transmittal = await TransmittalService(self.session).get(transmittal_id)

        from app.dependencies import verify_project_access

        await verify_project_access(transmittal.project_id, user_id, self.session)
        return await self._read_stored(transmittal)

    async def read_record_by_token(self, token: str) -> tuple[bytes, str, str]:
        """Return ``(bytes, media_type, filename)`` for a recipient token.

        Public, token-gated: the ack token minted for a recipient doubles as the
        bearer credential for the published PDF, mirroring the public
        acknowledgement endpoint on the transmittals module.
        """
        if not token:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid record token")
        stmt = select(FileTransmittalRecipient).where(FileTransmittalRecipient.acknowledge_token == token)
        recipient = (await self.session.execute(stmt)).scalar_one_or_none()
        if recipient is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid record token")
        transmittal = await TransmittalService(self.session).get(recipient.transmittal_id)
        return await self._read_stored(transmittal)

    # ── Internals ──────────────────────────────────────────────────────────

    async def _read_stored(self, transmittal: Any) -> tuple[bytes, str, str]:  # noqa: ANN401 - ORM row
        from app.core.storage import get_storage_backend

        key = record_storage_key(transmittal.project_id, transmittal.id)
        try:
            data = await get_storage_backend().get(key)
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Published record file is no longer available",
            ) from exc
        canonical = transmittal.items[0].canonical_name_snapshot if transmittal.items else None
        filename = safe_filename(canonical or f"record-{transmittal.number}")
        return data, "application/pdf", filename

    async def _collect_recipients(
        self,
        req: PublishRecordRequest,
        user_id: str,
    ) -> list[TransmittalRecipientCreate]:
        """Merge explicit recipients with an optional saved distribution list.

        De-duplicated by lower-cased email, explicit recipients winning. Invalid
        member emails from a stored list are skipped rather than failing the
        whole publish.
        """
        seen: set[str] = set()
        out: list[TransmittalRecipientCreate] = []
        for r in req.recipients:
            email = str(r.email).lower()
            if email in seen:
                continue
            seen.add(email)
            out.append(TransmittalRecipientCreate(email=r.email, display_name=r.display_name, role=r.role))

        if req.distribution_list_id is not None:
            for member in await self._load_distribution_members(req.distribution_list_id, user_id):
                email = str(getattr(member, "email", "") or "").lower()
                if not email or email in seen:
                    continue
                try:
                    row = TransmittalRecipientCreate(
                        email=member.email,
                        display_name=getattr(member, "display_name", None),
                        role=getattr(member, "role", None),
                    )
                except Exception:  # noqa: BLE001 - skip a malformed stored address
                    logger.debug("Skipping distribution member with invalid email", exc_info=True)
                    continue
                seen.add(email)
                out.append(row)
        return out

    async def _load_distribution_members(self, list_id: uuid.UUID, user_id: str) -> list[Any]:
        from app.modules.file_distribution.service import (
            DistributionListService,
            DistributionNotFoundError,
        )

        try:
            dist_list = await DistributionListService(self.session).get(list_id, uuid.UUID(str(user_id)))
        except DistributionNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Distribution list not found",
            ) from exc
        except (ValueError, TypeError):
            return []
        return list(getattr(dist_list, "members", []) or [])

    def _build_payload(self, transmittal: Any, rendered: RenderedRecord) -> dict[str, Any]:  # noqa: ANN401
        recipients: list[dict[str, Any]] = []
        for r in transmittal.recipients:
            token = r.acknowledge_token or ""
            recipients.append(
                {
                    "email": r.email,
                    "display_name": r.display_name,
                    "role": r.role,
                    "acknowledge_url": ack_url(token) if token else None,
                    "record_url": record_url(token) if token else None,
                }
            )
        return {
            "transmittal_id": transmittal.id,
            "transmittal_number": transmittal.number,
            "subject": transmittal.subject,
            "source_kind": rendered.source_kind,
            "source_id": rendered.source_id,
            "project_id": rendered.project_id,
            "record_filename": rendered.canonical_name,
            "cover_sheet_path": transmittal.cover_sheet_path,
            "recipient_count": len(recipients),
            "recipients": recipients,
        }

    async def _record_audit(
        self,
        rendered: RenderedRecord,
        transmittal_id: uuid.UUID,
        transmittal_number: str,
        recipient_count: int,
        locale: str | None,
        user_id: str,
    ) -> None:
        """Write a durable audit entry and fan out an event (both best-effort)."""
        try:
            from app.core.audit import audit_log

            await audit_log(
                self.session,
                action="record_published",
                entity_type="published_record",
                entity_id=str(transmittal_id),
                user_id=user_id,
                details={
                    "project_id": str(rendered.project_id),
                    "source_kind": rendered.source_kind,
                    "source_id": rendered.source_id,
                    "transmittal_number": transmittal_number,
                    "subject": rendered.subject[:200],
                    "recipient_count": recipient_count,
                    "locale": locale or "",
                },
            )
        except Exception:  # noqa: BLE001 - audit must never fail a publish
            logger.debug("audit_log failed for record publish", exc_info=True)

        try:
            from app.core.events import event_bus

            event_bus.publish_detached(
                "record.published",
                {
                    "transmittal_id": str(transmittal_id),
                    "project_id": str(rendered.project_id),
                    "source_kind": rendered.source_kind,
                    "source_id": rendered.source_id,
                    "recipient_count": recipient_count,
                    "user_id": user_id,
                },
                source_module="record_publishing",
            )
        except Exception:  # noqa: BLE001 - event fan-out is advisory
            logger.debug("record.published event publish failed", exc_info=True)
