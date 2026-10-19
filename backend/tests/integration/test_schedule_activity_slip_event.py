"""A finish date that moves past its baseline announces the slip, once.

``schedule.activity.slipped`` feeds the subcontractor rating, so it has to fire
when an assigned activity's finish crosses the active baseline and not for an
activity with no baseline, no assignee, or one already past it.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.schedule import service as schedule_service
from app.modules.schedule.models import Activity, Schedule, ScheduleBaseline
from app.modules.schedule.schemas import ActivityUpdate
from app.modules.schedule.service import ScheduleService
from tests._pg import transactional_session

SLIPPED = "schedule.activity.slipped"


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with transactional_session(disable_fks=True) as s:
        yield s


@pytest.fixture
def published(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    seen: list[tuple[str, dict[str, Any]]] = []

    def _record(_session: Any, name: str, data: dict[str, Any] | None = None, **_kw: Any) -> None:
        seen.append((name, dict(data or {})))

    monkeypatch.setattr(schedule_service, "publish_after_commit", _record)
    return seen


async def _setup(
    session: AsyncSession, *, assignee: uuid.UUID | None, baselined: bool = True
) -> tuple[Schedule, Activity]:
    schedule = Schedule(project_id=uuid.uuid4(), name="Slip events")
    session.add(schedule)
    await session.flush()
    activity = Activity(
        schedule_id=schedule.id,
        name="Slab pour",
        start_date="2026-07-01",
        end_date="2026-07-10",
        duration_days=7,
        progress_pct="0",
        status="not_started",
        assignee_id=assignee,
    )
    session.add(activity)
    await session.flush()
    if baselined:
        session.add(
            ScheduleBaseline(
                schedule_id=schedule.id,
                project_id=schedule.project_id,
                name="Baseline 1",
                baseline_date="2026-06-30",
                snapshot_data={"activities": [{"id": str(activity.id), "end_date": "2026-07-10"}]},
                is_active=True,
            )
        )
        await session.flush()
    return schedule, activity


async def _move(session: AsyncSession, activity: Activity, end: str) -> None:
    await ScheduleService(session).update_activity(activity.id, ActivityUpdate(end_date=end))


@pytest.mark.asyncio
async def test_crossing_the_baseline_announces_the_slip(
    session: AsyncSession, published: list[tuple[str, dict[str, Any]]]
) -> None:
    contact = uuid.uuid4()
    schedule, activity = await _setup(session, assignee=contact)

    await _move(session, activity, "2026-07-14")

    slips = [data for name, data in published if name == SLIPPED]
    assert len(slips) == 1
    assert slips[0]["assignee_id"] == str(contact)
    assert slips[0]["project_id"] == str(schedule.project_id)
    assert slips[0]["slip_days"] == 4


@pytest.mark.asyncio
async def test_slipping_further_past_the_baseline_is_not_a_second_slip(
    session: AsyncSession, published: list[tuple[str, dict[str, Any]]]
) -> None:
    _schedule, activity = await _setup(session, assignee=uuid.uuid4())

    await _move(session, activity, "2026-07-14")
    await _move(session, activity, "2026-07-20")

    assert [name for name, _ in published if name == SLIPPED] == [SLIPPED]


@pytest.mark.asyncio
async def test_no_baseline_no_assignee_or_an_earlier_finish_is_not_a_slip(
    session: AsyncSession, published: list[tuple[str, dict[str, Any]]]
) -> None:
    _s, unbaselined = await _setup(session, assignee=uuid.uuid4(), baselined=False)
    await _move(session, unbaselined, "2026-07-30")
    _s, unassigned = await _setup(session, assignee=None)
    await _move(session, unassigned, "2026-07-30")
    _s, early = await _setup(session, assignee=uuid.uuid4())
    await _move(session, early, "2026-07-08")

    assert [name for name, _ in published if name == SLIPPED] == []
