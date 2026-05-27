# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Field Diary — business logic.

Encapsulates the diary FSM (draft → submitted → approved), the dedicated
field-module grant check (BYPASSES the standard RBAC stack), and the
PIN-gated magic-link auth flow.

All tokens are stored as ``sha256(plaintext)`` hex digests; plaintext is
emitted to the field worker exactly once (via SMS in production, via the
HTTP response body in dev/test for the consume flow).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.modules.field_diary.models import (
    DiaryActivity,
    DiaryAttachment,
    DiaryEntry,
    FieldMagicLink,
    FieldModuleGrant,
    FieldSession,
)
from app.modules.field_diary.repository import (
    DiaryActivityRepository,
    DiaryAttachmentRepository,
    DiaryEntryRepository,
    FieldMagicLinkRepository,
    FieldModuleGrantRepository,
    FieldSessionRepository,
)
from app.modules.field_diary.schemas import (
    DIARY_STATUSES,
    DiaryActivityCreate,
    DiaryEntryCreate,
    DiaryEntryUpdate,
    FieldModuleGrantCreate,
)

logger = logging.getLogger(__name__)

# ── Tunables ──────────────────────────────────────────────────────────────

MAGIC_LINK_TTL = timedelta(minutes=15)
SESSION_TTL = timedelta(days=30)  # field workers stay logged in for weeks
PIN_MAX_ATTEMPTS = 5

# ── Pure helpers ──────────────────────────────────────────────────────────


def now_utc() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(UTC)


def generate_token() -> str:
    """Generate a 64-hex-char random token (32 bytes of entropy)."""
    return secrets.token_hex(32)


def generate_pin() -> str:
    """Generate a 6-digit numeric PIN as a zero-padded string.

    ``secrets.randbelow(1_000_000)`` gives a uniform integer in
    ``[0, 1_000_000)``; zero-padding turns ``42`` into ``"000042"``
    so the field worker always sees six digits in the SMS.
    """
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_token(plain: str) -> str:
    """SHA-256 hex digest of a token / PIN."""
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    """Constant-time string equality via :func:`hmac.compare_digest`."""
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def _ensure_aware(dt: datetime | None) -> datetime | None:
    """Coerce a naive datetime from SQLite into UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


# ── In-memory SMS sink for dev/test ───────────────────────────────────────


_SMS_LOG: list[dict[str, Any]] = []


def _send_sms(phone: str, body: str) -> None:
    """Stand-in SMS sender for the MVP.

    In production this dispatches via Twilio / MessageBird / etc.; here
    we simply log it AND append to an in-process list so the test suite
    can assert on the payload without monkey-patching the network.
    """
    _SMS_LOG.append({"phone": phone, "body": body, "sent_at": now_utc()})
    logger.info(
        "[field_diary][SMS-MOCK] to=%s body=%s",
        phone,
        body.replace("\n", " | "),
    )


def get_sms_log() -> list[dict[str, Any]]:
    """Return the in-memory SMS log (test introspection)."""
    return list(_SMS_LOG)


def clear_sms_log() -> None:
    """Empty the in-memory SMS log (used between tests)."""
    _SMS_LOG.clear()


# ── Service ───────────────────────────────────────────────────────────────


class FieldDiaryService:
    """Business logic for diary entries, grants, and the PIN-gated auth flow."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.entry_repo = DiaryEntryRepository(session)
        self.activity_repo = DiaryActivityRepository(session)
        self.attachment_repo = DiaryAttachmentRepository(session)
        self.grant_repo = FieldModuleGrantRepository(session)
        self.magic_repo = FieldMagicLinkRepository(session)
        self.session_repo = FieldSessionRepository(session)

    # ── Field module grant ────────────────────────────────────────────────

    async def check_module_grant(
        self,
        user_id: uuid.UUID,
        project_id: uuid.UUID,
        module_key: str = "field_diary",
    ) -> bool:
        """Return ``True`` iff a live non-expired grant row exists.

        Independent from the standard RBAC stack — used to gate every
        field-diary endpoint via :class:`RequireFieldModuleGrant`.
        """
        grant = await self.grant_repo.get_active(user_id, project_id, module_key)
        if grant is None:
            return False
        expires_at = _ensure_aware(grant.expires_at)
        return not (expires_at is not None and expires_at < now_utc())

    async def create_grant(
        self,
        data: FieldModuleGrantCreate,
        *,
        granted_by: uuid.UUID | None = None,
    ) -> FieldModuleGrant:
        """Create a new grant.

        Raises 409 if a live grant for the same ``(user, project, module)``
        already exists — caller should revoke the old one first if they
        want to re-issue.
        """
        existing = await self.grant_repo.get_active(
            data.user_id,
            data.project_id,
            data.module_key,
        )
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=("An active grant already exists for this (user, project, module) tuple"),
            )
        grant = FieldModuleGrant(
            user_id=data.user_id,
            project_id=data.project_id,
            module_key=data.module_key,
            granted_by=granted_by,
            granted_at=now_utc(),
            expires_at=data.expires_at,
        )
        grant = await self.grant_repo.create(grant)
        event_bus.publish_detached(
            "field_diary.grant.created",
            {
                "grant_id": str(grant.id),
                "user_id": str(grant.user_id),
                "project_id": str(grant.project_id),
                "module_key": grant.module_key,
            },
            source_module="field_diary",
        )
        return grant

    async def revoke_grant(self, grant_id: uuid.UUID) -> None:
        ok = await self.grant_repo.revoke(grant_id, revoked_at=now_utc())
        if not ok:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Grant not found or already revoked",
            )

    # ── Diary entry FSM ───────────────────────────────────────────────────

    async def create_diary_entry(
        self,
        data: DiaryEntryCreate,
        *,
        author_id: uuid.UUID,
    ) -> DiaryEntry:
        """Create a draft entry. ``(project, author, date)`` is unique."""
        existing = await self.entry_repo.get_by_unique(
            data.project_id,
            author_id,
            data.entry_date,
        )
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(f"A diary entry for this author + date already exists ({existing.id})"),
            )
        entry = DiaryEntry(
            project_id=data.project_id,
            author_id=author_id,
            entry_date=data.entry_date,
            weather=data.weather,
            temperature_c=data.temperature_c,
            headcount=data.headcount,
            notes_md=data.notes_md,
            metadata_=data.metadata or {},
            status="draft",
        )
        entry = await self.entry_repo.create(entry)
        return entry

    async def get_diary_entry(self, entry_id: uuid.UUID) -> DiaryEntry:
        entry = await self.entry_repo.get_by_id(entry_id)
        if entry is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Diary entry not found",
            )
        return entry

    async def update_diary_entry(
        self,
        entry_id: uuid.UUID,
        data: DiaryEntryUpdate,
    ) -> DiaryEntry:
        """Patch a draft entry. Submitted / approved entries are read-only."""
        entry = await self.get_diary_entry(entry_id)
        if entry.status != "draft":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(f"Cannot edit a diary entry in status '{entry.status}' — only drafts are editable"),
            )
        fields = data.model_dump(exclude_unset=True)
        if fields:
            await self.entry_repo.update_fields(entry_id, **fields)
            await self.session.refresh(entry)
        return entry

    async def submit_diary_entry(
        self,
        entry_id: uuid.UUID,
    ) -> DiaryEntry:
        """Transition draft → submitted (idempotent).

        Validates that the entry has at least one of: notes, activities,
        attachments — i.e. is not empty.
        """
        entry = await self.get_diary_entry(entry_id)
        if entry.status == "submitted":
            return entry  # idempotent — same status, no-op
        if entry.status == "approved":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot re-submit an approved diary entry",
            )
        # Completeness guard.
        has_notes = bool((entry.notes_md or "").strip())
        activities = await self.activity_repo.list_for_entry(entry_id)
        attachments = await self.attachment_repo.list_for_entry(entry_id)
        if not (has_notes or activities or attachments):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=("Diary entry is empty — add notes, activities, or attachments before submitting"),
            )
        now = now_utc()
        await self.entry_repo.update_fields(
            entry_id,
            status="submitted",
            submitted_at=now,
        )
        await self.session.refresh(entry)
        event_bus.publish_detached(
            "field_diary.entry.submitted",
            {
                "entry_id": str(entry_id),
                "project_id": str(entry.project_id),
                "author_id": str(entry.author_id),
                "entry_date": entry.entry_date,
            },
            source_module="field_diary",
        )
        return entry

    async def approve_diary_entry(
        self,
        entry_id: uuid.UUID,
        *,
        approver_id: uuid.UUID,
    ) -> DiaryEntry:
        entry = await self.get_diary_entry(entry_id)
        if entry.status not in ("submitted", "approved"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(f"Only submitted entries can be approved (current status: {entry.status})"),
            )
        if entry.status == "approved":
            return entry  # idempotent
        prior_status = entry.status
        now = now_utc()
        await self.entry_repo.update_fields(
            entry_id,
            status="approved",
            approved_at=now,
            approved_by=approver_id,
        )
        await self.session.refresh(entry)

        # Epic H — universal audit trail.
        from app.core.audit_log import log_activity as _log_activity

        await _log_activity(
            self.session,
            actor_id=str(approver_id),
            entity_type="diary_entry",
            entity_id=str(entry_id),
            action="status_changed",
            from_status=prior_status,
            to_status="approved",
            reason="Daily diary entry approved",
            module="field_diary",
            parent_entity_type="project",
            parent_entity_id=str(entry.project_id),
            before_state={"status": prior_status},
            after_state={"status": "approved"},
        )

        return entry

    async def list_diary_entries(
        self,
        project_id: uuid.UUID,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[DiaryEntry]:
        return await self.entry_repo.list_for_project(
            project_id,
            date_from=date_from,
            date_to=date_to,
            offset=offset,
            limit=limit,
        )

    # ── Activities ────────────────────────────────────────────────────────

    async def append_activity(
        self,
        entry_id: uuid.UUID,
        data: DiaryActivityCreate,
    ) -> DiaryActivity:
        entry = await self.get_diary_entry(entry_id)
        if entry.status == "approved":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot append activities to an approved entry",
            )
        activity = DiaryActivity(
            entry_id=entry_id,
            activity_type=data.activity_type,
            description=data.description,
            hours=data.hours,
            location=data.location,
            started_at=data.started_at,
            ended_at=data.ended_at,
            metadata_=data.metadata or {},
        )
        return await self.activity_repo.create(activity)

    # ── Attachments ───────────────────────────────────────────────────────

    async def register_attachment(
        self,
        entry_id: uuid.UUID,
        *,
        filename: str,
        mime_type: str,
        size_bytes: int,
        storage_key: str,
        uploaded_by: uuid.UUID,
    ) -> DiaryAttachment:
        entry = await self.get_diary_entry(entry_id)
        if entry.status == "approved":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot attach files to an approved entry",
            )
        attachment = DiaryAttachment(
            entry_id=entry_id,
            filename=filename,
            mime_type=mime_type,
            size_bytes=size_bytes,
            storage_key=storage_key,
            uploaded_by=uploaded_by,
        )
        return await self.attachment_repo.create(attachment)

    # ── PIN-gated magic-link auth ─────────────────────────────────────────

    async def request_magic_link(
        self,
        *,
        phone: str,
        project_id: uuid.UUID,
        module_key: str = "field_diary",
        user_id: uuid.UUID,
    ) -> tuple[FieldMagicLink, str, str]:
        """Mint a magic link + PIN, dispatch the (mocked) SMS.

        Returns ``(link, plain_token, plain_pin)``. Plaintext is shown
        exactly once — only the SHA-256 hashes are persisted.
        """
        plain_token = generate_token()
        plain_pin = generate_pin()
        expires_at = now_utc() + MAGIC_LINK_TTL

        link = FieldMagicLink(
            user_id=user_id,
            project_id=project_id,
            module_key=module_key,
            phone=phone,
            token_hash=hash_token(plain_token),
            pin_hash=hash_token(plain_pin),
            expires_at=expires_at,
        )
        link = await self.magic_repo.create(link)

        # Mock SMS dispatch — production wires Twilio here.
        sms_body = (
            f"OpenConstructionERP field link:\n"
            f"https://app.example.com/f/{plain_token}\n"
            f"PIN: {plain_pin}\n"
            f"Expires in {int(MAGIC_LINK_TTL.total_seconds() // 60)} min."
        )
        _send_sms(phone, sms_body)

        return link, plain_token, plain_pin

    async def consume_magic_link(
        self,
        *,
        token: str,
        pin: str,
    ) -> tuple[FieldSession, str]:
        """Consume the link, verify the PIN, open a session.

        Returns ``(session, plain_session_token)``.

        Errors:
            - 401 unknown token
            - 400 expired / already-consumed
            - 401 wrong PIN (5 attempts → link invalidated)
        """
        token_h = hash_token(token)
        link = await self.magic_repo.get_by_token_hash(token_h)
        if link is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid magic link",
            )

        # Constant-time equality on the persisted hash — paranoia layer
        # in case the lookup is ever loosened.
        if not constant_time_equals(link.token_hash, token_h):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid magic link",
            )
        if link.consumed_at is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Magic link already consumed",
            )
        expires_at = _ensure_aware(link.expires_at)
        now = now_utc()
        if expires_at is not None and expires_at < now:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Magic link expired",
            )

        # Snapshot scalars before any write that could trigger expire_all().
        link_id = link.id
        link_user_id = link.user_id
        link_project_id = link.project_id
        link_module_key = link.module_key
        link_pin_hash = link.pin_hash

        # PIN verification with throttling.
        if not constant_time_equals(link_pin_hash, hash_token(pin)):
            new_attempts = link.pin_attempts + 1
            if new_attempts >= PIN_MAX_ATTEMPTS:
                # Burn the link so the brute-force window closes.
                await self.magic_repo.update_fields(
                    link_id,
                    pin_attempts=new_attempts,
                    consumed_at=now,
                )
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=("Too many failed PIN attempts — magic link invalidated"),
                )
            await self.magic_repo.update_fields(
                link_id,
                pin_attempts=new_attempts,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid PIN",
            )

        # Mark link consumed and open the session.
        await self.magic_repo.update_fields(link_id, consumed_at=now)

        plain_session = generate_token()
        sess = FieldSession(
            user_id=link_user_id,
            project_id=link_project_id,
            module_key=link_module_key,
            session_token_hash=hash_token(plain_session),
            pin_hash=link_pin_hash,
            expires_at=now + SESSION_TTL,
            last_seen_at=now,
        )
        sess = await self.session_repo.create(sess)
        return sess, plain_session

    async def verify_session(
        self,
        session_token: str,
        pin: str,
    ) -> FieldSession | None:
        """Validate a field session by bearer token + PIN.

        Returns the live session on success, ``None`` otherwise. Touches
        ``last_seen_at`` for traffic accounting.
        """
        if not session_token or not pin:
            return None
        token_h = hash_token(session_token)
        sess = await self.session_repo.get_by_token_hash(token_h)
        if sess is None:
            return None
        if sess.revoked_at is not None:
            return None
        expires_at = _ensure_aware(sess.expires_at)
        if expires_at is not None and expires_at < now_utc():
            return None
        if not constant_time_equals(sess.session_token_hash, token_h):
            return None
        if not constant_time_equals(sess.pin_hash, hash_token(pin)):
            return None

        sess_id = sess.id
        await self.session_repo.update_fields(sess_id, last_seen_at=now_utc())
        return sess


__all__ = [
    "DIARY_STATUSES",
    "MAGIC_LINK_TTL",
    "PIN_MAX_ATTEMPTS",
    "SESSION_TTL",
    "FieldDiaryService",
    "clear_sms_log",
    "constant_time_equals",
    "generate_pin",
    "generate_token",
    "get_sms_log",
    "hash_token",
    "now_utc",
]
