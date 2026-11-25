"""Activities generated from a bill follow its quantities.

Worked example: a pour of 100 m3 at 2 labour hours per m3 is 200 crew hours.
Doubling the quantity to 200 m3 doubles the hours, so the activity's stored
working-day duration doubles and every successor moves out behind it. A
duration a person typed is pinned and stays as it was.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.core.validation.engine import ValidationContext
from app.modules.schedule.boq_followup import (
    DURATION_LOCKED_KEY,
    follow_position_quantity,
    position_effort_hours,
    scaled_duration,
)
from app.modules.schedule.events import _quantity_change
from app.modules.schedule.validators import DurationFollowsBillQuantity

START = "2026-05-04"  # a Monday


# ── Pure ──────────────────────────────────────────────────────────────────────


def test_effort_is_linear_in_quantity_at_a_fixed_crew() -> None:
    meta = {"labor_hours": 2}
    at_100 = position_effort_hours(meta, Decimal("100"), "m3", Decimal("50"), crew=4, machine_sets=1)
    at_200 = position_effort_hours(meta, Decimal("200"), "m3", Decimal("50"), crew=4, machine_sets=1)
    assert at_100 > 0
    assert at_200 == pytest.approx(2 * at_100)


def test_scaled_duration_keeps_the_stored_length_proportional() -> None:
    assert scaled_duration(10, 200.0, 400.0) == 20
    assert scaled_duration(10, 200.0, 100.0) == 5
    # Never below one working day.
    assert scaled_duration(3, 200.0, 1.0) == 1


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"quantity": {"old": "100", "new": "200"}}, (True, "100")),
        ({"description": {"old": "a", "new": "b"}}, (False, None)),
        ({"propagated_from": "x"}, (True, None)),
        (None, (True, None)),
    ],
)
def test_only_quantity_events_reach_the_schedule(changes, expected) -> None:  # noqa: ANN001
    assert _quantity_change({"position_id": "p", "changes": changes}) == expected


async def _run_rule(activities: list[dict], quantities: dict) -> list:  # noqa: ANN001
    ctx = ValidationContext(data={"activities": activities, "position_quantities": quantities})
    return await DurationFollowsBillQuantity().validate(ctx)


@pytest.mark.asyncio
async def test_rule_flags_an_activity_sized_for_an_old_quantity() -> None:
    pid = str(uuid.uuid4())
    act = {"id": "a1", "name": "Pour", "boq_position_ids": [pid], "metadata": {"quantity": "100"}}
    [stale] = await _run_rule([act], {pid: "200"})
    assert not stale.passed
    assert stale.details == {"planned_quantity": "100", "bill_quantity": "200"}
    [fresh] = await _run_rule([act], {pid: "100.000"})
    assert fresh.passed


@pytest.mark.asyncio
async def test_rule_leaves_a_pinned_duration_alone() -> None:
    pid = str(uuid.uuid4())
    act = {"id": "a1", "boq_position_ids": [pid], "metadata": {"quantity": "100", DURATION_LOCKED_KEY: True}}
    assert await _run_rule([act], {pid: "200"}) == []
    assert await _run_rule([act], {}) == []


# ── PostgreSQL ────────────────────────────────────────────────────────────────


async def _plan(session):  # noqa: ANN001, ANN202
    from app.modules.boq.models import BOQ, Position
    from app.modules.projects.models import Project
    from app.modules.schedule.schemas import ScheduleCreate
    from app.modules.schedule.service import ScheduleService
    from app.modules.users.models import User

    user = User(email=f"p-{uuid.uuid4().hex[:8]}@follow.io", hashed_password="x", full_name="P", role="editor")
    session.add(user)
    await session.flush()
    project = Project(name="Follow", owner_id=user.id, currency="EUR")
    session.add(project)
    await session.flush()
    service = ScheduleService(session)
    schedule = await service.create_schedule(ScheduleCreate(project_id=project.id, name="Plan", start_date=START))
    boq = BOQ(project_id=project.id, name="Bill")
    session.add(boq)
    await session.flush()
    section = Position(boq_id=boq.id, ordinal="01", description="Frame", unit="", quantity="0", unit_rate="0")
    session.add(section)
    await session.flush()
    ids = {}
    for n, (name, qty) in enumerate((("Pour", "100"), ("Cure", "40")), start=1):
        pos = Position(
            boq_id=boq.id,
            parent_id=section.id,
            ordinal=f"01.00{n}",
            description=name,
            unit="m3",
            quantity=qty,
            unit_rate="50",
            total=str(Decimal(qty) * 50),
            metadata_={"labor_hours": 2},
            sort_order=n,
        )
        session.add(pos)
        await session.flush()
        ids[name] = pos.id
    await service.generate_from_boq(schedule.id, boq.id, start_date=date.fromisoformat(START), workers_per_position=2)
    return service, schedule.id, ids


async def _by_name(session, schedule_id):  # noqa: ANN001, ANN202
    from app.modules.schedule.models import Activity

    session.expire_all()
    rows = (await session.execute(select(Activity).where(Activity.schedule_id == schedule_id))).scalars().all()
    return {a.name: a for a in rows if a.activity_type == "task"}


@pytest.mark.asyncio
async def test_a_doubled_quantity_doubles_the_duration_and_moves_successors() -> None:
    from app.modules.boq.models import Position
    from app.modules.schedule.models import ScheduleRelationship
    from tests._pg import transactional_session

    async with transactional_session() as session:
        service, schedule_id, ids = await _plan(session)
        before = await _by_name(session, schedule_id)
        pour_days = before["Pour"].duration_days
        pour_end = before["Pour"].end_date
        assert pour_days >= 1

        pos = await session.get(Position, ids["Pour"])
        pos.quantity = "200"
        await session.flush()
        changed = await follow_position_quantity(session, ids["Pour"], "100")

        after = await _by_name(session, schedule_id)
        assert changed == [after["Pour"].id]
        assert pour_days < after["Pour"].duration_days <= 2 * pour_days
        assert after["Pour"].metadata_["quantity"] == "200"
        assert after["Pour"].end_date > pour_end
        edges = (
            (
                await session.execute(
                    select(ScheduleRelationship).where(ScheduleRelationship.predecessor_id == after["Pour"].id)
                )
            )
            .scalars()
            .all()
        )
        by_id = {a.id: a for a in after.values()}
        for edge in edges:
            succ = by_id.get(edge.successor_id)
            if succ is not None and edge.relationship_type == "FS":
                assert succ.start_date > after["Pour"].end_date


@pytest.mark.asyncio
async def test_a_typed_duration_is_pinned_against_the_bill() -> None:
    from app.modules.boq.models import Position
    from app.modules.schedule.schemas import ActivityUpdate
    from tests._pg import transactional_session

    async with transactional_session() as session:
        service, schedule_id, ids = await _plan(session)
        pour = (await _by_name(session, schedule_id))["Pour"]
        await service.update_activity(pour.id, ActivityUpdate(duration_days=pour.duration_days + 3))
        pinned = (await _by_name(session, schedule_id))["Pour"]
        assert pinned.metadata_[DURATION_LOCKED_KEY] is True
        pinned_days = pinned.duration_days

        pos = await session.get(Position, ids["Pour"])
        pos.quantity = "300"
        await session.flush()
        assert await follow_position_quantity(session, ids["Pour"], "100") == []
        assert (await _by_name(session, schedule_id))["Pour"].duration_days == pinned_days


def test_crew_reads_the_generated_resources() -> None:
    from app.modules.schedule.boq_followup import _crew

    rows = [{"type": "labor", "count": 3}, {"type": "equipment", "count": 2}, SimpleNamespace()]
    assert _crew(rows) == (3, 2)
    assert _crew(None) == (1, 1)


@pytest.mark.asyncio
async def test_the_committed_bill_edit_reaches_the_schedule_through_the_event(monkeypatch) -> None:
    """The real path: publish after commit, handler opens its own session and commits."""
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker

    import app.database
    from app.modules.boq.schemas import PositionUpdate
    from app.modules.boq.service import BOQService
    from app.modules.schedule import events as schedule_events
    from app.modules.schedule.models import Activity
    from tests._pg import isolated_engine

    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        # Every session the handlers open lands in this throwaway database.
        monkeypatch.setattr(app.database, "async_session_factory", factory)
        monkeypatch.setattr(schedule_events, "async_session_factory", factory)

        async with factory() as session:
            _service, schedule_id, ids = await _plan(session)
            pour = (await _by_name(session, schedule_id))["Pour"]
            pour_id, pour_days = pour.id, pour.duration_days
            await session.commit()

        async with factory() as session:
            await BOQService(session).update_position(ids["Pour"], PositionUpdate(quantity=200))
            await session.commit()

        days = pour_days
        for _ in range(100):
            await asyncio.sleep(0.1)
            async with factory() as check:
                days = (await check.get(Activity, pour_id)).duration_days
            if days != pour_days:
                break
        assert pour_days < days <= 2 * pour_days
        await asyncio.sleep(0.5)  # let the other detached handlers finish before the database is dropped
