# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""A seeded programme has to read off the calendar, not off the row number.

Percent complete was derived from an activity's position in the template list,
which puts every value strictly between 0 and 100. Two things follow, and the
second is the one that leaves the schedule screen:

* no phase is ever finished and none is ever still to come, so a programme
  whose first phase ended last year shows it at ten percent;
* ``status`` is derived from progress, and progress is never zero, so every
  activity in every templated project is permanently ``in_progress``. Any
  screen, rollup or dashboard counting activities by status reads a programme
  that never starts anything and never finishes anything.

The templates ship absolute dates, so asserting against one of them would only
hold until the calendar moved past it. The fixture here is a template whose
phases straddle the day the test runs: two finished, two under way, two not
started, by construction rather than by luck.

Both seeding branches are covered. They differ in where an activity comes from
- hand-authored phases in the template against phases derived from the BOQ
sections - and not in how far along it is, which is what the shared derivation
now guarantees.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.demo_projects import DEMO_TEMPLATES, install_demo_project
from app.modules.schedule.models import Activity, Schedule

pytestmark = pytest.mark.asyncio

# The template the fixture is built from. Any template without its own explicit
# activities will do; this one is picked because it is the smallest install.
_BASE_DEMO = "school-paris"
_STRADDLE_DEMO = "test-straddle-programme"


def _straddling_phases(now: datetime) -> list[tuple[str, str, str]]:
    """Phases either side of ``now``, so 0 and 100 are both reachable answers."""

    def iso(days: int) -> str:
        return (now + timedelta(days=days)).strftime("%Y-%m-%d")

    return [
        ("Site preparation", iso(-540), iso(-400)),
        ("Substructure", iso(-400), iso(-210)),
        ("Superstructure", iso(-210), iso(60)),
        ("Envelope", iso(-40), iso(160)),
        ("Fit-out", iso(70), iso(260)),
        ("Commissioning", iso(220), iso(330)),
    ]


async def _activities(session, project_id) -> list[Activity]:
    schedule_ids = (await session.execute(select(Schedule.id).where(Schedule.project_id == project_id))).scalars().all()
    assert schedule_ids, "the demo install seeded no schedule at all"
    return list(
        (
            await session.execute(
                select(Activity).where(Activity.schedule_id.in_(schedule_ids)).order_by(Activity.wbs_code)
            )
        )
        .scalars()
        .all()
    )


async def _install_straddling(session, monkeypatch) -> list[Activity]:
    """Install a project whose template carries explicit, straddling phases."""
    template = dataclasses.replace(
        DEMO_TEMPLATES[_BASE_DEMO],
        demo_id=_STRADDLE_DEMO,
        project_name="Straddling programme fixture",
        schedule_activities=_straddling_phases(datetime.now()),
    )
    monkeypatch.setitem(DEMO_TEMPLATES, _STRADDLE_DEMO, template)

    result = await install_demo_project(session, _STRADDLE_DEMO)
    await session.flush()
    return await _activities(session, result["project_id"])


def _expected(activity: Activity, now: datetime) -> tuple[int | None, str]:
    """What the activity's own stored dates say about it.

    Only the two ends are pinned. The value in flight depends on how far into
    the phase today is, which is not something to restate here - what matters is
    that it is neither of the ends.
    """
    start = datetime.strptime(activity.start_date[:10], "%Y-%m-%d")
    end = datetime.strptime(activity.end_date[:10], "%Y-%m-%d")
    if end <= now:
        return 100, "completed"
    if start >= now:
        return 0, "planned"
    return None, "in_progress"


async def test_a_seeded_programme_has_finished_and_unstarted_phases(pg_session, monkeypatch) -> None:
    """The two ends of the scale have to be reachable, or nothing is ever done."""
    activities = await _install_straddling(pg_session, monkeypatch)
    assert len(activities) == 6, f"seeded {len(activities)} activities from a six-phase template"

    progress = sorted(int(a.progress_pct) for a in activities)
    assert 100 in progress, f"no phase finished, on a programme whose first phase ended 400 days ago: {progress}"
    assert 0 in progress, f"no phase still to come, on a programme whose last phase starts in 220 days: {progress}"


async def test_the_seeded_statuses_are_not_all_in_progress(pg_session, monkeypatch) -> None:
    """Status is what the dashboards count, so it has to span the lifecycle."""
    activities = await _install_straddling(pg_session, monkeypatch)

    statuses = {a.status for a in activities}
    assert statuses != {"in_progress"}, "every activity is in progress, so nothing is planned and nothing is done"
    assert statuses == {"planned", "in_progress", "completed"}, f"the programme only ever reads {sorted(statuses)}"


async def test_every_seeded_activity_agrees_with_its_own_dates(pg_session, monkeypatch) -> None:
    """The discriminating check: progress re-derived from each row's own dates.

    A count of distinct values can be satisfied by any spread. This cannot: a
    phase that ended before today has to read 100 and one that starts after
    today has to read 0, whatever order the rows were written in.
    """
    now = datetime.now()
    activities = await _install_straddling(pg_session, monkeypatch)

    for activity in activities:
        want_progress, want_status = _expected(activity, now)
        got = int(activity.progress_pct)
        assert activity.status == want_status, (
            f"{activity.name} ({activity.start_date} to {activity.end_date}) reads {activity.status!r}, "
            f"expected {want_status!r}"
        )
        if want_progress is None:
            assert 0 < got < 100, f"{activity.name} is under way but reads {got}%"
        else:
            assert got == want_progress, f"{activity.name} reads {got}%, expected {want_progress}%"


async def test_the_section_derived_branch_agrees_with_its_dates_too(pg_session) -> None:
    """The sibling branch, which builds its phases out of the BOQ sections.

    It already computed progress from the date and is asserted here so a later
    edit cannot quietly take one of the two branches back to row arithmetic. The
    seeded window is fixed in the installer, so only the agreement between a
    row's dates and its own progress is asserted, never which values turn up.
    """
    now = datetime.now()
    result = await install_demo_project(pg_session, _BASE_DEMO)
    await pg_session.flush()

    activities = await _activities(pg_session, result["project_id"])
    assert activities, "the section-derived branch seeded no activities"

    for activity in activities:
        want_progress, want_status = _expected(activity, now)
        got = int(activity.progress_pct)
        assert activity.status == want_status, (
            f"{activity.name} ({activity.start_date} to {activity.end_date}) reads {activity.status!r}, "
            f"expected {want_status!r}"
        )
        if want_progress is None:
            assert 0 < got < 100, f"{activity.name} is under way but reads {got}%"
        else:
            assert got == want_progress, f"{activity.name} reads {got}%, expected {want_progress}%"
