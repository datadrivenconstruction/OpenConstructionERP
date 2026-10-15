"""Activity calendars, the reset guard and the schedule end date.

Three defects reported against the 4D schedule:

* Picking a calendar on an activity left its duration as the project week
  had counted it: a calendar without days off still read ten days for two
  weeks of work.
* "Clear all activities" stayed available on an activated schedule, whose
  plan the site already works to.
* The schedule's end date stayed where it was typed when activities moved
  past it, and could not be edited either.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.modules.schedule.progress_service import ScheduleProgressService
from app.modules.schedule.schemas import ActivityCreate, ActivityUpdate, ScheduleCreate
from app.modules.schedule.service import ScheduleService
from tests._pg import transactional_session

# Monday 4 May to Friday 15 May 2026: ten weekdays, twelve days in all.
START = "2026-05-04"
END = "2026-05-15"


async def _project(session) -> uuid.UUID:  # noqa: ANN001
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    user = User(
        email=f"cal-{uuid.uuid4().hex[:8]}@schedule-cal.io",
        hashed_password="x",
        full_name="Planner",
        role="editor",
        is_active=True,
    )
    session.add(user)
    await session.flush()
    project = Project(name="Calendar QA", owner_id=user.id)
    session.add(project)
    await session.flush()
    return project.id


async def _calendar(session, project_id: uuid.UUID, work_days: list[int]) -> uuid.UUID:  # noqa: ANN001
    from app.modules.schedule_advanced.models import Calendar

    cal = Calendar(project_id=project_id, name=f"Week {len(work_days)}", work_days=work_days, holidays=[])
    session.add(cal)
    await session.flush()
    return cal.id


async def _schedule(session):  # noqa: ANN001, ANN202
    project_id = await _project(session)
    service = ScheduleService(session)
    schedule = await service.create_schedule(
        ScheduleCreate(project_id=project_id, name="Plan", start_date=START, end_date="2026-05-31")
    )
    return service, schedule.id, project_id


async def _task(service: ScheduleService, schedule_id: uuid.UUID, name: str, start: str, end: str):  # noqa: ANN202
    return await service.create_activity(
        ActivityCreate(schedule_id=schedule_id, name=name, start_date=start, end_date=end)
    )


@pytest.mark.asyncio
async def test_picking_a_seven_day_calendar_recounts_the_duration() -> None:
    async with transactional_session() as session:
        service, schedule_id, project_id = await _schedule(session)
        act = await _task(service, schedule_id, "Formwork", START, END)
        assert act.duration_days == 10

        every_day = await _calendar(session, project_id, [0, 1, 2, 3, 4, 5, 6])
        progress = ScheduleProgressService(session)
        updated = await progress.set_calendar(act.id, every_day)
        assert updated.calendar_id == every_day
        assert updated.duration_days == 12
        assert (updated.start_date, updated.end_date) == (START, END)

        # Back to the project week, back to its count.
        cleared = await progress.set_calendar(act.id, None)
        assert cleared.duration_days == 10


@pytest.mark.asyncio
async def test_a_date_edit_counts_on_the_activitys_own_calendar() -> None:
    async with transactional_session() as session:
        service, schedule_id, project_id = await _schedule(session)
        act = await _task(service, schedule_id, "Rebar", START, START)
        six_days = await _calendar(session, project_id, [0, 1, 2, 3, 4, 5])
        await ScheduleProgressService(session).set_calendar(act.id, six_days)

        moved = await service.update_activity(act.id, ActivityUpdate(end_date=END))
        assert moved.duration_days == 11


@pytest.mark.asyncio
async def test_a_milestone_keeps_no_working_days_on_a_calendar() -> None:
    async with transactional_session() as session:
        service, schedule_id, project_id = await _schedule(session)
        ms = await service.create_activity(
            ActivityCreate(
                schedule_id=schedule_id, name="Handover", start_date=END, end_date=END, activity_type="milestone"
            )
        )
        every_day = await _calendar(session, project_id, [0, 1, 2, 3, 4, 5, 6])
        updated = await ScheduleProgressService(session).set_calendar(ms.id, every_day)
        assert updated.duration_days == ms.duration_days


@pytest.mark.asyncio
async def test_reset_is_refused_once_the_schedule_is_active() -> None:
    async with transactional_session() as session:
        service, schedule_id, _ = await _schedule(session)
        await _task(service, schedule_id, "Excavation", START, END)

        from app.modules.schedule.schemas import ScheduleUpdate

        await service.update_schedule(schedule_id, ScheduleUpdate(status="active"))
        with pytest.raises(HTTPException) as refused:
            await service.clear_activities(schedule_id)
        assert refused.value.status_code == 409
        assert refused.value.detail["error"] == "schedule_not_draft"
        rows, _ = await service.list_activities_for_schedule(schedule_id)
        assert len(rows) == 1


@pytest.mark.asyncio
async def test_reset_still_clears_a_draft() -> None:
    async with transactional_session() as session:
        service, schedule_id, _ = await _schedule(session)
        await _task(service, schedule_id, "Excavation", START, END)
        assert await service.clear_activities(schedule_id) == 1


async def _end_date(service: ScheduleService, schedule_id: uuid.UUID) -> str | None:
    service.session.expire_all()
    return (await service.get_schedule(schedule_id)).end_date


@pytest.mark.asyncio
async def test_the_schedule_ends_with_its_latest_activity() -> None:
    async with transactional_session() as session:
        service, schedule_id, _ = await _schedule(session)
        first = await _task(service, schedule_id, "Foundations", START, END)
        assert await _end_date(service, schedule_id) == END

        late = await _task(service, schedule_id, "Roof", "2026-06-01", "2026-06-30")
        assert await _end_date(service, schedule_id) == "2026-06-30"

        await service.update_activity(late.id, ActivityUpdate(end_date="2026-07-10"))
        assert await _end_date(service, schedule_id) == "2026-07-10"

        # Pulled in again, the end follows it back.
        await service.update_activity(late.id, ActivityUpdate(end_date="2026-06-12"))
        assert await _end_date(service, schedule_id) == "2026-06-12"

        await service.delete_activity(late.id)
        assert await _end_date(service, schedule_id) == END

        await service.update_activity(first.id, ActivityUpdate(name="Footings"))
        assert await _end_date(service, schedule_id) == END
