"""Integration: generating a schedule from a BOQ stays inside the project window.

The generate dialog now sends the project's duration as ``total_project_days``.
That only helps if the generator honours it: before the fix each activity was
capped at the window on its own, sequential children inside a section were
summed with no cap, and a section of a few long positions ran for years past
the project's end. The window is calendar days, end inclusive.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from app.modules.schedule.schemas import ScheduleCreate
from app.modules.schedule.service import ScheduleService
from tests._pg import transactional_session

START = "2026-05-04"  # a Monday


async def _seed_boq(session, project_id: uuid.UUID) -> uuid.UUID:  # noqa: ANN001
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

    # Two sections, each with large quantities, so the unit production-rate
    # fallback alone yields durations far longer than the window.
    for s_idx in (1, 2):
        section_id = await _pos(None, f"0{s_idx}", f"Section {s_idx}", "", "0", "0")
        for c_idx in (1, 2, 3):
            await _pos(
                section_id,
                f"0{s_idx}.00{c_idx}",
                f"Position {s_idx}.{c_idx}",
                "m3",
                "50000",
                "100000",
            )
    return boq_id


@pytest.mark.asyncio
@pytest.mark.parametrize("window_days", [120, 365])
async def test_generated_activities_end_inside_the_project_window(window_days: int) -> None:
    async with transactional_session(disable_fks=True) as session:
        service = ScheduleService(session)
        project_id = uuid.uuid4()
        schedule = await service.create_schedule(
            ScheduleCreate(project_id=project_id, name="Window QA", start_date=START)
        )
        schedule_id = schedule.id
        boq_id = await _seed_boq(session, project_id)

        await service.generate_from_boq(schedule_id, boq_id, window_days)
        session.expire_all()

        activities, _ = await service.list_activities_for_schedule(schedule_id, limit=1000)
        last_day = date.fromisoformat(START) + timedelta(days=window_days - 1)
        late = [(a.name, a.end_date) for a in activities if date.fromisoformat(a.end_date) > last_day]
        assert not late, late

        # A reschedule re-derives dates from duration_days through CPM; it must
        # land inside the same window rather than stretch every bar.
        rescheduled = await service.reschedule(schedule_id)
        late = [(a.name, a.end_date) for a in rescheduled if date.fromisoformat(a.end_date) > last_day]
        assert not late, late
