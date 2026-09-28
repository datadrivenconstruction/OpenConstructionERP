# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Field Diary - business logic.

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
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.core.json_merge import merge_metadata
from app.modules.field_diary.models import (
    DiaryActivity,
    DiaryAttachment,
    DiaryEntry,
    FieldMagicLink,
    FieldModuleGrant,
    FieldSession,
    FieldSyncLedger,
)
from app.modules.field_diary.repository import (
    DiaryActivityRepository,
    DiaryAttachmentRepository,
    DiaryEntryRepository,
    FieldMagicLinkRepository,
    FieldModuleGrantRepository,
    FieldSessionRepository,
    FieldSyncLedgerRepository,
)
from app.modules.field_diary.schemas import (
    DIARY_STATUSES,
    DiaryActivityCreate,
    DiaryEntryCreate,
    DiaryEntryUpdate,
    FieldCapture,
    FieldCaptureResponse,
    FieldInspectionCreate,
    FieldModuleGrantCreate,
    FieldPunchCreate,
    FieldScheduleProgressCreate,
)

if TYPE_CHECKING:  # Typing only - the roster route imports this at call time so
    # a deployment without the resources module still loads this one.
    from app.modules.resources.models import Resource

logger = logging.getLogger(__name__)

# ── Tunables ──────────────────────────────────────────────────────────────

MAGIC_LINK_TTL = timedelta(minutes=15)
SESSION_TTL = timedelta(days=30)  # field workers stay logged in for weeks
PIN_MAX_ATTEMPTS = 5

# Resource kinds a foreman books hours against. A crew is on the list because
# the timesheet lets a crew carry hours as one row; equipment and
# subcontractor companies are not, they are not who a punch clock is for.
FIELD_ROSTER_KINDS = ("person", "crew")
# The roster is cached whole on the device, so it is capped. A site with more
# people than this has a register problem, not a phone problem, and the free
# text field still takes anybody the list has cut.
FIELD_ROSTER_LIMIT = 500

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
_SMS_LOG_MAX = 200


def dev_auth_secrets_exposed(settings: Any | None = None) -> bool:
    """Whether plaintext magic-link secrets may leave the server.

    True only when ``EXPOSE_DEV_AUTH_SECRETS`` is set explicitly and the
    deployment is not ``APP_ENV=production``. Deliberately independent of
    ``APP_DEBUG``: debug gets switched on to chase a problem, and that must
    never start handing field login tokens to whoever asks for one.
    """
    if settings is None:
        from app.config import get_settings

        settings = get_settings()
    return bool(getattr(settings, "expose_dev_auth_secrets", False)) and (
        getattr(settings, "app_env", "development") != "production"
    )


def _send_sms(phone: str, body: str) -> None:
    """Stand-in SMS sender for the MVP.

    In production this dispatches via Twilio / MessageBird / etc. The body
    carries a live login token and PIN, so it is only logged and kept in the
    in-process list (which the test suite reads) when dev secrets are
    explicitly exposed. Otherwise the log line records that an SMS was due
    and nothing that could be replayed.
    """
    if not dev_auth_secrets_exposed():
        logger.info("[field_diary][SMS-MOCK] to=%s body=<redacted, %d chars>", phone, len(body))
        return
    if len(_SMS_LOG) >= _SMS_LOG_MAX:
        del _SMS_LOG[: len(_SMS_LOG) - _SMS_LOG_MAX + 1]
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
        self.ledger_repo = FieldSyncLedgerRepository(session)

    # ── Field module grant ────────────────────────────────────────────────

    async def check_module_grant(
        self,
        user_id: uuid.UUID,
        project_id: uuid.UUID,
        module_key: str = "field_diary",
    ) -> bool:
        """Return ``True`` iff a live non-expired grant row exists.

        Independent from the standard RBAC stack - used to gate every
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
        already exists - caller should revoke the old one first if they
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
                detail=(f"Cannot edit a diary entry in status '{entry.status}' - only drafts are editable"),
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
        attachments - i.e. is not empty.
        """
        entry = await self.get_diary_entry(entry_id)
        if entry.status == "submitted":
            return entry  # idempotent - same status, no-op
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
                detail=("Diary entry is empty - add notes, activities, or attachments before submitting"),
            )
        project_id_s = str(entry.project_id)
        author_id_s = str(entry.author_id)
        entry_date_s = entry.entry_date

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
                "project_id": project_id_s,
                "author_id": author_id_s,
                "entry_date": entry_date_s,
            },
            source_module="field_diary",
        )

        # Hours are not costed here. Submitting says the worker is finished
        # writing, not that anyone has checked what they wrote, and these hours
        # land straight on a budget line's actuals. They now go out on approval
        # instead, which is the same rule the desktop timesheet has always had.
        return entry

    @staticmethod
    def _diary_labour_rows(activities: list[DiaryActivity]) -> list[dict[str, Any]]:
        """Build labour rows from a diary entry's work activities.

        Only ``work`` / ``inspection`` activities with positive ``hours``
        count as labour; delays, visits and incidents carry no payable
        hours. ``resource_id`` / ``cost_rate`` / ``currency`` are lifted
        from the activity metadata when present so the cost model can apply
        a resource rate deterministically.
        """
        rows: list[dict[str, Any]] = []
        for act in activities:
            if act.activity_type not in ("work", "inspection"):
                continue
            try:
                hours = float(act.hours) if act.hours is not None else 0.0
            except (TypeError, ValueError):
                hours = 0.0
            if hours <= 0.0:
                continue
            md = act.metadata_ if isinstance(act.metadata_, dict) else {}
            row: dict[str, Any] = {
                "worker_type": act.activity_type,
                "hours": round(hours, 4),
                "overtime_hours": 0.0,
                "headcount": 1,
            }
            if md.get("resource_id"):
                row["resource_id"] = str(md["resource_id"])
            if md.get("cost_rate") is not None:
                row["cost_rate"] = str(md["cost_rate"])
            if md.get("currency"):
                row["currency"] = str(md["currency"])
            rows.append(row)
        return rows

    async def approve_diary_entry(
        self,
        entry_id: uuid.UUID,
        *,
        approver_id: uuid.UUID,
    ) -> DiaryEntry:
        """Transition submitted → approved, and cost the hours (idempotent).

        Approval is where the work hours reach the cost model. They used to go
        out on submit, which meant a worker's own phone posted straight onto a
        budget line with nobody in between, on a screen where the crew is typed
        by hand. The desktop timesheet has always required a manager, and there
        is no reason the same hours captured on site should require less.

        The publish is marked on the entry so it happens once. Approving an
        entry twice, or approving one that was submitted while submit still
        published, does not cost the hours again.
        """
        entry = await self.get_diary_entry(entry_id)
        if entry.status not in ("submitted", "approved"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(f"Only submitted entries can be approved (current status: {entry.status})"),
            )
        if entry.status == "approved":
            return entry  # idempotent
        prior_status = entry.status

        # Snapshot the labour-bearing rows BEFORE update_fields() expires the
        # ORM state. Each work/inspection activity with positive hours becomes
        # a labour row; delays, visits and incidents carry no payable hours.
        activities = await self.activity_repo.list_for_entry(entry_id)
        labour_rows = self._diary_labour_rows(activities)
        already_published = entry.labour_published_at is not None
        project_id_s = str(entry.project_id)
        author_id_s = str(entry.author_id)
        entry_date_s = entry.entry_date

        now = now_utc()
        await self.entry_repo.update_fields(
            entry_id,
            status="approved",
            approved_at=now,
            approved_by=approver_id,
        )
        await self.session.refresh(entry)

        # Feed diary work hours into the shared labour-cost / payroll flow.
        # Best-effort: a rollup failure must not undo an approval the manager
        # has already made, so the mark is only set once the publish returns.
        if labour_rows and not already_published:
            try:
                from app.modules.field_diary.events import publish_diary_labour

                publish_diary_labour(
                    entry_id=str(entry_id),
                    project_id=project_id_s,
                    entry_date=entry_date_s,
                    author_id=author_id_s,
                    activity_rows=labour_rows,
                )
                await self.entry_repo.update_fields(entry_id, labour_published_at=now)
                await self.session.refresh(entry)
            except Exception:
                logger.exception(
                    "Diary labour publish failed for entry=%s - approval unaffected",
                    entry_id,
                )

        # Epic H - universal audit trail.
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

    # ── Project roster ────────────────────────────────────────────────────

    async def list_project_crew(self, project_id: uuid.UUID) -> list[Resource]:
        """People and crews the phone can pick instead of typing a name.

        A crew row captured under a typed name has no ``resource_id``, and the
        timesheet reconciliation matches on exactly that, so the same person is
        counted once from the phone and once from the desktop with nothing on
        either screen saying so. Picking off this list carries the id.

        Two ways in, because a project staffs itself both ways: a resource whose
        ``home_project_id`` is this project (site labour that belongs here), and
        a resource with an assignment to this project (someone lent from the
        shared pool for a week). A foreman would not accept "not on the list"
        for a person standing on their site.

        Returns ``[]`` when the resources module is not installed - the phone
        keeps its free-text field, which is also the fallback for a
        subcontractor's worker who is in nobody's register.
        """
        try:
            from app.modules.resources.models import Assignment, Resource
        except ImportError:  # pragma: no cover - resources ships with core
            logger.debug("resources module absent, field roster is empty for project=%s", project_id)
            return []

        assigned_here = (
            select(Assignment.id)
            .where(
                Assignment.resource_id == Resource.id,
                Assignment.project_id == project_id,
            )
            .exists()
        )
        stmt = (
            select(Resource)
            .where(
                Resource.resource_type.in_(FIELD_ROSTER_KINDS),
                Resource.status == "active",
                or_(Resource.home_project_id == project_id, assigned_here),
            )
            .order_by(Resource.name, Resource.code)
            # One over the cap, so a truncated list can be told from a full one
            # rather than being reported as the whole workforce.
            .limit(FIELD_ROSTER_LIMIT + 1)
        )
        rows = list((await self.session.execute(stmt)).scalars().all())
        if len(rows) > FIELD_ROSTER_LIMIT:
            # Say so. Somebody past the cap reads on the phone as "not on the
            # list", the foreman types their name, and the punch goes back to
            # the shape this whole route exists to stop - silently.
            logger.warning(
                "Field roster for project=%s truncated at %s people, the rest will have to be typed",
                project_id,
                FIELD_ROSTER_LIMIT,
            )
            rows = rows[:FIELD_ROSTER_LIMIT]
        return rows

    # ── Activities ────────────────────────────────────────────────────────

    async def append_activity(
        self,
        entry_id: uuid.UUID,
        data: DiaryActivityCreate,
        *,
        op_kind: str = "",
    ) -> DiaryActivity:
        entry = await self.get_diary_entry(entry_id)
        if entry.status == "approved":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot append activities to an approved entry",
            )

        # Durable offline idempotency: if this op was already applied (a queue
        # replayed at-least-once, or a request whose response was lost), return
        # the original row instead of inserting a duplicate. Keyed on the
        # device-generated ``client_op_id``; absent for direct online callers.
        client_op_id = data.client_op_id
        if client_op_id:
            seen = await self.ledger_repo.get_by_client_op_id(client_op_id)
            if seen is not None and seen.result_id is not None:
                existing = await self.activity_repo.get_by_id(seen.result_id)
                if existing is not None:
                    return existing
                # Ledger row exists but the activity was deleted - fall through
                # and re-create, then refresh the ledger pointer below.

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
        activity = await self.activity_repo.create(activity)

        if client_op_id:
            await self._record_op(
                client_op_id,
                project_id=entry.project_id,
                user_id=entry.author_id,
                op_kind=op_kind,
                result_type="field_diary_activity",
                result_id=activity.id,
            )

        return activity

    async def _record_op(
        self,
        client_op_id: str,
        *,
        project_id: uuid.UUID,
        user_id: uuid.UUID,
        op_kind: str,
        result_type: str,
        result_id: uuid.UUID,
    ) -> None:
        """Record an applied offline op in the sync ledger (best-effort dedup key).

        Tolerates a concurrent insert of the same ``client_op_id`` (two drains
        racing): the unique constraint makes the second insert fail, which we
        swallow because the first already recorded the canonical result.
        """
        from sqlalchemy.exc import IntegrityError

        if await self.ledger_repo.get_by_client_op_id(client_op_id) is not None:
            return
        try:
            # Wrap ONLY the ledger insert in a SAVEPOINT so a duplicate-race
            # IntegrityError rolls back just this insert, not the whole request
            # transaction. The outer transaction already holds the applied
            # activity (and any earlier ops drained in this same batch); a bare
            # session.rollback() here would silently discard those already-
            # applied writes, including the schedule-progress entry that reaches
            # earned value.
            async with self.session.begin_nested():
                await self.ledger_repo.create(
                    FieldSyncLedger(
                        client_op_id=client_op_id,
                        project_id=project_id,
                        user_id=user_id,
                        op_kind=op_kind or "",
                        result_type=result_type,
                        result_id=result_id,
                    )
                )
        except IntegrityError:
            # A racing drain already recorded this op; the activity row it points
            # at is the canonical one. The SAVEPOINT was rolled back on exit, so
            # the surrounding transaction stays intact for the outer commit.
            pass

    async def append_activity_by_date(
        self,
        *,
        project_id: uuid.UUID,
        author_id: uuid.UUID,
        entry_date: str,
        data: DiaryActivityCreate,
        op_kind: str = "",
    ) -> DiaryActivity:
        """Find-or-create the author's diary entry for *entry_date*, append *data*.

        Built for the offline field shell: a queued write replayed from a phone
        has no server entry id (the entry may not exist yet), so this resolves
        the ``(project, author, date)`` entry, creating a draft when absent, then
        appends the activity. The entry's unique constraint makes the create
        idempotent and the activity dedup on ``client_op_id`` (handled in
        :meth:`append_activity`) makes the whole op replay-safe.
        """
        # Short-circuit a known replayed op BEFORE touching the entry, so a
        # second drain does not even resolve / create the entry again.
        if data.client_op_id:
            seen = await self.ledger_repo.get_by_client_op_id(data.client_op_id)
            if seen is not None and seen.result_id is not None:
                existing = await self.activity_repo.get_by_id(seen.result_id)
                if existing is not None:
                    return existing

        entry = await self.entry_repo.get_by_unique(project_id, author_id, entry_date)
        if entry is None:
            entry = DiaryEntry(
                project_id=project_id,
                author_id=author_id,
                entry_date=entry_date,
                status="draft",
                field_source="pwa",
                metadata_={},
            )
            entry = await self.entry_repo.create(entry)
        return await self.append_activity(entry.id, data, op_kind=op_kind)

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
        exactly once - only the SHA-256 hashes are persisted.
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

        # Mock SMS dispatch - production wires Twilio here.
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

        # Constant-time equality on the persisted hash - paranoia layer
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

        # Snapshot the scalars the consume path below needs before it writes.
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
                    detail=("Too many failed PIN attempts - magic link invalidated"),
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


# ── Cross-module field sync dispatcher ─────────────────────────────────────


class FieldSyncService:
    """Hub that routes an offline-captured field write into the target module.

    It owns no record type: it dispatches a capture into the punchlist or
    inspections module's own service, forces ``project_id`` to the session's
    pinned project, and records the applied op in the shared
    :class:`FieldSyncLedger` keyed on ``client_op_id``. A replay of a known
    ``client_op_id`` short-circuits and returns the original downstream row id,
    which is what makes draining the offline queue more than once safe.

    The diary-entry / activity capture path is idempotent inside
    :class:`FieldDiaryService` already; this service adds the punch and
    inspection capture paths on the same ledger so all four modules dedup on one
    key.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.field_svc = FieldDiaryService(session)
        self.ledger_repo = FieldSyncLedgerRepository(session)

    async def _seen_result(
        self,
        client_op_id: str,
        expected_type: str,
    ) -> uuid.UUID | None:
        """Return the prior downstream id for a known op, or ``None`` if new.

        ``None`` is also returned when the ledger row exists but the downstream
        row was since deleted, so the caller re-creates and re-points the ledger.
        """
        seen = await self.ledger_repo.get_by_client_op_id(client_op_id)
        if seen is None or seen.result_id is None:
            return None
        if seen.result_type != expected_type:
            # Same op id replayed against a different kind: treat as new for the
            # expected kind (the unique key still blocks a second ledger row).
            return None
        return seen.result_id

    async def capture_punch(
        self,
        field_session: FieldSession,
        data: FieldPunchCreate,
    ) -> FieldCaptureResponse:
        """Create a punch item from a field capture, idempotently.

        The project is the session's pinned project (never the request body), so
        a cross-project write is impossible to express.
        """
        from app.modules.punchlist.models import PunchItem
        from app.modules.punchlist.repository import PunchListRepository

        project_id = field_session.project_id

        prior = await self._seen_result(data.client_op_id, "punchlist_item")
        if prior is not None:
            return FieldCaptureResponse(
                client_op_id=data.client_op_id,
                status="applied",
                target_module="punchlist",
                target_kind="punch_item",
                result_id=prior,
                http_status=200,
            )

        repo = PunchListRepository(self.session)
        item = PunchItem(
            project_id=project_id,
            title=data.title,
            description=data.description,
            priority=data.priority,
            status="open",
            trade=data.trade,
            geo_lat=data.lat,
            geo_lon=data.lon,
            created_by=str(field_session.user_id),
            metadata_=self._capture_metadata(data),
        )
        item = await repo.create(item)
        await self.field_svc._record_op(
            data.client_op_id,
            project_id=project_id,
            user_id=field_session.user_id,
            op_kind="field.capture.punch",
            result_type="punchlist_item",
            result_id=item.id,
        )
        return FieldCaptureResponse(
            client_op_id=data.client_op_id,
            status="applied",
            target_module="punchlist",
            target_kind="punch_item",
            result_id=item.id,
            http_status=201,
        )

    async def capture_inspection(
        self,
        field_session: FieldSession,
        data: FieldInspectionCreate,
    ) -> FieldCaptureResponse:
        """Create an inspection from a field capture, idempotently."""
        from app.modules.inspections.models import QualityInspection
        from app.modules.inspections.repository import InspectionRepository

        project_id = field_session.project_id

        prior = await self._seen_result(data.client_op_id, "inspection")
        if prior is not None:
            return FieldCaptureResponse(
                client_op_id=data.client_op_id,
                status="applied",
                target_module="inspections",
                target_kind="inspection",
                result_id=prior,
                http_status=200,
            )

        repo = InspectionRepository(self.session)
        inspection = QualityInspection(
            project_id=project_id,
            inspection_type=data.inspection_type,
            title=data.title,
            location=data.location,
            status="scheduled",
            checklist_data=list(data.checklist_data or []),
            geo_lat=data.lat,
            geo_lon=data.lon,
            created_by=str(field_session.user_id),
            metadata_=self._capture_metadata(data),
        )
        inspection = await repo.create(inspection)
        await self.field_svc._record_op(
            data.client_op_id,
            project_id=project_id,
            user_id=field_session.user_id,
            op_kind="field.capture.inspection",
            result_type="inspection",
            result_id=inspection.id,
        )
        return FieldCaptureResponse(
            client_op_id=data.client_op_id,
            status="applied",
            target_module="inspections",
            target_kind="inspection",
            result_id=inspection.id,
            http_status=201,
        )

    async def capture_schedule_progress(
        self,
        field_session: FieldSession,
        data: FieldScheduleProgressCreate,
    ) -> FieldCaptureResponse:
        """Apply a field-captured progress update to a schedule activity (T3.4).

        Routes the capture through the progress-rigor engine (T3.2) so a phone
        update is resolved exactly like a desktop one (per-type percent /
        remaining / installed-units, with the same completion guard). Idempotent
        on ``client_op_id``: a replay returns the original activity id and does
        not re-apply.
        """
        # Schedule imports are function-local: the schedule service imports
        # app.database at module load, so importing it here (matching the
        # punch/inspection capture paths above) keeps field_diary import-safe.
        from decimal import Decimal

        from app.modules.schedule import realtime_math
        from app.modules.schedule.models import Activity, Schedule, ScheduleProgressEntry
        from app.modules.schedule.progress_schemas import TypedProgressRequest
        from app.modules.schedule.progress_service import ScheduleProgressService
        from app.modules.schedule.service import ScheduleService

        # 1. Idempotent replay short-circuit (returns the prior activity id).
        prior = await self._seen_result(data.client_op_id, "schedule_activity_progress")
        if prior is not None:
            return FieldCaptureResponse(
                client_op_id=data.client_op_id,
                status="applied",
                target_module="schedule",
                target_kind="schedule_progress",
                result_id=prior,
                http_status=200,
            )

        # 2. IDOR guard (critical). Resolve activity -> schedule -> project_id
        #    and require it to equal the session's pinned project. A cross-project
        #    (or unknown) activity id resolves to 404 - existence-oracle safe, the
        #    same guard the punch-photo capture path applies. NEVER trust an
        #    activity id that is not in the field session's project.
        project_id = (
            await self.session.execute(
                select(Schedule.project_id)
                .join(Activity, Activity.schedule_id == Schedule.id)
                .where(Activity.id == data.activity_id)
            )
        ).scalar_one_or_none()
        if project_id is None or project_id != field_session.project_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Activity not found",
            )

        # 3. Validate + normalise via the pure engine (clamp percent, floor
        #    remaining, finish-implies-complete, require a mutating field).
        submission = realtime_math.FieldProgressSubmission(
            activity_id=str(data.activity_id),
            client_op_id=data.client_op_id,
            percent_complete=data.percent_complete,
            remaining_duration=data.remaining_duration,
            installed_units=(str(data.installed_units) if data.installed_units is not None else None),
            actual_start_iso=data.actual_start,
            actual_finish_iso=data.actual_finish,
            captured_at_iso=data.captured_at,
        )
        validation = realtime_math.validate_field_submission(submission)
        if not validation.ok or validation.normalized is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"errors": list(validation.errors)},
            )
        norm = validation.normalized

        # 4. Route to T3.2. Map the captured date onto the engine's data_date;
        #    leave percent_complete_type unset so the activity's current type is
        #    honoured. installed_units stays a Decimal quantity.
        data_date = data.captured_at[:10] if data.captured_at else None
        progress_svc = ScheduleProgressService(self.session)
        outcome = await progress_svc.set_typed_progress(
            data.activity_id,
            TypedProgressRequest(
                percent=norm.percent_complete,
                remaining_duration=norm.remaining_duration,
                installed_units=data.installed_units,
                data_date=data_date,
            ),
        )

        # 5. Append a progress-history entry on the dedicated progress table so
        #    the field reading reaches every consumer that reads that table -
        #    the EVM / 4D dashboards and the S-curve actual series - not just the
        #    activity row. This row is where the captured actual_start /
        #    actual_finish dates live: the Activity table has no actual-date
        #    columns, so without this entry a phone-captured actual date never
        #    reached EVM. progress_percent mirrors the engine-resolved value from
        #    step 4 (which honours the activity's percent-complete type), NOT the
        #    raw input, so the entry and the activity never disagree. The
        #    roll-forward onto the activity was already applied by
        #    set_typed_progress, so here we only append the entry.
        geolocation = {"lat": data.lat, "lon": data.lon} if data.lat is not None and data.lon is not None else None
        self.session.add(
            ScheduleProgressEntry(
                task_id=data.activity_id,
                progress_percent=Decimal(str(outcome.result.percent_complete)),
                geolocation=geolocation,
                device="field",
                recorded_by_user_id=field_session.user_id,
                actual_start_date=data.actual_start,
                actual_finish_date=data.actual_finish,
            )
        )
        await self.session.flush()

        # 6. Also mirror the captured actual_start / actual_finish onto the
        #    activity metadata as a denormalised convenience read (the canonical
        #    home is the progress entry recorded in step 5). We merge so a prior
        #    field_actuals block and all sibling metadata keys survive
        #    (json_overwrite-on-PATCH guard).
        actuals: dict[str, str] = {}
        if data.actual_start is not None:
            actuals["actual_start"] = data.actual_start
        if data.actual_finish is not None:
            actuals["actual_finish"] = data.actual_finish
        if actuals:
            sched_svc = ScheduleService(self.session)
            current = await sched_svc.get_activity(data.activity_id)
            existing_meta = dict(current.metadata_ or {})
            existing_actuals = dict(existing_meta.get("field_actuals") or {})
            existing_actuals.update(actuals)
            merged = merge_metadata(existing_meta, {"field_actuals": existing_actuals})
            await sched_svc.activity_repo.update_fields(data.activity_id, metadata_=merged)

        # 7. Record the applied op in the shared ledger (tolerates a racing drain
        #    via the same IntegrityError swallow as the punch/inspection paths).
        await self.field_svc._record_op(
            data.client_op_id,
            project_id=project_id,
            user_id=field_session.user_id,
            op_kind="field.capture.schedule_progress",
            result_type="schedule_activity_progress",
            result_id=data.activity_id,
        )
        return FieldCaptureResponse(
            client_op_id=data.client_op_id,
            status="applied",
            target_module="schedule",
            target_kind="schedule_progress",
            result_id=data.activity_id,
            http_status=201,
        )

    @staticmethod
    def _capture_metadata(data: FieldCapture) -> dict[str, Any]:
        """Build the ``field_capture`` metadata block stored on the row.

        Only non-null capture fields are written so the JSON stays tight.
        """
        block: dict[str, Any] = {"source": "field_pwa"}
        for key in ("lat", "lon", "accuracy_m", "device_hint", "captured_at"):
            value = getattr(data, key, None)
            if value is not None:
                block[key] = value
        return {"field_capture": block}

    async def list_ops(
        self,
        field_session: FieldSession,
        *,
        since: str | None = None,
    ) -> list:
        """A worker's own applied ops (newest first), scoped to the session."""
        return await self.ledger_repo.list_for_session_scope(
            field_session.project_id,
            field_session.user_id,
            since=since,
        )


__all__ = [
    "DIARY_STATUSES",
    "MAGIC_LINK_TTL",
    "PIN_MAX_ATTEMPTS",
    "SESSION_TTL",
    "FieldDiaryService",
    "FieldSyncService",
    "clear_sms_log",
    "constant_time_equals",
    "generate_pin",
    "generate_token",
    "get_sms_log",
    "hash_token",
    "now_utc",
]
