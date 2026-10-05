# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Announce a schedule milestone the moment it is reached, and when it is reopened.

Payment plans (contract milestones, property sales instalments) fall due on a
milestone of the programme, so the schedule has to tell the rest of the
platform when one is reached. Every path that can complete an activity calls
:func:`announce_if_milestone_reached` after its write, handing over whether
the activity was complete before it.

- not complete -> complete publishes ``schedule.milestone.reached``, once:
  the activity's ``metadata_["milestone_reached_at"]`` records the
  announcement, and a milestone that already carries it is not announced
  again.
- complete -> not complete publishes ``schedule.milestone.reopened`` and
  clears that marker, so completing it again announces it again. Only a
  milestone carrying the marker is reopened: one that was never announced
  (imported finished, or completed before this existed) withdraws nothing,
  and a reopen would tell subscribers to undo a completion they never saw.
- Anything that is not a milestone, and a complete -> complete re-save, is
  silent.

Imports do not call this. A schedule imported with finished milestones
records history, not something that just happened on site, and announcing it
would mark instalments due for work completed long before the import.

Both events are published only after the caller's transaction commits
(:func:`~app.core.events.publish_after_commit`): subscribers open their own
sessions, and a save that rolls back must not have announced anything.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import publish_after_commit
from app.modules.schedule.models import Activity, Schedule
from app.modules.schedule.repository import ActivityRepository

logger = logging.getLogger(__name__)

#: Activity types that mark a point in the programme rather than work. The
#: activity API only writes ``milestone``; the start/finish variants arrive
#: from scheduling-tool imports and mean the same thing to a payment plan.
#: A zero-duration ``task`` is deliberately not a milestone: an activity
#: created without dates also has zero duration.
MILESTONE_ACTIVITY_TYPES: frozenset[str] = frozenset({"milestone", "start_milestone", "finish_milestone"})

#: Metadata key that records the announcement, so it is made once.
REACHED_AT_KEY = "milestone_reached_at"

#: Status every completion path writes for a finished activity.
_STATUS_COMPLETED = "completed"


def is_milestone(activity: Activity) -> bool:
    """Whether *activity* is a milestone for payment purposes."""
    return (activity.activity_type or "") in MILESTONE_ACTIVITY_TYPES


def is_completed(status: str | None, progress_pct: object) -> bool:
    """Whether an activity with this status and progress counts as complete.

    The same test the schedule service uses for its completion guard: the
    stored status says so, or progress has reached 100.
    """
    if status == _STATUS_COMPLETED:
        return True
    try:
        return float(str(progress_pct)) >= 100.0
    except (TypeError, ValueError):
        return False


def _iso_date(value: str | None) -> str | None:
    """The ``YYYY-MM-DD`` part of *value*, or ``None`` when it is not a date."""
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except ValueError:
        return None


async def announce_if_milestone_reached(
    session: AsyncSession,
    activity: Activity,
    *,
    was_completed: bool,
    actor_id: uuid.UUID | str | None,
    reached_on: str | None = None,
) -> str | None:
    """Publish the milestone event this activity's latest write calls for.

    Call after the write, with the activity as it now stands (re-read it if
    the write expired it) and whether it was complete before the write.

    Args:
        session: The session the write ran in; the event follows its commit.
        activity: The activity after the write.
        was_completed: Whether the activity counted as complete before it.
        actor_id: The user who made the change, when known.
        reached_on: The actual finish date the caller recorded, when it has
            one. Defaults to today.

    Returns:
        The event name published, or ``None`` when nothing was.
    """
    if not is_milestone(activity):
        return None

    now_completed = is_completed(activity.status, activity.progress_pct)
    metadata = dict(activity.metadata_ or {})
    announced = metadata.get(REACHED_AT_KEY)

    if now_completed and not was_completed:
        if announced:
            return None
        event_name = "schedule.milestone.reached"
        reached_at = _iso_date(reached_on) or datetime.now(UTC).date().isoformat()
        metadata[REACHED_AT_KEY] = reached_at
    elif was_completed and not now_completed:
        if not announced:
            return None
        event_name = "schedule.milestone.reopened"
        reached_at = announced
        del metadata[REACHED_AT_KEY]
    else:
        return None

    activity_id = activity.id
    schedule_id = activity.schedule_id
    payload: dict[str, Any] = {
        "project_id": None,
        "schedule_id": str(schedule_id),
        "activity_id": str(activity_id),
        "activity_name": activity.name,
        "reached_at": reached_at,
        "actor_id": str(actor_id) if actor_id is not None else None,
        "milestone_event": metadata.get("milestone_event") or None,
        "sales_contract_id": metadata.get("sales_contract_id") or None,
    }

    project_id = await session.scalar(select(Schedule.project_id).where(Schedule.id == schedule_id))
    payload["project_id"] = str(project_id) if project_id is not None else None

    if metadata != dict(activity.metadata_ or {}):
        await ActivityRepository(session).update_fields(activity_id, metadata_=metadata)

    # Each name spelled out at its call: tests/unit/test_event_name_wiring.py
    # finds publishers by the literal in the publish call.
    if event_name == "schedule.milestone.reached":
        publish_after_commit(session, "schedule.milestone.reached", payload, source_module="oe_schedule")
    else:
        publish_after_commit(session, "schedule.milestone.reopened", payload, source_module="oe_schedule")

    logger.info("Milestone %s %s", activity_id, event_name.rsplit(".", 1)[-1])
    return event_name
