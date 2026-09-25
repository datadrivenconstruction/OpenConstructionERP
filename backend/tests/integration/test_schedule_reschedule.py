"""Integration: edit a dependency and reschedule the Gantt (issue #348).

Exercises the new PATCH ``/relationships/{id}`` and POST
``/schedules/{id}/reschedule/`` handlers against a real (async) throwaway
PostgreSQL. The reschedule bulk-writes real date columns and the PATCH
mirror-rebuild calls ``expire_all()`` - neither is reproducible on a fake
session. The owner check is stubbed to a no-op so the test stays on the
handler + CPM engine path, not the JWT/RBAC stack.

The dates are deterministic because 2024-01-01 is a Monday, so the default
Monday-Friday work calendar projects the CPM offsets onto known weekdays.
"""

from __future__ import annotations

import uuid

import pytest

from app.modules.schedule import router as schedule_router
from app.modules.schedule.schemas import (
    ActivityCreate,
    RelationshipCreate,
    RelationshipUpdate,
    ScheduleCreate,
)
from app.modules.schedule.service import ScheduleService
from tests._pg import transactional_session


def _by_id(activities: list, activity_id: uuid.UUID):
    return next(a for a in activities if a.id == activity_id)


@pytest.mark.asyncio
async def test_patch_relationship_and_reschedule_moves_successor() -> None:
    async with transactional_session(disable_fks=True) as session:
        service = ScheduleService(session)

        schedule = await service.create_schedule(
            ScheduleCreate(project_id=uuid.uuid4(), name="Reschedule QA", start_date="2024-01-01")
        )
        # Snapshot the id before the first create_relationship expires the ORM
        # object (its mirror rebuild calls session.expire_all(), after which a
        # sync ``schedule.id`` access would trigger an async refresh). The real
        # route takes the id as a path param, so this is a test-only concern.
        schedule_id = schedule.id
        pred = await service.create_activity(
            ActivityCreate(
                schedule_id=schedule_id,
                name="Predecessor",
                start_date="2024-01-01",
                end_date="2024-01-05",  # 5 working days (Mon-Fri)
            )
        )
        succ = await service.create_activity(
            ActivityCreate(
                schedule_id=schedule_id,
                name="Successor",
                start_date="2024-01-01",  # deliberately overlapping the predecessor
                end_date="2024-01-03",  # 3 working days
            )
        )
        pred_id, succ_id = pred.id, succ.id

        # Keep the test focused on the handler + engine, not the JWT/RBAC stack.
        async def _noop_verify(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            return None

        original = schedule_router._verify_schedule_owner
        schedule_router._verify_schedule_owner = _noop_verify  # type: ignore[assignment]
        try:
            created = await schedule_router.create_relationship(
                schedule_id=schedule_id,
                data=RelationshipCreate(
                    predecessor_id=pred_id,
                    successor_id=succ_id,
                    relationship_type="FS",
                    lag_days=0,
                ),
                session=session,
                _user_id=uuid.uuid4(),
                payload={"role": "admin"},
                service=service,
            )
            rel_id = created.id

            # Reschedule moves the successor to the predecessor's finish (over the
            # weekend) and marks the single chain critical; the root keeps its
            # manually set start.
            activities = await schedule_router.reschedule_schedule(
                schedule_id=schedule_id,
                _user_id=uuid.uuid4(),
                payload={"role": "admin"},
                session=session,
                service=service,
            )
            a_pred = _by_id(activities, pred_id)
            a_succ = _by_id(activities, succ_id)
            assert a_pred.start_date == "2024-01-01"  # root: unchanged
            assert a_pred.is_critical is True
            assert a_succ.start_date == "2024-01-08"  # FS + 0 lag lands on Monday
            assert a_succ.end_date == "2024-01-10"  # 3 working days, end inclusive
            assert a_succ.is_critical is True

            # PATCH updates the lag; the type stays FS.
            patched = await schedule_router.update_relationship(
                relationship_id=rel_id,
                data=RelationshipUpdate(lag_days=2),
                session=session,
                _user_id=uuid.uuid4(),
                payload={"role": "admin"},
                service=service,
            )
            assert patched.relationship_type == "FS"
            assert patched.lag_days == 2

            # Reschedule again: the 2-day lag pushes the successor two calendar
            # days later.
            activities = await schedule_router.reschedule_schedule(
                schedule_id=schedule_id,
                _user_id=uuid.uuid4(),
                payload={"role": "admin"},
                session=session,
                service=service,
            )
            a_succ = _by_id(activities, succ_id)
            assert a_succ.start_date == "2024-01-10"
            assert a_succ.end_date == "2024-01-12"  # Wed, Thu, Fri

            # PATCH also updates the type; the lag is untouched (still 2).
            retyped = await schedule_router.update_relationship(
                relationship_id=rel_id,
                data=RelationshipUpdate(relationship_type="SS"),
                session=session,
                _user_id=uuid.uuid4(),
                payload={"role": "admin"},
                service=service,
            )
            assert retyped.relationship_type == "SS"
            assert retyped.lag_days == 2
        finally:
            schedule_router._verify_schedule_owner = original  # type: ignore[assignment]


@pytest.mark.asyncio
async def test_reschedule_honours_per_activity_work_calendar() -> None:
    """A predecessor on a six-day work week finishes sooner, moving its successor.

    The predecessor spans several weeks. On the default Monday-Friday calendar
    every Saturday is idle; assigning it a Monday-Saturday calendar lets it work
    the Saturdays, so the same duration finishes at an earlier calendar date and
    its FS successor starts earlier. Proves reschedule threads
    ``Activity.calendar_id`` through the CPM engine.
    """
    from app.modules.schedule_advanced.models import Calendar

    async with transactional_session(disable_fks=True) as session:
        service = ScheduleService(session)
        project_id = uuid.uuid4()
        schedule = await service.create_schedule(
            ScheduleCreate(project_id=project_id, name="Calendar QA", start_date="2024-01-01")
        )
        schedule_id = schedule.id
        pred = await service.create_activity(
            ActivityCreate(
                schedule_id=schedule_id,
                name="Six-day trade",
                start_date="2024-01-01",
                end_date="2024-01-12",  # ~2 weeks, several idle Saturdays on Mon-Fri
            )
        )
        succ = await service.create_activity(
            ActivityCreate(
                schedule_id=schedule_id,
                name="Follow-on",
                start_date="2024-01-01",
                end_date="2024-01-03",
            )
        )
        pred_id, succ_id = pred.id, succ.id

        # A named Monday-Saturday work calendar for the project. disable_fks lets
        # the project_id be synthetic; Activity.calendar_id has no DB-level FK.
        six_day = Calendar(
            project_id=project_id,
            name="Six-day week",
            work_days=[0, 1, 2, 3, 4, 5],
            holidays=[],
            is_default=False,
        )
        session.add(six_day)
        await session.flush()
        six_day_id = six_day.id

        async def _noop_verify(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            return None

        original = schedule_router._verify_schedule_owner
        schedule_router._verify_schedule_owner = _noop_verify  # type: ignore[assignment]
        try:
            await schedule_router.create_relationship(
                schedule_id=schedule_id,
                data=RelationshipCreate(
                    predecessor_id=pred_id,
                    successor_id=succ_id,
                    relationship_type="FS",
                    lag_days=0,
                ),
                session=session,
                _user_id=uuid.uuid4(),
                payload={"role": "admin"},
                service=service,
            )

            # Baseline reschedule on the default Monday-Friday calendar.
            activities = await schedule_router.reschedule_schedule(
                schedule_id=schedule_id,
                _user_id=uuid.uuid4(),
                payload={"role": "admin"},
                session=session,
                service=service,
            )
            succ_default_start = _by_id(activities, succ_id).start_date

            # Assign the six-day calendar to the predecessor and reschedule again.
            # expire_all so the reschedule reload sees the new calendar_id (a Core
            # UPDATE does not refresh the identity-mapped instance); in the real
            # API the assign and the reschedule are separate requests/sessions.
            await service.activity_repo.update_fields(pred_id, calendar_id=six_day_id)
            session.expire_all()
            activities = await schedule_router.reschedule_schedule(
                schedule_id=schedule_id,
                _user_id=uuid.uuid4(),
                payload={"role": "admin"},
                session=session,
                service=service,
            )
            succ_sixday_start = _by_id(activities, succ_id).start_date

            # Working the Saturdays pulls the successor to an earlier start.
            assert succ_sixday_start < succ_default_start
        finally:
            schedule_router._verify_schedule_owner = original  # type: ignore[assignment]


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_reschedule_ignores_a_foreign_project_calendar() -> None:
    """An activity carrying a calendar from another project falls back to default.

    A ``calendar_id`` can be copied in from another project (for example through
    a schedule import), pointing at a calendar the schedule's own project does
    not own. Reschedule must not measure the activity on that other tenant's
    work week; the project-scoped lookup finds nothing and the activity
    reschedules on the schedule-wide default, exactly as if it carried no
    calendar. Proves the read path is project-scoped like the write path.
    """
    from app.modules.schedule_advanced.models import Calendar

    async with transactional_session(disable_fks=True) as session:
        service = ScheduleService(session)
        project_id = uuid.uuid4()
        other_project_id = uuid.uuid4()
        schedule = await service.create_schedule(
            ScheduleCreate(project_id=project_id, name="Tenant QA", start_date="2024-01-01")
        )
        schedule_id = schedule.id
        pred = await service.create_activity(
            ActivityCreate(schedule_id=schedule_id, name="Trade", start_date="2024-01-01", end_date="2024-01-12")
        )
        succ = await service.create_activity(
            ActivityCreate(schedule_id=schedule_id, name="Follow-on", start_date="2024-01-01", end_date="2024-01-03")
        )
        pred_id, succ_id = pred.id, succ.id

        # A six-day calendar owned by a DIFFERENT project.
        foreign = Calendar(
            project_id=other_project_id,
            name="Foreign six-day",
            work_days=[0, 1, 2, 3, 4, 5],
            holidays=[],
            is_default=False,
        )
        session.add(foreign)
        await session.flush()
        foreign_id = foreign.id

        async def _noop_verify(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            return None

        original = schedule_router._verify_schedule_owner
        schedule_router._verify_schedule_owner = _noop_verify  # type: ignore[assignment]
        try:
            await schedule_router.create_relationship(
                schedule_id=schedule_id,
                data=RelationshipCreate(
                    predecessor_id=pred_id, successor_id=succ_id, relationship_type="FS", lag_days=0
                ),
                session=session,
                _user_id=uuid.uuid4(),
                payload={"role": "admin"},
                service=service,
            )
            activities = await schedule_router.reschedule_schedule(
                schedule_id=schedule_id,
                _user_id=uuid.uuid4(),
                payload={"role": "admin"},
                session=session,
                service=service,
            )
            succ_default_start = _by_id(activities, succ_id).start_date

            # Assign the FOREIGN calendar and reschedule again.
            await service.activity_repo.update_fields(pred_id, calendar_id=foreign_id)
            session.expire_all()
            activities = await schedule_router.reschedule_schedule(
                schedule_id=schedule_id,
                _user_id=uuid.uuid4(),
                payload={"role": "admin"},
                session=session,
                service=service,
            )
            succ_foreign_start = _by_id(activities, succ_id).start_date

            # The foreign six-day calendar is ignored: the successor is unmoved.
            assert succ_foreign_start == succ_default_start
        finally:
            schedule_router._verify_schedule_owner = original  # type: ignore[assignment]


@pytest.mark.asyncio
async def test_reschedule_inherits_project_default_calendar() -> None:
    """Activities with no calendar of their own follow the project default one.

    Neither activity carries a ``calendar_id`` here. On the built-in
    Monday-Friday fallback the predecessor idles every Saturday; once the
    project has a default Monday-Saturday calendar (``is_default``), the
    schedule-wide resolution picks it up so the predecessor works the Saturdays
    and its FS successor starts earlier. Proves reschedule consults the
    project's default named calendar, not just a Monday-Friday constant.
    """
    from app.modules.schedule_advanced.schemas import CalendarCreate
    from app.modules.schedule_advanced.service import ScheduleAdvancedService

    async with transactional_session(disable_fks=True) as session:
        service = ScheduleService(session)
        project_id = uuid.uuid4()
        schedule = await service.create_schedule(
            ScheduleCreate(project_id=project_id, name="Default calendar QA", start_date="2024-01-01")
        )
        schedule_id = schedule.id
        pred = await service.create_activity(
            ActivityCreate(schedule_id=schedule_id, name="Trade", start_date="2024-01-01", end_date="2024-01-12")
        )
        succ = await service.create_activity(
            ActivityCreate(schedule_id=schedule_id, name="Follow-on", start_date="2024-01-01", end_date="2024-01-03")
        )
        pred_id, succ_id = pred.id, succ.id

        async def _noop_verify(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            return None

        original = schedule_router._verify_schedule_owner
        schedule_router._verify_schedule_owner = _noop_verify  # type: ignore[assignment]
        try:
            await schedule_router.create_relationship(
                schedule_id=schedule_id,
                data=RelationshipCreate(
                    predecessor_id=pred_id, successor_id=succ_id, relationship_type="FS", lag_days=0
                ),
                session=session,
                _user_id=uuid.uuid4(),
                payload={"role": "admin"},
                service=service,
            )

            activities = await schedule_router.reschedule_schedule(
                schedule_id=schedule_id,
                _user_id=uuid.uuid4(),
                payload={"role": "admin"},
                session=session,
                service=service,
            )
            succ_default_start = _by_id(activities, succ_id).start_date

            # Give the project a default six-day calendar; no activity is assigned
            # to it, so it must be picked up as the schedule-wide default.
            adv = ScheduleAdvancedService(session)
            await adv.create_calendar(
                CalendarCreate(
                    project_id=project_id,
                    name="Project six-day",
                    work_days=[0, 1, 2, 3, 4, 5],
                    holidays=[],
                    is_default=True,
                )
            )
            session.expire_all()
            activities = await schedule_router.reschedule_schedule(
                schedule_id=schedule_id,
                _user_id=uuid.uuid4(),
                payload={"role": "admin"},
                session=session,
                service=service,
            )
            succ_sixday_start = _by_id(activities, succ_id).start_date

            assert succ_sixday_start < succ_default_start
        finally:
            schedule_router._verify_schedule_owner = original  # type: ignore[assignment]


@pytest.mark.asyncio
async def test_setting_a_new_default_calendar_clears_the_previous_one() -> None:
    """At most one calendar per project stays ``is_default`` so resolution is stable."""
    from app.modules.schedule_advanced.schemas import CalendarCreate, CalendarUpdate
    from app.modules.schedule_advanced.service import ScheduleAdvancedService

    async with transactional_session(disable_fks=True) as session:
        adv = ScheduleAdvancedService(session)
        project_id = uuid.uuid4()
        first = await adv.create_calendar(CalendarCreate(project_id=project_id, name="Five-day", is_default=True))
        # A second default via create must demote the first.
        second = await adv.create_calendar(
            CalendarCreate(project_id=project_id, name="Six-day", work_days=[0, 1, 2, 3, 4, 5], is_default=True)
        )
        session.expire_all()
        cals = await adv.calendar_repo.list_for_project(project_id)
        defaults = [c for c in cals if c.is_default]
        assert len(defaults) == 1
        assert defaults[0].id == second.id

        # Promoting the first back via update must demote the second.
        await adv.update_calendar(first.id, CalendarUpdate(is_default=True))
        session.expire_all()
        cals = await adv.calendar_repo.list_for_project(project_id)
        defaults = [c for c in cals if c.is_default]
        assert len(defaults) == 1
        assert defaults[0].id == first.id


def _working_days_inclusive(start: str, end: str, work_days: set[int], holidays: set[str]) -> int:
    """Count the working days from ``start`` to ``end``, both ends included."""
    from datetime import date, timedelta

    current, last = date.fromisoformat(start), date.fromisoformat(end)
    count = 0
    while current <= last:
        if current.weekday() in work_days and current.isoformat() not in holidays:
            count += 1
        current += timedelta(days=1)
    return count


def _next_working_day(day: str, work_days: set[int], holidays: set[str]) -> str:
    from datetime import date, timedelta

    current = date.fromisoformat(day) + timedelta(days=1)
    while current.weekday() not in work_days or current.isoformat() in holidays:
        current += timedelta(days=1)
    return current.isoformat()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("work_days", "holidays"),
    [
        ([0, 1, 2, 3, 4], []),
        ([0, 1, 2, 3, 4], ["2024-01-10"]),
        ([0, 1, 2, 3, 4, 5], ["2024-01-10"]),
    ],
    ids=["mon-fri", "mon-fri-holiday", "six-day-holiday"],
)
async def test_fs_link_keeps_the_duration_and_starts_the_next_working_day(
    work_days: list[int], holidays: list[str]
) -> None:
    """A finish-to-start link must not stretch either activity by a day.

    The end date is inclusive: an activity of N working days runs from its start
    through its Nth working day. Before the fix the CPM finish offset (the first
    free day after the work) was written as the end date, so every linked
    activity ended one working day late and its successor started on that day.
    The durations are counted on the same calendar the schedule runs on.
    """
    from app.modules.schedule_advanced.schemas import CalendarCreate
    from app.modules.schedule_advanced.service import ScheduleAdvancedService

    async with transactional_session(disable_fks=True) as session:
        service = ScheduleService(session)
        project_id = uuid.uuid4()
        schedule = await service.create_schedule(
            ScheduleCreate(project_id=project_id, name="Inclusive end QA", start_date="2024-01-01")
        )
        schedule_id = schedule.id
        await ScheduleAdvancedService(session).create_calendar(
            CalendarCreate(
                project_id=project_id,
                name="Project week",
                work_days=work_days,
                holidays=holidays,
                is_default=True,
            )
        )
        chain = []
        for name, duration in (("Site prep", 4), ("Foundations", 5), ("Concrete", 3)):
            act = await service.create_activity(
                ActivityCreate(
                    schedule_id=schedule_id,
                    name=name,
                    start_date="2024-01-01",
                    end_date="2024-01-01",
                    duration_days=duration,
                )
            )
            chain.append((act.id, duration))

        async def _noop_verify(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            return None

        original = schedule_router._verify_schedule_owner
        schedule_router._verify_schedule_owner = _noop_verify  # type: ignore[assignment]
        try:
            for (pred_id, _), (succ_id, _) in zip(chain, chain[1:], strict=False):
                await schedule_router.create_relationship(
                    schedule_id=schedule_id,
                    data=RelationshipCreate(
                        predecessor_id=pred_id, successor_id=succ_id, relationship_type="FS", lag_days=0
                    ),
                    session=session,
                    _user_id=uuid.uuid4(),
                    payload={"role": "admin"},
                    service=service,
                )
            session.expire_all()
            activities = await schedule_router.reschedule_schedule(
                schedule_id=schedule_id,
                _user_id=uuid.uuid4(),
                payload={"role": "admin"},
                session=session,
                service=service,
            )
        finally:
            schedule_router._verify_schedule_owner = original  # type: ignore[assignment]

        week, off = set(work_days), set(holidays)
        rows = [_by_id(activities, act_id) for act_id, _ in chain]
        # Site prep is the root and keeps its manual dates; the two linked
        # activities are the ones CPM writes.
        for row, (_, duration) in zip(rows[1:], chain[1:], strict=True):
            assert _working_days_inclusive(row.start_date, row.end_date, week, off) == duration, (
                row.name,
                row.start_date,
                row.end_date,
            )
        assert rows[2].start_date == _next_working_day(rows[1].end_date, week, off)
