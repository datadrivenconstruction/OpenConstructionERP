# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Formwork strike suggestions from site sensors.

When a concrete maturity sensor reports that a pour reached the strike
strength of a formwork strip, the strip's linked activity gets a pending
``strike_suggestion`` in its metadata. Nothing moves until a person accepts
it: accepting pins the activity to start today and reschedules the network
so the successors roll with it.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.schedule.models import Activity, Schedule

logger = logging.getLogger(__name__)

SUGGESTION_KEY = "strike_suggestion"
# The maturity method is an estimate until a cube or core test confirms it.
MATURITY_CONFIDENCE = 0.8


def _parse_day(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


async def activity_in_project(session: AsyncSession, activity_id: uuid.UUID, project_id: uuid.UUID) -> Activity | None:
    """The activity, if it exists and belongs to a schedule of the project."""
    activity = await session.get(Activity, activity_id)
    if activity is None:
        return None
    schedule = await session.get(Schedule, activity.schedule_id)
    if schedule is None or schedule.project_id != project_id:
        return None
    return activity


async def record_strike_suggestion(session: AsyncSession, data: dict[str, Any]) -> Activity | None:
    """Store a pending strike suggestion on the strip's activity. Returns it, or None if skipped."""
    try:
        activity_id = uuid.UUID(str(data.get("schedule_activity_id")))
        project_id = uuid.UUID(str(data.get("project_id")))
    except (TypeError, ValueError):
        return None
    activity = await activity_in_project(session, activity_id, project_id)
    if activity is None:
        logger.info("strike suggestion skipped: activity %s not in project %s", activity_id, project_id)
        return None
    meta = dict(activity.metadata_ or {})
    current = meta.get(SUGGESTION_KEY)
    if isinstance(current, dict) and current.get("strip_id") == str(data.get("strip_id")):
        return activity
    today = datetime.now(UTC).date()
    meta[SUGGESTION_KEY] = {
        "status": "pending",
        "strip_id": str(data.get("strip_id") or ""),
        "device_id": str(data.get("device_id") or ""),
        "strength_mpa": data.get("strength_mpa"),
        "target_mpa": data.get("target_mpa"),
        "proposed_start": today.isoformat(),
        "planned_start": activity.start_date,
        "confidence": MATURITY_CONFIDENCE,
        "raised_at": datetime.now(UTC).isoformat(),
    }
    activity.metadata_ = meta
    await session.flush()
    return activity


async def resolve_strike_suggestion(
    session: AsyncSession, activity: Activity, *, accept: bool, user_id: str | None
) -> Activity:
    """Accept or dismiss the pending suggestion.

    Raises:
        LookupError: the activity has no pending suggestion.
    """
    meta = dict(activity.metadata_ or {})
    sug = meta.get(SUGGESTION_KEY)
    if not isinstance(sug, dict) or sug.get("status") != "pending":
        raise LookupError("no_pending_strike_suggestion")
    sug = {**sug, "status": "accepted" if accept else "dismissed", "resolved_by": user_id}
    sug["resolved_at"] = datetime.now(UTC).isoformat()
    meta[SUGGESTION_KEY] = sug
    activity.metadata_ = meta
    if accept:
        new_start = _parse_day(sug.get("proposed_start")) or datetime.now(UTC).date()
        old_start = _parse_day(activity.start_date)
        old_end = _parse_day(activity.end_date)
        span = (old_end - old_start) if old_start and old_end and old_end >= old_start else timedelta(0)
        activity.start_date = new_start.isoformat()
        activity.end_date = (new_start + span).isoformat()
        activity.constraint_type = "must_start_on"
        activity.constraint_date = new_start.isoformat()
    await session.flush()
    if accept:
        from app.modules.schedule.service import ScheduleService

        try:
            await ScheduleService(session).reschedule(activity.schedule_id)
        except Exception:
            logger.warning("reschedule after strike acceptance failed", exc_info=True)
    return activity
