"""Integration: generating a schedule from a BOQ stays inside the project window.

The generate dialog now sends the project's duration as ``total_project_days``.
That only helps if the generator honours it: before the fix each activity was
capped at the window on its own, sequential children inside a section were
summed with no cap, and a section of a few long positions ran for years past
the project's end. The window is calendar days, end inclusive.

Durations are shortened to fit, but never below half of their estimate: a bill
that would need more than that is laid out at half and says it runs past the
window, rather than promising crews a pace nobody keeps.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from app.modules.schedule.schemas import ScheduleCreate
from app.modules.schedule.service import ScheduleService
from tests._pg import transactional_session

START = "2026-05-04"  # a Monday


async def _seed_boq(session, project_id: uuid.UUID, quantity: str) -> uuid.UUID:  # noqa: ANN001
    from app.modules.boq.models import BOQ, Position

    boq = BOQ(project_id=project_id, name="Window BOQ")
    session.add(boq)
    await session.flush()
    boq_id = boq.id

    async def _pos(parent_id, ordinal: str, description: str, unit: str, qty: str, total: str):  # noqa: ANN001, ANN202
        pos = Position(
            boq_id=boq_id,
            parent_id=parent_id,
            ordinal=ordinal,
            description=description,
            unit=unit,
            quantity=qty,
            unit_rate="1",
            total=total,
        )
        session.add(pos)
        await session.flush()
        return pos.id

    # Two sections of three positions in m3, sized by the unit fallback
    # alone: 4 h a unit for a gang of four, so ``quantity / 8`` working days.
    for s_idx in (1, 2):
        section_id = await _pos(None, f"0{s_idx}", f"Section {s_idx}", "", "0", "0")
        for c_idx in (1, 2, 3):
            await _pos(
                section_id,
                f"0{s_idx}.00{c_idx}",
                f"Position {s_idx}.{c_idx}",
                "m3",
                quantity,
                "100000",
            )
    return boq_id


async def _generate(session, window_days: int, quantity: str) -> tuple[ScheduleService, uuid.UUID]:  # noqa: ANN001
    service = ScheduleService(session)
    project_id = uuid.uuid4()
    schedule = await service.create_schedule(ScheduleCreate(project_id=project_id, name="Window QA", start_date=START))
    schedule_id = schedule.id
    boq_id = await _seed_boq(session, project_id, quantity)
    # One worker a position, pinned: these tests measure how a plan is
    # shortened to the window, which assumed workers would absorb.
    await service.generate_from_boq(schedule_id, boq_id, window_days, workers_per_position=1)
    session.expire_all()
    return service, schedule_id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("window_days", "quantity"),
    # About 1.4 times the window at full estimates: it fits once shortened.
    [(120, "640"), (365, "1920")],
)
async def test_generated_activities_end_inside_the_project_window(window_days: int, quantity: str) -> None:
    async with transactional_session(disable_fks=True) as session:
        service, schedule_id = await _generate(session, window_days, quantity)
        activities, _ = await service.list_activities_for_schedule(schedule_id, limit=1000)
        last_day = date.fromisoformat(START) + timedelta(days=window_days - 1)
        late = [(a.name, a.end_date) for a in activities if date.fromisoformat(a.end_date) > last_day]
        assert not late, late
        generation = (await service.get_schedule(schedule_id)).metadata_["boq_generation"]
        assert [w["code"] for w in generation["warnings"]] == ["durations_shortened"]

        # A reschedule re-derives dates from duration_days through CPM; it must
        # land inside the same window rather than stretch every bar.
        rescheduled = await service.reschedule(schedule_id)
        late = [(a.name, a.end_date) for a in rescheduled if date.fromisoformat(a.end_date) > last_day]
        assert not late, late


@pytest.mark.asyncio
@pytest.mark.parametrize("window_days", [120, 365])
async def test_a_bill_too_big_for_the_window_stops_at_half_and_says_so(window_days: int) -> None:
    async with transactional_session(disable_fks=True) as session:
        service, schedule_id = await _generate(session, window_days, "50000")
        activities, _ = await service.list_activities_for_schedule(schedule_id, limit=1000)
        tasks = [a for a in activities if a.activity_type == "task"]
        # 50000 / 8 working days each at full estimate, never below half.
        assert {a.duration_days for a in tasks} == {3125}
        generation = (await service.get_schedule(schedule_id)).metadata_["boq_generation"]
        [warning] = generation["warnings"]
        assert warning["code"] == "plan_exceeds_window"
        assert warning["percent"] == 50
        assert warning["planned_end"] == max(a.end_date for a in activities)

        before = {a.id: (a.start_date, a.end_date) for a in activities}
        rescheduled = await service.reschedule(schedule_id)
        assert {a.id: (a.start_date, a.end_date) for a in rescheduled} == before
