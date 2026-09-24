# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Meetings service - business logic for meeting management.

Stateless service layer. Handles:
- Meeting CRUD
- Auto-generated meeting numbers (MTG-001, MTG-002, ...)
- Status transitions (draft -> scheduled -> in_progress -> completed)
- Action item -> Task creation on meeting completion
"""

import base64
import binascii
import logging
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.core.json_merge import merge_metadata
from app.modules.meetings import logic
from app.modules.meetings.models import Meeting, MeetingActionItem, MeetingAttendance, MeetingMinutes
from app.modules.meetings.repository import MeetingRepository
from app.modules.meetings.schemas import (
    ActionRegisterItemCreate,
    ActionRegisterItemUpdate,
    MeetingCreate,
    MeetingSeriesCreate,
    MeetingStatsResponse,
    MeetingUpdate,
    MinutesGenerateRequest,
    MinutesUpdate,
    OpenActionItemResponse,
)

logger = logging.getLogger(__name__)
_logger_audit = logging.getLogger(__name__ + ".audit")


async def _safe_audit(
    session: AsyncSession,
    *,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    user_id: str | None = None,
    details: dict | None = None,
) -> None:
    """Best-effort audit log - never blocks the caller on failure."""
    try:
        from app.core.audit import audit_log

        await audit_log(
            session,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            user_id=user_id,
            details=details,
        )
    except Exception:
        _logger_audit.debug("Audit log write skipped for %s %s", action, entity_type)


# ── Allowed meeting status transitions ────────────────────────────────────────

_MEETING_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"scheduled", "cancelled"},
    "scheduled": {"in_progress", "cancelled", "draft"},
    "in_progress": {"completed", "cancelled"},
    "completed": set(),  # terminal
    "cancelled": {"draft"},
}


class MeetingService:
    """Business logic for meeting operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = MeetingRepository(session)

    # ── Integrity helpers ────────────────────────────────────────────────

    async def _reject_foreign_document_ids(
        self,
        project_id: uuid.UUID,
        document_ids: list[str],
    ) -> None:
        """Raise 422 if any document_id belongs to a different project.

        A meeting's ``document_ids`` JSON array is a cross-module
        reference into ``oe_documents_document``.  Pre-fix this field
        was stored verbatim, so a caller could attach a UUID that
        resolves to a document inside another project (even on a
        sibling project of the same tenant).  That breaks data
        integrity in two ways:

        1. The reference leaks the existence of foreign documents into
           the meeting payload returned by ``GET /meetings/{id}``.
        2. The dangling FK survives deletion of the foreign project,
           leaving zombie pointers no team can clean up without
           superuser DB access.

        The check is symmetric - it applies whether the caller is a
        tenant boundary breach OR a same-tenant mistake (an admin
        copy-pasting the wrong UUID from another project).  Missing
        documents return the same 422 - we do NOT distinguish
        ``not-found`` from ``wrong-project`` here, to avoid turning
        the meeting create into a UUID-existence oracle.
        """
        if not document_ids:
            return
        # Lazy import to avoid a module-level circular: documents
        # depends on the audit log, which sometimes lazy-imports
        # meetings at startup.
        from sqlalchemy import select as _select

        from app.modules.documents.models import Document

        # Coerce input to UUID, ignoring malformed entries so a single
        # bad string doesn't blow up the whole insertion - the
        # ``oe_documents_document.id`` column is GUID-typed, so any
        # non-UUID can't possibly match anyway.
        ids: list[uuid.UUID] = []
        for raw in document_ids:
            try:
                ids.append(uuid.UUID(str(raw)))
            except (ValueError, AttributeError):
                continue
        if not ids:
            return

        stmt = _select(Document.id, Document.project_id).where(
            Document.id.in_(ids),
        )
        rows = (await self.session.execute(stmt)).all()
        by_id = {str(row[0]): str(row[1]) for row in rows}

        bad: list[str] = []
        for raw in document_ids:
            owner = by_id.get(str(raw))
            if owner is None or owner != str(project_id):
                bad.append(str(raw))
        if bad:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(f"document_ids reference documents that do not belong to project {project_id}: {bad}"),
            )

    # ── Create ────────────────────────────────────────────────────────────

    async def create_meeting(
        self,
        data: MeetingCreate,
        user_id: str | None = None,
    ) -> Meeting:
        """Create a new meeting with auto-generated meeting number."""
        # Reject any document_ids that don't live inside this project -
        # a meeting referencing a foreign-project document is a
        # data-integrity violation that creates dangling cross-project
        # FKs and leaks the *existence* of foreign documents into the
        # meeting payload.  Same rule on update_meeting below.
        await self._reject_foreign_document_ids(
            data.project_id,
            [str(x) for x in data.document_ids],
        )

        meeting_number = await self.repo.next_meeting_number(data.project_id)

        attendees_data = [entry.model_dump() for entry in data.attendees]
        agenda_data = [entry.model_dump() for entry in data.agenda_items]
        action_data = [entry.model_dump() for entry in data.action_items]
        document_ids = [str(x) for x in data.document_ids]

        meeting = Meeting(
            project_id=data.project_id,
            meeting_number=meeting_number,
            meeting_type=data.meeting_type,
            title=data.title,
            meeting_date=data.meeting_date,
            location=data.location,
            chairperson_id=data.chairperson_id,
            attendees=attendees_data,
            agenda_items=agenda_data,
            action_items=action_data,
            minutes=data.minutes,
            status=data.status,
            document_ids=document_ids,
            created_by=user_id,
            metadata_=data.metadata,
        )
        meeting = await self.repo.create(meeting)

        await _safe_audit(
            self.session,
            action="create",
            entity_type="meeting",
            entity_id=str(meeting.id),
            user_id=user_id,
            details={
                "title": data.title,
                "meeting_number": meeting_number,
                "meeting_type": data.meeting_type,
                "project_id": str(data.project_id),
            },
        )

        logger.info(
            "Meeting created: %s (%s) for project %s",
            meeting_number,
            data.meeting_type,
            data.project_id,
        )
        return meeting

    # ── Read ──────────────────────────────────────────────────────────────

    async def get_meeting(self, meeting_id: uuid.UUID) -> Meeting:
        """Get meeting by ID. Raises 404 if not found."""
        meeting = await self.repo.get_by_id(meeting_id)
        if meeting is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Meeting not found",
            )
        return meeting

    async def list_meetings(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        meeting_type: str | None = None,
        status_filter: str | None = None,
        search: str | None = None,
        sort_by: str | None = None,
        sort_order: str = "desc",
    ) -> tuple[list[Meeting], int]:
        """List meetings for a project with optional search."""
        return await self.repo.list_for_project(
            project_id,
            offset=offset,
            limit=limit,
            meeting_type=meeting_type,
            status=status_filter,
            search=search,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    # ── Update ────────────────────────────────────────────────────────────

    async def update_meeting(
        self,
        meeting_id: uuid.UUID,
        data: MeetingUpdate,
    ) -> Meeting:
        """Update meeting fields."""
        meeting = await self.get_meeting(meeting_id)

        if meeting.status in ("completed", "cancelled"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot edit a meeting with status '{meeting.status}'",
            )

        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            _incoming = fields.pop("metadata")
            fields["metadata_"] = (
                merge_metadata(getattr(meeting, "metadata_", None), _incoming)
                if isinstance(_incoming, dict)
                else _incoming
            )

        # Validate status transition if status is being changed
        new_status = fields.get("status")
        if new_status is not None and new_status != meeting.status:
            allowed = _MEETING_STATUS_TRANSITIONS.get(meeting.status, set())
            if new_status not in allowed:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Cannot transition meeting from '{meeting.status}' to "
                        f"'{new_status}'. Allowed transitions: "
                        f"{', '.join(sorted(allowed)) or 'none'}"
                    ),
                )

        # Convert Pydantic models to dicts for JSON columns
        for key in ("attendees", "agenda_items", "action_items"):
            if key in fields and fields[key] is not None:
                fields[key] = [entry.model_dump() if hasattr(entry, "model_dump") else entry for entry in fields[key]]

        # Stringify + deduplicate document_ids for JSON storage
        if "document_ids" in fields and fields["document_ids"] is not None:
            seen: set[str] = set()
            deduped: list[str] = []
            for raw in fields["document_ids"]:
                s = str(raw)
                if s not in seen:
                    seen.add(s)
                    deduped.append(s)
            fields["document_ids"] = deduped
            # Same per-project integrity gate as create_meeting.
            await self._reject_foreign_document_ids(
                meeting.project_id,
                deduped,
            )

        if not fields:
            return meeting

        await self.repo.update_fields(meeting_id, **fields)
        await self.session.refresh(meeting)

        logger.info("Meeting updated: %s (fields=%s)", meeting_id, list(fields.keys()))
        return meeting

    # ── Delete ────────────────────────────────────────────────────────────

    async def delete_meeting(self, meeting_id: uuid.UUID) -> None:
        """Delete a meeting.

        Also scrubs ``meeting_id`` references from any tasks that were
        auto-created via ``complete_meeting`` - preventing dangling FK
        pointers without destroying the user's task history.
        """
        meeting = await self.get_meeting(meeting_id)  # Raises 404 if not found

        # A completed meeting and one whose minutes were issued are the record
        # of what was decided; the minutes row cascades with the meeting, so a
        # delete would take the issued document with it. A meeting that will
        # not take place is cancelled instead.
        if meeting.status == "completed":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot delete a completed meeting: it is the record of what was decided and is kept.",
            )
        minutes = await self.get_minutes_row(meeting_id)
        if minutes is not None and minutes.status == "issued":
            remedy = (
                " Cancel the meeting instead."
                if "cancelled" in _MEETING_STATUS_TRANSITIONS.get(meeting.status, set())
                else ""
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cannot delete a meeting whose minutes were issued: they are kept as the record.{remedy}",
            )

        # Clear the meeting_id FK on tasks that reference this meeting
        try:
            from sqlalchemy import update as _update

            from app.modules.tasks.models import Task

            result = await self.session.execute(
                _update(Task).where(Task.meeting_id == str(meeting_id)).values(meeting_id=None)
            )
            if result.rowcount:
                logger.info(
                    "Cleared meeting_id on %d tasks before deleting meeting %s",
                    result.rowcount,
                    meeting_id,
                )
        except Exception as exc:  # best-effort cleanup
            logger.warning(
                "Failed to scrub task.meeting_id refs for meeting %s: %s",
                meeting_id,
                exc,
            )

        await self.repo.delete(meeting_id)
        logger.info("Meeting deleted: %s", meeting_id)

    # ── Complete ──────────────────────────────────────────────────────────

    async def complete_meeting(
        self,
        meeting_id: uuid.UUID,
        user_id: str | None = None,
    ) -> Meeting:
        """Mark a meeting as completed.

        Only meetings with status ``scheduled`` or ``in_progress`` can be
        completed.  A ``draft`` meeting must first be scheduled.

        When the meeting contains open action items, corresponding tasks are
        created automatically and a ``meeting.action_items_created`` event is
        emitted for any additional subscribers.
        """
        meeting = await self.get_meeting(meeting_id)
        if meeting.status == "completed":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Meeting is already completed",
            )
        if meeting.status == "cancelled":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot complete a cancelled meeting",
            )
        if meeting.status == "draft":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot complete a draft meeting - schedule it first",
            )

        await self.repo.update_fields(meeting_id, status="completed")
        await self.session.refresh(meeting)
        logger.info("Meeting completed: %s", meeting_id)

        # Create tasks from open action items.  Per-item isolation: a
        # single failed action item does not abort the others, AND the
        # event payload only carries the action items that ACTUALLY
        # produced a Task row.  The previous version wrapped the
        # whole loop in a try/except and then published a "tasks
        # created" event regardless - even if zero tasks were
        # created, downstream subscribers were told the work was
        # done.  Now the event payload + the meeting completion
        # response surface the real success/failure breakdown so the
        # UI can show "3 of 5 tasks created" instead of lying.
        action_items = meeting.action_items or []
        open_actions = [ai for ai in action_items if isinstance(ai, dict) and ai.get("status", "open") == "open"]
        created_action_items: list[dict] = []
        failed_action_items: list[dict] = []

        if open_actions:
            from app.modules.tasks.models import Task

            for ai in open_actions:
                try:
                    task = Task(
                        project_id=meeting.project_id,
                        task_type="task",
                        title=ai.get("description", "Action item from meeting")[:500],
                        description=(f"Auto-created from meeting {meeting.meeting_number}: {meeting.title}"),
                        responsible_id=ai.get("owner_id"),
                        due_date=ai.get("due_date"),
                        meeting_id=str(meeting.id),
                        status="open",
                        priority="normal",
                        is_private=False,
                        created_by=user_id,
                        metadata_={"source": "meeting_action_item"},
                    )
                    self.session.add(task)
                    await self.session.flush()
                    created_action_items.append({**ai, "task_id": str(task.id)})
                except Exception as exc:  # noqa: BLE001 - per-item isolation
                    logger.warning(
                        "Failed to create task from meeting %s action item: %s",
                        meeting.meeting_number,
                        exc,
                    )
                    failed_action_items.append({**ai, "error": str(exc)})

            logger.info(
                "Meeting %s: %d/%d tasks created from action items (%d failed)",
                meeting.meeting_number,
                len(created_action_items),
                len(open_actions),
                len(failed_action_items),
            )

            # Only publish the event if at least one task actually
            # made it into the DB.  An empty creation set means
            # downstream subscribers (notifications, vector index)
            # have nothing to consume - publishing would be a lie.
            #
            # Idempotency note: ``complete_meeting`` is guarded above
            # against re-completion ("Meeting is already completed"),
            # so this event fires at most once per meeting in the
            # happy path.  We still hand subscribers a stable
            # ``event_key`` (``meeting:complete:<id>``) so they can
            # dedupe defensively if the bus ever gains
            # at-least-once delivery semantics - the publish itself
            # is a fire-and-forget detached task and a transient
            # bus retry would otherwise create duplicate
            # notifications on the task owner's inbox.
            if created_action_items:
                event_bus.publish_detached(
                    "meeting.action_items_created",
                    {
                        "meeting_id": str(meeting.id),
                        "project_id": str(meeting.project_id),
                        "meeting_number": meeting.meeting_number,
                        "action_items": created_action_items,
                        "failed_action_items": failed_action_items,
                        "created_count": len(created_action_items),
                        "failed_count": len(failed_action_items),
                        "event_key": f"meeting:complete:{meeting.id}",
                    },
                    source_module="meetings",
                )

        # Stash the per-item breakdown on the returned meeting so the
        # router can surface it in the response payload.  Setting it
        # via setattr keeps the ORM model unchanged - this is a
        # transient annotation, not a column.
        meeting._action_item_summary = {  # type: ignore[attr-defined]
            "created": created_action_items,
            "failed": failed_action_items,
        }

        return meeting

    # ── Stats ────────────────────────────────────────────────────────────

    async def get_stats(self, project_id: uuid.UUID) -> MeetingStatsResponse:
        """Return aggregate meeting statistics for a project.

        Includes open_action_items_count computed by scanning the JSON
        action_items arrays of all non-cancelled meetings. Pulls only the
        JSON column (not full Meeting rows) to keep cost bounded.
        """
        raw = await self.repo.stats_for_project(project_id)

        rows = await self.repo.action_items_for_project(project_id)
        open_count = 0
        for _id, _num, _title, _date, action_items in rows:
            for ai in action_items or []:
                if isinstance(ai, dict) and ai.get("status", "open") == "open":
                    open_count += 1

        return MeetingStatsResponse(
            total=raw["total"],
            by_status=raw["by_status"],
            by_type=raw["by_type"],
            open_action_items_count=open_count,
            next_meeting_date=raw["next_meeting_date"],
        )

    # ── Open Action Items ────────────────────────────────────────────────

    async def get_open_actions(
        self,
        project_id: uuid.UUID,
    ) -> list[OpenActionItemResponse]:
        """Return all open action items across all meetings in a project."""
        rows = await self.repo.action_items_for_project(project_id)
        result: list[OpenActionItemResponse] = []
        for meeting_id, meeting_number, title, meeting_date, action_items in rows:
            for ai in action_items or []:
                if isinstance(ai, dict) and ai.get("status", "open") == "open":
                    result.append(
                        OpenActionItemResponse(
                            meeting_id=meeting_id,
                            meeting_number=meeting_number,
                            meeting_title=title,
                            meeting_date=meeting_date,
                            description=ai.get("description", ""),
                            owner_id=ai.get("owner_id"),
                            due_date=ai.get("due_date"),
                        )
                    )
        return result

    # ── Recurring series ─────────────────────────────────────────────────

    async def create_series(
        self,
        data: MeetingSeriesCreate,
        user_id: str | None = None,
    ) -> tuple[Meeting, list[Meeting]]:
        """Create a series master and (optionally) materialise occurrences.

        The master meeting carries the ``recurrence_rule`` and stamps its
        own id into ``series_id``. Occurrences (non-master) share the same
        ``series_id`` but have no rule of their own.

        Returns:
            Tuple of (master Meeting, list of occurrence Meetings).
        """
        # Build a one-off Meeting first via the regular path so we reuse
        # auto-numbering, audit, and attendee/agenda coercion.
        base_create = MeetingCreate(
            project_id=data.project_id,
            meeting_type=data.meeting_type,
            title=data.title,
            meeting_date=data.meeting_date,
            location=data.location,
            chairperson_id=data.chairperson_id,
            attendees=data.attendees,
            agenda_items=data.agenda_items,
            action_items=data.action_items,
            minutes=data.minutes,
            status=data.status,
            document_ids=data.document_ids,
            metadata=data.metadata,
        )
        master = await self.create_meeting(base_create, user_id=user_id)

        # Stamp master with series fields. Using update_fields keeps the
        # repo as the single mutator and reuses its transaction handling.
        await self.repo.update_fields(
            master.id,
            series_id=str(master.id),
            recurrence_rule=data.recurrence_rule,
            is_series_master=True,
        )
        await self.session.refresh(master)

        occurrences: list[Meeting] = []
        if data.materialize_until:
            until_dt = datetime.strptime(
                data.materialize_until,
                "%Y-%m-%d",
            ).replace(tzinfo=UTC)
            occurrences = await self.generate_occurrences(
                str(master.id),
                until_dt,
                user_id=user_id,
            )

        return master, occurrences

    async def generate_occurrences(
        self,
        series_id: str,
        until: datetime,
        *,
        user_id: str | None = None,
    ) -> list[Meeting]:
        """Materialise non-master occurrences up to ``until``.

        Idempotent: meetings whose ``meeting_date`` already exists in the
        series are skipped. Returns only newly-created occurrences (not
        master, not pre-existing rows).
        """
        # Load master + existing occurrences in one query.
        result = await self.session.execute(select(Meeting).where(Meeting.series_id == series_id))
        existing = result.scalars().all()
        master = next((m for m in existing if m.is_series_master), None)
        if master is None or not master.recurrence_rule:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(f"Series master not found or has no recurrence_rule (series_id={series_id})"),
            )

        already_have_dates: set[str] = {m.meeting_date for m in existing}

        # Anchor at the master meeting_date so DTSTART is implicit.
        try:
            start_dt = datetime.strptime(
                master.meeting_date,
                "%Y-%m-%d",
            ).replace(tzinfo=UTC)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Master meeting_date is not ISO format: {master.meeting_date}",
            ) from exc

        try:
            occurrence_dates = _expand_rrule(master.recurrence_rule, start_dt, until)
        except _RRuleError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid recurrence_rule: {exc}",
            ) from exc

        new_occurrences: list[Meeting] = []
        for dt in occurrence_dates:
            date_str = dt.strftime("%Y-%m-%d")
            # Skip the master's own date (it represents the first occurrence
            # already) and any pre-existing occurrences.
            if date_str in already_have_dates:
                continue
            occ_create = MeetingCreate(
                project_id=master.project_id,
                meeting_type=master.meeting_type,
                title=master.title,
                meeting_date=date_str,
                location=master.location,
                chairperson_id=master.chairperson_id,
                attendees=[],  # occurrences start with empty rolls
                agenda_items=[],
                action_items=[],
                minutes=None,
                status="scheduled",
                document_ids=[uuid.UUID(d) for d in (master.document_ids or [])],
                metadata={"materialized_from_series": str(series_id)},
            )
            occ = await self.create_meeting(occ_create, user_id=user_id)
            await self.repo.update_fields(
                occ.id,
                series_id=str(series_id),
                is_series_master=False,
            )
            await self.session.refresh(occ)
            already_have_dates.add(date_str)
            new_occurrences.append(occ)

        logger.info(
            "Series %s materialised %d new occurrences (until=%s)",
            series_id,
            len(new_occurrences),
            until.date(),
        )
        return new_occurrences

    # ── Attendance check-in ──────────────────────────────────────────────

    async def check_in(
        self,
        meeting_id: uuid.UUID,
        user_id: str,
        signature_image_data: str | None = None,
    ) -> MeetingAttendance:
        """Create or update an attendance row for the given user.

        Re-checking-in updates the existing row (single row per
        (meeting, user)) instead of creating a duplicate.
        """
        # Verify the meeting exists.
        await self.get_meeting(meeting_id)

        result = await self.session.execute(
            select(MeetingAttendance).where(
                MeetingAttendance.meeting_id == meeting_id,
                MeetingAttendance.user_id == user_id,
            )
        )
        row = result.scalar_one_or_none()

        sig_path: str | None = None
        if signature_image_data:
            sig_path = await _save_signature_image(
                meeting_id,
                signature_image_data,
            )

        now = datetime.now(UTC)
        if row is None:
            row = MeetingAttendance(
                meeting_id=meeting_id,
                user_id=user_id,
                external_name=None,
                checked_in_at=now,
                signature_image_path=sig_path,
            )
            self.session.add(row)
        else:
            row.checked_in_at = now
            if sig_path:
                row.signature_image_path = sig_path
        await self.session.flush()
        await self.session.refresh(row)
        logger.info("Attendance check-in: meeting=%s user=%s", meeting_id, user_id)
        return row

    async def record_external_attendee(
        self,
        meeting_id: uuid.UUID,
        name: str,
        signature_image_data: str | None = None,
    ) -> MeetingAttendance:
        """Record a walk-in / non-system attendee by name only.

        Multiple rows with the same ``external_name`` are allowed - the
        unique constraint only fires on ``(meeting_id, user_id)`` with
        non-NULL user_id.
        """
        await self.get_meeting(meeting_id)

        sig_path: str | None = None
        if signature_image_data:
            sig_path = await _save_signature_image(
                meeting_id,
                signature_image_data,
            )

        row = MeetingAttendance(
            meeting_id=meeting_id,
            user_id=None,
            external_name=name.strip(),
            checked_in_at=datetime.now(UTC),
            signature_image_path=sig_path,
        )
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        logger.info("External attendee recorded: meeting=%s name=%s", meeting_id, name)
        return row

    async def list_attendance(
        self,
        meeting_id: uuid.UUID,
    ) -> list[MeetingAttendance]:
        """List all attendance rows for a meeting (ordered by created_at)."""
        await self.get_meeting(meeting_id)
        result = await self.session.execute(
            select(MeetingAttendance)
            .where(MeetingAttendance.meeting_id == meeting_id)
            .order_by(MeetingAttendance.created_at.asc())
        )
        return list(result.scalars().all())

    # ── Action register (carry-over across a series) ──────────────────────

    async def get_action(self, action_id: uuid.UUID) -> MeetingActionItem:
        """Get a tracked action item by id. Raises 404 if not found."""
        row = await self.session.get(MeetingActionItem, action_id)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Action item not found",
            )
        return row

    async def _series_meeting_index(self, meeting: Meeting) -> dict[str, tuple[str, str | None]]:
        """Map ``meeting_id -> (meeting_number, meeting_date)`` for the scope.

        For a meeting in a series the scope is the whole series; for a one-off
        meeting it is just that meeting. Used to stamp each action with the
        date of the meeting it was raised in, which the pure carry-over logic
        needs to decide "earlier in the series".
        """
        if meeting.series_id:
            stmt = select(Meeting.id, Meeting.meeting_number, Meeting.meeting_date).where(
                Meeting.series_id == meeting.series_id
            )
        else:
            stmt = select(Meeting.id, Meeting.meeting_number, Meeting.meeting_date).where(Meeting.id == meeting.id)
        rows = (await self.session.execute(stmt)).all()
        return {str(r[0]): (r[1], r[2]) for r in rows}

    async def _load_register_rows(self, meeting: Meeting) -> list[MeetingActionItem]:
        """Load the action-register rows in scope for a meeting.

        Series meetings share a ``series_id`` so one query scoops the whole
        register; a one-off meeting is scoped to its own origin rows (its
        ``series_id`` is NULL, which must never match other one-off rows).
        """
        if meeting.series_id:
            stmt = select(MeetingActionItem).where(MeetingActionItem.series_id == meeting.series_id)
        else:
            stmt = select(MeetingActionItem).where(MeetingActionItem.origin_meeting_id == meeting.id)
        return list((await self.session.execute(stmt)).scalars().all())

    @staticmethod
    def _serialize_action_row(
        row: MeetingActionItem,
        index: dict[str, tuple[str, str | None]],
    ) -> dict[str, Any]:
        """Turn an ORM action row into the plain dict the pure logic consumes."""
        num, meeting_date = index.get(str(row.origin_meeting_id), ("", None))
        return {
            "id": str(row.id),
            "project_id": str(row.project_id),
            "series_id": row.series_id,
            "origin_meeting_id": str(row.origin_meeting_id),
            "origin_meeting_number": num,
            "origin_meeting_date": meeting_date,
            "description": row.description,
            "owner_id": row.owner_id,
            "owner_name": row.owner_name,
            "due_date": row.due_date,
            "status": row.status,
            "closed_in_meeting_id": (str(row.closed_in_meeting_id) if row.closed_in_meeting_id else None),
            "closed_at": row.closed_at.isoformat() if row.closed_at else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    async def _seed_actions_from_legacy(self, meeting: Meeting) -> None:
        """Backfill the register from a meeting's legacy ``action_items`` JSON.

        Idempotent: only runs when the meeting has legacy action items and no
        register rows of its own yet. This turns imported / AI-extracted action
        items into first-class tracked rows the first time a meeting's actions
        are opened, so nothing has to be re-typed. Seeded rows may be missing an
        owner or a due date (historical data) - they are surfaced, not blocked;
        validation only gates newly entered or edited actions.
        """
        legacy = meeting.action_items or []
        if not legacy:
            return
        exists = (
            await self.session.execute(
                select(MeetingActionItem.id).where(MeetingActionItem.origin_meeting_id == meeting.id).limit(1)
            )
        ).scalar_one_or_none()
        if exists is not None:
            return
        for ai in legacy:
            if not isinstance(ai, dict):
                continue
            desc = str(ai.get("description") or "").strip()
            if not desc:
                continue
            raw_due = ai.get("due_date")
            self.session.add(
                MeetingActionItem(
                    project_id=meeting.project_id,
                    series_id=meeting.series_id,
                    origin_meeting_id=meeting.id,
                    description=desc[:1000],
                    owner_id=ai.get("owner_id"),
                    owner_name=(ai.get("owner_name") or ai.get("owner") or None),
                    due_date=str(raw_due) if logic.is_iso_date(raw_due) else None,
                    status=logic.normalize_action_status(ai.get("status")),
                    created_by=meeting.created_by,
                    metadata_={"seeded_from": "legacy_action_items"},
                )
            )
        await self.session.flush()

    async def list_meeting_actions(
        self,
        meeting: Meeting,
        *,
        reference_date: str | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Return a meeting's own actions plus the ones brought forward into it.

        Brought-forward actions are still-live actions raised in an earlier
        meeting of the same series. Each returned dict carries the computed
        ``overdue`` and ``brought_forward`` flags, ready for the response.
        """
        await self._seed_actions_from_legacy(meeting)
        index = await self._series_meeting_index(meeting)
        rows = await self._load_register_rows(meeting)
        ref = reference_date or datetime.now(UTC).strftime("%Y-%m-%d")
        actions = [self._serialize_action_row(r, index) for r in rows]
        return logic.split_actions_for_meeting(
            actions,
            str(meeting.id),
            meeting.meeting_date,
            ref,
        )

    async def add_action(
        self,
        meeting: Meeting,
        data: ActionRegisterItemCreate,
        *,
        user_id: str | None = None,
        reference_date: str | None = None,
    ) -> dict[str, Any]:
        """Add a tracked action item to a meeting and return it serialized.

        Enforces the ownership rule (owner + due date required) at the API
        boundary. The action joins the series register via the meeting's
        ``series_id`` so it can carry forward.
        """
        await self._seed_actions_from_legacy(meeting)
        problems = logic.validate_action_fields(data.owner_id, data.owner_name, data.due_date, data.status)
        if problems:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=" ".join(problems),
            )
        row = MeetingActionItem(
            project_id=meeting.project_id,
            series_id=meeting.series_id,
            origin_meeting_id=meeting.id,
            description=data.description,
            owner_id=data.owner_id,
            owner_name=data.owner_name,
            due_date=data.due_date,
            status=data.status,
            created_by=user_id,
            metadata_={},
        )
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        logger.info("Action item added to meeting %s (status=%s)", meeting.id, row.status)
        return await self.serialize_single_action(row, reference_date=reference_date)

    async def update_action(
        self,
        row: MeetingActionItem,
        data: ActionRegisterItemUpdate,
        *,
        reference_date: str | None = None,
    ) -> dict[str, Any]:
        """Update a tracked action, closing it for the whole series if resolved.

        Moving the status to ``done`` or ``cancelled`` stamps ``closed_at`` and
        the closing meeting; reopening clears them. Because the action is a
        single row, closing it here closes it everywhere in the series.
        """
        fields = data.model_dump(exclude_unset=True)
        closing_meeting_id = fields.pop("closing_meeting_id", None)

        new_owner_id = fields.get("owner_id", row.owner_id)
        new_owner_name = fields.get("owner_name", row.owner_name)
        new_due = fields.get("due_date", row.due_date)
        new_status = fields.get("status", row.status)

        # A still-live action must keep an owner and a due date.
        if logic.action_is_live(new_status):
            problems = logic.validate_action_fields(new_owner_id, new_owner_name, new_due, new_status)
            if problems:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=" ".join(problems),
                )

        for key, value in fields.items():
            setattr(row, key, value)

        if not logic.action_is_live(new_status):  # done or cancelled
            row.closed_at = row.closed_at or datetime.now(UTC)
            if closing_meeting_id is not None:
                row.closed_in_meeting_id = closing_meeting_id
        else:  # reopened
            row.closed_at = None
            row.closed_in_meeting_id = None

        await self.session.flush()
        await self.session.refresh(row)
        logger.info("Action item %s updated (status=%s)", row.id, row.status)
        return await self.serialize_single_action(row, reference_date=reference_date)

    async def delete_action(self, row: MeetingActionItem) -> None:
        """Delete a tracked action item."""
        await self.session.delete(row)
        await self.session.flush()
        logger.info("Action item %s deleted", row.id)

    async def serialize_single_action(
        self,
        row: MeetingActionItem,
        *,
        reference_date: str | None = None,
    ) -> dict[str, Any]:
        """Serialize one action row with its overdue flag (no carry-over context)."""
        res = (
            await self.session.execute(
                select(Meeting.meeting_number, Meeting.meeting_date).where(Meeting.id == row.origin_meeting_id)
            )
        ).first()
        index = {str(row.origin_meeting_id): (res[0] if res else "", res[1] if res else None)}
        ref = reference_date or datetime.now(UTC).strftime("%Y-%m-%d")
        return logic.annotate_action(self._serialize_action_row(row, index), ref)

    async def series_action_register(
        self,
        master: Meeting,
        *,
        reference_date: str | None = None,
    ) -> tuple[str | None, list[dict[str, Any]], dict[str, int]]:
        """Return every action across a series with a status roll-up.

        Scoped to the series the meeting belongs to (or the single meeting for a
        one-off). Actions are returned newest-origin first with overdue flags.
        """
        series_id = master.series_id
        index = await self._series_meeting_index(master)
        rows = await self._load_register_rows(master)
        ref = reference_date or datetime.now(UTC).strftime("%Y-%m-%d")
        actions = [self._serialize_action_row(r, index) for r in rows]
        summary = logic.summarize_register(actions, ref)
        annotated = [logic.annotate_action(a, ref) for a in actions]
        # Sort by origin meeting date (newest first), then due date.
        annotated.sort(
            key=lambda a: (
                str(a.get("origin_meeting_date") or ""),
                str(a.get("due_date") or ""),
            ),
            reverse=True,
        )
        return series_id, annotated, summary

    # ── Auto-draft minutes ────────────────────────────────────────────────

    async def get_minutes_row(self, meeting_id: uuid.UUID) -> MeetingMinutes | None:
        """Load the minutes document for a meeting, or ``None``."""
        return (
            await self.session.execute(select(MeetingMinutes).where(MeetingMinutes.meeting_id == meeting_id))
        ).scalar_one_or_none()

    async def _checked_in_keys(self, meeting_id: uuid.UUID) -> set[str]:
        """Return the set of names / user ids that actually checked in."""
        rows = await self.list_attendance(meeting_id)
        keys: set[str] = set()
        for row in rows:
            if row.checked_in_at is None:
                continue
            if row.user_id:
                keys.add(str(row.user_id))
            if row.external_name:
                keys.add(row.external_name)
        return keys

    def _chairperson_display(self, meeting: Meeting) -> str:
        """Resolve a human chairperson label from id + metadata name."""
        meta = meeting.metadata_ or {}
        name = str(meta.get("chairperson_name") or "").strip()
        if name:
            return name
        raw = str(meeting.chairperson_id or "").strip()
        # A bare contact UUID is not a name; hide it.
        try:
            uuid.UUID(raw)
        except (ValueError, TypeError):
            return raw
        return ""

    def _meeting_minutes_dict(self, meeting: Meeting, req: MinutesGenerateRequest) -> dict[str, Any]:
        """Build the plain meeting dict the pure minutes builder consumes.

        Applies any per-agenda discussion/decision overrides from the request,
        matched by agenda number first, then by topic, then by position.
        """
        agenda_items = [dict(a) for a in (meeting.agenda_items or []) if isinstance(a, dict)]
        overrides = req.agenda or []
        for pos, ov in enumerate(overrides):
            target: dict[str, Any] | None = None
            if ov.number:
                target = next((a for a in agenda_items if str(a.get("number")) == str(ov.number)), None)
            if target is None and ov.topic:
                target = next(
                    (a for a in agenda_items if str(a.get("topic") or a.get("title")) == ov.topic),
                    None,
                )
            if target is None and pos < len(agenda_items):
                target = agenda_items[pos]
            if target is None:
                # A brand-new agenda line supplied only in the minutes request.
                target = {"number": ov.number, "topic": ov.topic}
                agenda_items.append(target)
            if ov.discussion is not None:
                target["discussion"] = ov.discussion
            if ov.decision is not None:
                target["decision"] = ov.decision
            if ov.presenter is not None:
                target["presenter"] = ov.presenter
            if ov.required:
                target["required"] = True
        return {
            "title": meeting.title,
            "meeting_number": meeting.meeting_number,
            "meeting_type": meeting.meeting_type,
            "meeting_date": meeting.meeting_date,
            "location": meeting.location,
            "chairperson": self._chairperson_display(meeting),
            "attendees": meeting.attendees or [],
            "agenda_items": agenda_items,
            "minutes": meeting.minutes,
            "metadata": meeting.metadata_ or {},
        }

    async def _infer_next_meeting_date(self, meeting: Meeting) -> str | None:
        """Find the next scheduled occurrence date after this meeting (series)."""
        if not meeting.series_id:
            return None
        stmt = (
            select(Meeting.meeting_date)
            .where(Meeting.series_id == meeting.series_id)
            .where(Meeting.meeting_date > meeting.meeting_date)
            .order_by(Meeting.meeting_date.asc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def generate_minutes(
        self,
        meeting: Meeting,
        req: MinutesGenerateRequest,
        *,
        user_id: str | None = None,
    ) -> MeetingMinutes:
        """Generate (or refresh) the draft minutes for a meeting.

        The draft assembles who was present/absent, the per-agenda discussion
        and decision, the action items (brought-forward first) and the next
        meeting date. An already-issued document is never silently rebuilt.
        """
        existing = await self.get_minutes_row(meeting.id)
        if existing is not None and existing.status == "issued":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Minutes have already been issued for this meeting",
            )

        own, brought = await self.list_meeting_actions(meeting)
        checked_in = await self._checked_in_keys(meeting.id)
        next_md = (
            req.next_meeting_date
            or (existing.next_meeting_date if existing else None)
            or await self._infer_next_meeting_date(meeting)
        )
        content = logic.build_minutes_content(
            self._meeting_minutes_dict(meeting, req),
            own,
            brought,
            checked_in,
            next_meeting_date=next_md,
            generated_at=datetime.now(UTC).isoformat(),
        )

        if existing is not None:
            # Keep human edits unless the caller explicitly asks to rebuild.
            if req.regenerate or not existing.content:
                existing.content = content
            existing.next_meeting_date = next_md
            row = existing
        else:
            row = MeetingMinutes(
                project_id=meeting.project_id,
                meeting_id=meeting.id,
                status="draft",
                content=content,
                next_meeting_date=next_md,
                created_by=user_id,
                distributed_to=[],
                metadata_={},
            )
            self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        logger.info("Minutes generated for meeting %s (status=%s)", meeting.id, row.status)
        return row

    async def update_minutes(
        self,
        row: MeetingMinutes,
        data: MinutesUpdate,
    ) -> MeetingMinutes:
        """Apply human edits to a draft minutes document."""
        if row.status == "issued":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Issued minutes can no longer be edited",
            )
        if data.content is not None:
            row.content = data.content
        if data.next_meeting_date is not None:
            row.next_meeting_date = data.next_meeting_date
            # Keep the embedded content in sync so the PDF matches.
            if isinstance(row.content, dict):
                row.content = {**row.content, "next_meeting_date": data.next_meeting_date}
        await self.session.flush()
        await self.session.refresh(row)
        return row

    async def issue_minutes(
        self,
        row: MeetingMinutes,
        *,
        user_id: str | None = None,
    ) -> MeetingMinutes:
        """Issue the minutes after the readiness validation passes.

        Blocks while a required agenda item is unaddressed or no attendee is
        marked present. Issuing is the human-confirmed step; nothing is auto-issued.
        """
        content = row.content if isinstance(row.content, dict) else {}
        problems = logic.minutes_issue_problems(content)
        if problems:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=" ".join(problems),
            )
        row.status = "issued"
        row.issued_at = datetime.now(UTC)
        row.issued_by = user_id
        await self.session.flush()
        await self.session.refresh(row)
        logger.info("Minutes issued for meeting %s", row.meeting_id)
        return row

    async def distribute_minutes(
        self,
        meeting: Meeting,
        row: MeetingMinutes,
        *,
        user_id: str | None = None,
    ) -> tuple[MeetingMinutes, list[str]]:
        """Notify the meeting's attendees that the minutes are available.

        Reuses the platform notification service (the same in-app + connector
        sink every other module uses). Only attendees linked to a real user
        (a contact id) can be notified; walk-in guests have no inbox. Issued
        minutes only.
        """
        if row.status != "issued":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Issue the minutes before distributing them",
            )

        recipient_ids: list[str] = []
        seen: set[str] = set()
        for att in meeting.attendees or []:
            if not isinstance(att, dict):
                continue
            uid = str(att.get("user_id") or "").strip()
            if not uid or uid in seen:
                continue
            try:
                uuid.UUID(uid)
            except (ValueError, TypeError):
                continue
            seen.add(uid)
            recipient_ids.append(uid)

        notified: list[str] = []
        if recipient_ids:
            try:
                from app.modules.notifications.service import NotificationService

                notif_svc = NotificationService(self.session)
                await notif_svc.notify_users(
                    recipient_ids,
                    "info",
                    "notification.meeting_minutes_issued_title",
                    entity_type="meeting",
                    entity_id=str(meeting.id),
                    body_key="notification.meeting_minutes_issued_body",
                    body_context={
                        "meeting_number": meeting.meeting_number,
                        "title": meeting.title,
                    },
                    action_url="/meetings",
                    metadata={"minutes_id": str(row.id)},
                )
                notified = recipient_ids
            except Exception:  # best-effort - never fail distribution on the sink
                logger.exception("Failed to send meeting minutes notifications")

        row.distributed_at = datetime.now(UTC)
        row.distributed_to = notified
        await self.session.flush()
        await self.session.refresh(row)
        logger.info(
            "Minutes for meeting %s distributed to %d recipient(s)",
            meeting.id,
            len(notified),
        )
        return row, notified


# ── RRULE parser (subset of RFC 5545) ─────────────────────────────────────


class _RRuleError(ValueError):
    """Raised when a recurrence_rule string cannot be parsed."""


_WEEKDAY_MAP = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


def _expand_rrule(
    rule: str,
    start: datetime,
    until: datetime,
) -> list[datetime]:
    """Expand an RRULE string into a list of datetimes ≤ ``until``.

    Prefers ``dateutil.rrule.rrulestr`` when available; falls back to a
    minimal hand-rolled parser for FREQ=DAILY/WEEKLY/MONTHLY + BYDAY +
    COUNT/UNTIL so the feature still works on stripped-down deploys.

    Includes the start datetime itself only if the RRULE would emit it
    (e.g. WEEKLY BYDAY containing the start's weekday).
    """
    # ── Fast path: python-dateutil is present in transitive deps. ───────
    try:
        from dateutil.rrule import rrulestr  # type: ignore[import-untyped]

        rs = rrulestr(rule, dtstart=start)
        out: list[datetime] = []
        for occ in rs:
            # rrulestr yields naive or tz-aware depending on dtstart; we
            # always feed it tz-aware so occurrences are tz-aware too.
            if occ.tzinfo is None:
                occ = occ.replace(tzinfo=UTC)
            if occ > until:
                break
            out.append(occ)
        return out
    except ImportError:
        pass  # fall through to hand-rolled parser
    except Exception as exc:  # noqa: BLE001 - surface as RRuleError for the router
        raise _RRuleError(str(exc)) from exc

    # ── Fallback parser ─────────────────────────────────────────────────
    parts = dict(_parse_rrule_parts(rule))
    freq = parts.get("FREQ", "")
    count = int(parts["COUNT"]) if "COUNT" in parts else None
    rule_until: datetime | None = None
    if "UNTIL" in parts:
        try:
            rule_until = datetime.strptime(
                parts["UNTIL"][:8],
                "%Y%m%d",
            ).replace(tzinfo=UTC)
        except ValueError as exc:
            raise _RRuleError(f"bad UNTIL: {parts['UNTIL']}") from exc

    bydays = [_WEEKDAY_MAP[d] for d in parts["BYDAY"].split(",") if d in _WEEKDAY_MAP] if "BYDAY" in parts else []

    horizon = until if rule_until is None else min(until, rule_until)
    results: list[datetime] = []

    if freq == "DAILY":
        cur = start
        while cur <= horizon:
            results.append(cur)
            if count is not None and len(results) >= count:
                break
            cur = cur + timedelta(days=1)

    elif freq == "WEEKLY":
        cur = start
        while cur <= horizon:
            if not bydays or cur.weekday() in bydays:
                results.append(cur)
                if count is not None and len(results) >= count:
                    break
            cur = cur + timedelta(days=1)

    elif freq == "MONTHLY":
        cur = start
        while cur <= horizon:
            results.append(cur)
            if count is not None and len(results) >= count:
                break
            # naive month-add: bump month, clamp day
            month = cur.month + 1
            year = cur.year + (month - 1) // 12
            month = ((month - 1) % 12) + 1
            day = min(cur.day, _days_in_month(year, month))
            cur = cur.replace(year=year, month=month, day=day)

    else:
        raise _RRuleError(f"unsupported FREQ={freq!r}")

    return results


def _parse_rrule_parts(rule: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for chunk in rule.split(";"):
        if "=" not in chunk:
            continue
        k, v = chunk.split("=", 1)
        out.append((k.strip().upper(), v.strip()))
    return out


def _days_in_month(year: int, month: int) -> int:
    if month == 2:
        leap = (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)
        return 29 if leap else 28
    if month in (4, 6, 9, 11):
        return 30
    return 31


# ── Signature image storage ──────────────────────────────────────────────


_SIGNATURE_DIR_ENV = "MEETING_SIGNATURE_DIR"


def _signature_dir() -> Path:
    import os

    base = os.environ.get(_SIGNATURE_DIR_ENV)
    if base:
        return Path(base)
    # Default to <home>/.openestimator/meetings/signatures (matches the
    # uploads scheme in router.py's transcript cross-link).
    return Path.home() / ".openestimator" / "meetings" / "signatures"


async def _save_signature_image(
    meeting_id: uuid.UUID,
    data: str,
) -> str:
    """Decode + persist a signature image, return the saved file path.

    Accepts either a ``data:image/png;base64,...`` URL or bare base64
    bytes. Caps payload at 2MB (enforced upstream by the schema) and
    silently strips anything that's not a PNG/JPEG by inspecting the
    decoded magic bytes.
    """
    raw = data.strip()
    m = re.match(r"^data:image/(png|jpeg|jpg);base64,(.+)$", raw, re.IGNORECASE)
    payload = m.group(2) if m else raw

    try:
        blob = base64.b64decode(payload, validate=False)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="signature_image_data is not valid base64",
        ) from exc

    # Magic-byte check: 89 50 4E 47 = PNG, FF D8 FF = JPEG.
    ext: str
    if blob[:4] == b"\x89PNG":
        ext = "png"
    elif blob[:3] == b"\xff\xd8\xff":
        ext = "jpg"
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="signature_image_data must be PNG or JPEG",
        )

    out_dir = _signature_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{meeting_id}_{uuid.uuid4().hex[:12]}.{ext}"
    out_path.write_bytes(blob)
    return str(out_path)
