"""Meetings service — business logic for meeting management.

Stateless service layer. Handles:
- Meeting CRUD
- Auto-generated meeting numbers (MTG-001, MTG-002, ...)
- Status transitions (draft -> scheduled -> in_progress -> completed)
- Action item -> Task creation on meeting completion
"""

import logging
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.modules.meetings.models import Meeting
from app.modules.meetings.repository import MeetingRepository
from app.modules.meetings.schemas import (
    MeetingCreate,
    MeetingStatsResponse,
    MeetingUpdate,
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
    """Best-effort audit log — never blocks the caller on failure."""
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

    # ── Create ────────────────────────────────────────────────────────────

    async def create_meeting(
        self,
        data: MeetingCreate,
        user_id: str | None = None,
    ) -> Meeting:
        """Create a new meeting with auto-generated meeting number."""
        meeting_number = await self.repo.next_meeting_number(data.project_id)

        attendees_data = [entry.model_dump() for entry in data.attendees]
        agenda_data = [entry.model_dump() for entry in data.agenda_items]
        action_data = [entry.model_dump() for entry in data.action_items]

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
    ) -> tuple[list[Meeting], int]:
        """List meetings for a project with optional search."""
        return await self.repo.list_for_project(
            project_id,
            offset=offset,
            limit=limit,
            meeting_type=meeting_type,
            status=status_filter,
            search=search,
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
            fields["metadata_"] = fields.pop("metadata")

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
                fields[key] = [
                    entry.model_dump() if hasattr(entry, "model_dump") else entry
                    for entry in fields[key]
                ]

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
        auto-created via ``complete_meeting`` — preventing dangling FK
        pointers without destroying the user's task history.
        """
        await self.get_meeting(meeting_id)  # Raises 404 if not found

        # Clear the meeting_id FK on tasks that reference this meeting
        try:
            from sqlalchemy import update as _update

            from app.modules.tasks.models import Task

            result = await self.session.execute(
                _update(Task)
                .where(Task.meeting_id == str(meeting_id))
                .values(meeting_id=None)
            )
            if result.rowcount:
                logger.info(
                    "Cleared meeting_id on %d tasks before deleting meeting %s",
                    result.rowcount, meeting_id,
                )
        except Exception as exc:  # best-effort cleanup
            logger.warning(
                "Failed to scrub task.meeting_id refs for meeting %s: %s",
                meeting_id, exc,
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
                detail="Cannot complete a draft meeting — schedule it first",
            )

        await self.repo.update_fields(meeting_id, status="completed")
        await self.session.refresh(meeting)
        logger.info("Meeting completed: %s", meeting_id)

        # Create tasks from open action items.  Per-item isolation: a
        # single failed action item does not abort the others, AND the
        # event payload only carries the action items that ACTUALLY
        # produced a Task row.  The previous version wrapped the
        # whole loop in a try/except and then published a "tasks
        # created" event regardless — even if zero tasks were
        # created, downstream subscribers were told the work was
        # done.  Now the event payload + the meeting completion
        # response surface the real success/failure breakdown so the
        # UI can show "3 of 5 tasks created" instead of lying.
        action_items = meeting.action_items or []
        open_actions = [
            ai
            for ai in action_items
            if isinstance(ai, dict) and ai.get("status", "open") == "open"
        ]
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
                        description=(
                            f"Auto-created from meeting {meeting.meeting_number}: "
                            f"{meeting.title}"
                        ),
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
                except Exception as exc:  # noqa: BLE001 — per-item isolation
                    logger.warning(
                        "Failed to create task from meeting %s action item: %s",
                        meeting.meeting_number,
                        exc,
                    )
                    failed_action_items.append({**ai, "error": str(exc)})

            logger.info(
                "Meeting %s: %d/%d tasks created from action items "
                "(%d failed)",
                meeting.meeting_number,
                len(created_action_items),
                len(open_actions),
                len(failed_action_items),
            )

            # Only publish the event if at least one task actually
            # made it into the DB.  An empty creation set means
            # downstream subscribers (notifications, vector index)
            # have nothing to consume — publishing would be a lie.
            if created_action_items:
                await event_bus.publish(
                    "meeting.action_items_created",
                    {
                        "meeting_id": str(meeting.id),
                        "project_id": str(meeting.project_id),
                        "meeting_number": meeting.meeting_number,
                        "action_items": created_action_items,
                        "failed_action_items": failed_action_items,
                        "created_count": len(created_action_items),
                        "failed_count": len(failed_action_items),
                    },
                    source_module="meetings",
                )

        # Stash the per-item breakdown on the returned meeting so the
        # router can surface it in the response payload.  Setting it
        # via setattr keeps the ORM model unchanged — this is a
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
        action_items arrays of all non-cancelled meetings.
        """
        raw = await self.repo.stats_for_project(project_id)

        # Count open action items by scanning JSON columns
        meetings = await self.repo.all_for_project(project_id)
        open_count = 0
        for m in meetings:
            for ai in m.action_items or []:
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
        meetings = await self.repo.all_for_project(project_id)
        result: list[OpenActionItemResponse] = []
        for m in meetings:
            for ai in m.action_items or []:
                if isinstance(ai, dict) and ai.get("status", "open") == "open":
                    result.append(
                        OpenActionItemResponse(
                            meeting_id=m.id,
                            meeting_number=m.meeting_number,
                            meeting_title=m.title,
                            meeting_date=m.meeting_date,
                            description=ai.get("description", ""),
                            owner_id=ai.get("owner_id"),
                            due_date=ai.get("due_date"),
                        )
                    )
        return result
