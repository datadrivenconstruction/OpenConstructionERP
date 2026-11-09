"""Generating from a BOQ at a chosen depth: sections below it roll up into one activity.

A planner with a bill of hundreds of positions does not want a task per
position on the first plan. The depth keeps the first N levels of sections as
bars and turns each section at that level into one activity that carries the
labour of everything under it; the dates are the full plan's, so the overall
duration does not change.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.modules.schedule.boq_plan import BoqRow, build_plan_tree, group_depth, rollup_groups
from app.modules.schedule.models import Activity
from tests._pg import transactional_session
from tests.integration.test_schedule_generate_from_boq_tree import _activities, _Bill, _setup


def _row(rid: str, parent: str | None, *, section: bool) -> BoqRow:
    return BoqRow(
        id=rid,
        parent_id=parent,
        is_section=section,
        is_placeholder=False,
        data={"ordinal": rid},
        has_work=not section,
    )


def _tree():  # noqa: ANN202
    rows = [
        _row("a", None, section=True),
        _row("a1", "a", section=True),
        _row("a1x", "a1", section=False),
        _row("a1y", "a1", section=False),
        _row("a2", "a", section=False),
        _row("b", None, section=True),
        _row("b1", "b", section=False),
    ]
    return build_plan_tree(rows)


def test_depth_counts_section_levels() -> None:
    assert group_depth(_tree().roots) == 2


def test_rollup_maps_everything_below_the_chosen_level() -> None:
    rolled = rollup_groups(_tree().roots, 1)
    assert rolled == {
        "g:a1": "g:a",
        "t:a1x": "g:a",
        "t:a1y": "g:a",
        "t:a2": "g:a",
        "t:b1": "g:b",
    }
    # Level 2 stands on section a1 only; section b has no level 2.
    assert rollup_groups(_tree().roots, 2) == {"t:a1x": "g:a1", "t:a1y": "g:a1"}
    assert rollup_groups(_tree().roots, 0) == {}


def _labour_hours(activities: list[Activity]) -> float:
    return sum(
        float(r["hours"])
        for a in activities
        if a.activity_type == "task"
        for r in a.resources or []
        if r.get("type") == "labor"
    )


async def _deep_bill(bill: _Bill) -> None:
    for c in range(2):
        cap = await bill.section(None, f"0{c + 1}", f"Chapter {c + 1}")
        for k in range(2):
            cat = await bill.section(cap, f"0{c + 1}.0{k + 1}", f"Category {c + 1}.{k + 1}")
            for p in range(3):
                await bill.position(
                    cat,
                    f"0{c + 1}.0{k + 1}.00{p + 1}",
                    f"Item {c + 1}.{k + 1}.{p + 1}",
                    "m2",
                    "40",
                    "25",
                    meta={"labor_hours": 16, "workers_per_unit": 2},
                )


@pytest.mark.asyncio
async def test_rollup_keeps_the_span_and_sums_the_work() -> None:
    async with transactional_session() as session:
        service, schedule_id, bill, _ = await _setup(session)
        await _deep_bill(bill)
        await service.generate_from_boq(schedule_id, bill.boq_id, 365)
        full = await _activities(service, schedule_id)
        full_end = max(a.end_date for a in full)
        full_by_name = {a.name: a for a in full}

        await service.generate_from_boq(schedule_id, bill.boq_id, 365, replace=True, rollup_depth=1)
        rolled = await _activities(service, schedule_id)

        assert max(a.end_date for a in rolled) == full_end
        assert len(rolled) < len(full)
        chapters = [a for a in rolled if a.metadata_.get("rolled_up")]
        assert [a.name for a in chapters] == ["Chapter 1", "Chapter 2"]
        for chapter in chapters:
            twin = full_by_name[chapter.name]
            assert (chapter.start_date, chapter.end_date) == (twin.start_date, twin.end_date)
            assert chapter.activity_type == "task"
            assert len(chapter.boq_position_ids) == 6
            assert chapter.metadata_["rolled_up_positions"] == 6
            assert chapter.resources[0]["type"] == "labor"
        assert _labour_hours(rolled) == pytest.approx(_labour_hours(full))
        # Money survives the roll-up exactly.
        assert sum((Decimal(str(a.cost_planned)) for a in rolled if a.cost_planned), Decimal(0)) == sum(
            (Decimal(str(a.cost_planned)) for a in full if a.cost_planned and a.activity_type == "task"),
            Decimal(0),
        )
        # Nothing waits on a bar that is gone.
        ids = {a.id for a in rolled}
        for a in rolled:
            for dep in a.dependencies or []:
                assert uuid.UUID(dep["activity_id"]) in ids


@pytest.mark.asyncio
async def test_depth_at_or_past_the_bills_depth_changes_nothing() -> None:
    async with transactional_session() as session:
        service, schedule_id, bill, _ = await _setup(session)
        await _deep_bill(bill)
        preview = await service.preview_generation(schedule_id, bill.boq_id, 365, rollup_depth=5)
        assert preview["max_depth"] == 2
        assert preview["rollup_depth"] == 0
        assert preview["rolled_up_count"] == 0
        one = await service.preview_generation(schedule_id, bill.boq_id, 365, rollup_depth=1)
        assert one["rollup_depth"] == 1
        assert one["rolled_up_count"] == 2
        assert one["activity_count"] < preview["activity_count"]
        assert one["planned_end"] == preview["planned_end"]


@pytest.mark.asyncio
async def test_hours_a_day_come_from_the_project_calendar() -> None:
    from app.modules.schedule_advanced.models import Calendar

    async with transactional_session() as session:
        service, schedule_id, bill, project_id = await _setup(session)
        sec = await bill.section(None, "01", "Walls")
        await bill.position(sec, "01.1", "Wall", "m2", "10", "10", meta={"labor_hours": 80, "workers_per_unit": 1})
        before = await service.preview_generation(schedule_id, bill.boq_id, 365, workers_per_position=1)
        assert before["hours_source"] == "region"
        await service.generate_from_boq(schedule_id, bill.boq_id, 365, workers_per_position=1)
        wall_before = next(a for a in await _activities(service, schedule_id) if a.name == "Wall")

        session.add(
            Calendar(
                project_id=project_id,
                name="Site",
                work_days=[0, 1, 2, 3, 4],
                work_hours_per_day=Decimal("4"),
                holidays=[],
                is_default=True,
            )
        )
        await session.flush()
        after = await service.preview_generation(schedule_id, bill.boq_id, 365, workers_per_position=1)
        assert after["hours_source"] == "calendar"
        assert after["hours_per_day"] == 4.0
        # Half the hours a day: the same labour takes twice the working days.
        await service.generate_from_boq(schedule_id, bill.boq_id, 365, replace=True, workers_per_position=1)
        wall_after = next(a for a in await _activities(service, schedule_id) if a.name == "Wall")
        assert wall_after.duration_days >= 2 * wall_before.duration_days - 1
