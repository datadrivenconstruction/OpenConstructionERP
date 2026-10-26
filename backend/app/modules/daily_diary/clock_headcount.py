# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Daily diary headcount from the field time clock​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠.

When a worker clocks in, the open diary of that project-day learns how many
distinct workers have clocked in so far. The count lands in the diary's
``metadata.clock_headcount`` and lifts ``labour_count`` when the clock saw more
people than were typed; it never lowers a typed figure (subcontract gangs who
do not clock are still on site). A day with no diary yet gets nothing: a
diary is opened by a person, and it picks the count up on the next clock-in.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import Event, event_bus

logger = logging.getLogger(__name__)

CLOCK_IN_EVENT = "field_time.clock_in"


async def clock_headcount_for(session: AsyncSession, project_id: uuid.UUID, day: date) -> int:
    """Distinct workers who clocked in on the project on a UTC day (0 without the module)."""
    try:
        from app.modules.field_time.models import FieldClockEvent
    except Exception:
        return 0
    start = datetime.combine(day, time.min, tzinfo=UTC)
    stmt = select(func.count(func.distinct(FieldClockEvent.resource_id))).where(
        FieldClockEvent.project_id == project_id,
        FieldClockEvent.kind == "in",
        FieldClockEvent.occurred_at >= start,
        FieldClockEvent.occurred_at < start + timedelta(days=1),
    )
    return int((await session.execute(stmt)).scalar() or 0)


async def apply_headcount(session: AsyncSession, project_id: uuid.UUID, day: date) -> int | None:
    """Write the clock headcount onto the day's open diary; returns it, None when no diary."""
    from app.modules.daily_diary.models import DailyDiary

    diary = (
        await session.execute(
            select(DailyDiary).where(DailyDiary.project_id == project_id, DailyDiary.diary_date == day.isoformat())
        )
    ).scalar_one_or_none()
    if diary is None or diary.status != "open":
        return None
    count = await clock_headcount_for(session, project_id, day)
    meta = dict(diary.metadata_ or {})
    meta["clock_headcount"] = count
    diary.metadata_ = meta
    if count > (diary.labour_count or 0):
        diary.labour_count = count
    await session.flush()
    return count


async def _on_clock_in(event: Event) -> None:
    data = event.data or {}
    try:
        project_id = uuid.UUID(str(data.get("project_id")))
        day = date.fromisoformat(str(data.get("work_date")))
    except (TypeError, ValueError):
        return
    from app.database import async_session_factory

    try:
        async with async_session_factory() as session:
            await apply_headcount(session, project_id, day)
            await session.commit()
    except Exception:
        logger.debug("Diary headcount from clock skipped for project=%s", project_id, exc_info=True)


def register_clock_headcount() -> None:
    """Idempotently subscribe the diary to clock-ins."""
    event_bus.subscribe_once(CLOCK_IN_EVENT, _on_clock_in)
