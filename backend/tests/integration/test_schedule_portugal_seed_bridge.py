"""PT/2026 seed dates reach actual generated schedules, with explicit year gaps."""

import uuid
from datetime import date

import pytest

from app.modules.boq.models import BOQ, Position
from app.modules.projects.models import Project
from app.modules.schedule.schemas import ScheduleCreate, ScheduleUpdate
from app.modules.schedule.service import ScheduleService
from app.modules.schedule_advanced.models import Calendar
from app.modules.users.models import User
from tests._pg import transactional_session


async def _portugal_task(session, start_date: date):
    # Keep this small fixture local: importing another test module also brings
    # its module-level date anchor into the Portugal calendar cases.
    user = User(
        email=f"pt-calendar-{uuid.uuid4().hex}@example.test",
        hashed_password="x",
        full_name="Portugal calendar fixture",
        role="editor",
        is_active=True,
    )
    session.add(user)
    await session.flush()
    project = Project(name="Portugal calendar QA", owner_id=user.id, region="PT", country_code="PT")
    session.add(project)
    await session.flush()
    service = ScheduleService(session)
    schedule = await service.create_schedule(
        ScheduleCreate(project_id=project.id, name="Portugal calendar", start_date=start_date.isoformat())
    )
    boq = BOQ(project_id=project.id, name="Portugal calendar bill")
    session.add(boq)
    await session.flush()
    session.add(
        Position(
            boq_id=boq.id,
            ordinal="1",
            description="Two working days on the fixture calendar",
            unit="m2",
            quantity="1",
            unit_rate="10",
            total="10",
            sort_order=1,
            # The estimator adds mobilization before converting calendar days
            # back to working days. Twelve hours yield two working days.
            metadata_={"labor_hours": 12, "workers_per_unit": 1},
        )
    )
    await session.flush()
    return service, schedule.id, boq.id, project.id


async def _activities(service, schedule_id):
    service.session.expire_all()
    rows, _ = await service.list_activities_for_schedule(schedule_id, limit=100_000)
    return rows


@pytest.mark.asyncio
async def test_portugal_day_moves_the_actual_task_finish_and_first_cpm_keeps_dates():
    async with transactional_session() as session:
        service, schedule_id, boq_id, _ = await _portugal_task(session, date(2026, 6, 9))
        await service.generate_from_boq(schedule_id, boq_id, 10, start_date=date(2026, 6, 9), workers_per_position=1)
        schedule = await service.get_schedule(schedule_id)
        calendar = schedule.metadata_["calendar"]
        assert "2026-06-10" in calendar["exceptions"]
        coverage = {entry["year"]: entry for entry in calendar["holiday_coverage"]}
        assert coverage[2026]["applied"] is True
        assert coverage[2026]["jurisdiction"]["source"] == "declared"
        activities = await _activities(service, schedule_id)
        task = next(activity for activity in activities if activity.activity_type == "task")
        assert (task.duration_days, task.start_date, task.end_date) == (2, "2026-06-09", "2026-06-11")
        before = {activity.id: (activity.start_date, activity.end_date) for activity in activities}
        await service.reschedule(schedule_id)
        after = {
            activity.id: (activity.start_date, activity.end_date)
            for activity in await _activities(service, schedule_id)
        }
        assert after == before


@pytest.mark.asyncio
async def test_year_boundary_records_missing_2027_without_copying_the_2026_roster():
    async with transactional_session() as session:
        service, schedule_id, boq_id, _ = await _portugal_task(session, date(2026, 12, 31))
        await service.generate_from_boq(schedule_id, boq_id, 10, start_date=date(2026, 12, 31), workers_per_position=1)
        schedule = await service.get_schedule(schedule_id)
        calendar = schedule.metadata_["calendar"]
        coverage = {entry["year"]: entry for entry in calendar["holiday_coverage"]}
        assert coverage[2026]["applied"] is True
        assert coverage[2027]["applied"] is False
        assert coverage[2027]["jurisdiction"]["source"] == "fallback"
        assert "2026-01-01" in calendar["exceptions"]
        assert not any(day.startswith("2027-") for day in calendar["exceptions"])
        # The unshipped year uses the explicitly reported no-holiday fallback;
        # this date is not a claim that January 1 is a Portuguese working day.
        task = next(
            activity for activity in await _activities(service, schedule_id) if activity.activity_type == "task"
        )
        assert (task.start_date, task.end_date) == ("2026-12-31", "2027-01-01")


@pytest.mark.asyncio
@pytest.mark.parametrize("manual", [False, True])
async def test_an_explicit_site_calendar_still_overrides_the_seeded_holiday(manual):
    async with transactional_session() as session:
        service, schedule_id, boq_id, project_id = await _portugal_task(session, date(2026, 6, 9))
        if manual:
            await service.update_schedule(
                schedule_id,
                ScheduleUpdate(metadata={"calendar": {"work_days": [0, 1, 2, 3, 4], "exceptions": []}}),
            )
        else:
            session.add(
                Calendar(
                    project_id=project_id, name="Own site week", work_days=[0, 1, 2, 3, 4], holidays=[], is_default=True
                )
            )
            await session.flush()
        await service.generate_from_boq(schedule_id, boq_id, 10, start_date=date(2026, 6, 9), workers_per_position=1)
        task = next(
            activity for activity in await _activities(service, schedule_id) if activity.activity_type == "task"
        )
        assert (task.duration_days, task.start_date, task.end_date) == (2, "2026-06-09", "2026-06-10")
        schedule = await service.get_schedule(schedule_id)
        calendar = (schedule.metadata_ or {}).get("calendar") or {}
        assert "regional_holiday_country" not in calendar
        assert "holiday_coverage" not in calendar
