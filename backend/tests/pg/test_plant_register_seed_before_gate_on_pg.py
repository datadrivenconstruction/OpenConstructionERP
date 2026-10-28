# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The demo register of a project that has not started building, on PostgreSQL.

A project whose gate into the phase that enables construction start is still
undecided is seeded as one day before that gate. Nothing may contradict that
day: no item ordered, need dates after the construction start,
long-lead order dates before the gate date. A project past the gate, or
without a governance model, gets the full range of states.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.plant_register import seed
from app.modules.plant_register.models import DecisionPaper, ItService, PlantItem, SlotReservation
from app.modules.plant_register.ports import unregister_commitment_provider, unregister_package_plan_provider
from app.modules.plant_register.service import PlantService
from tests._pg import isolated_engine
from tests.pg.plant_fixtures import World, build_world

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def world():
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        yield await build_world(factory)
    unregister_package_plan_provider()
    unregister_commitment_provider()


async def _as_demo_project(w: World) -> None:
    from app.modules.approval_routes.models import Route, Step
    from app.modules.projects.models import Project

    async with w.factory() as s:
        project = await s.get(Project, w.project_id)
        project.metadata_ = {"demo_id": "plant-demo"}
        project.currency = "CAD"
        for step in (await s.execute(select(Step).where(Step.route_id == w.route_id))).scalars():
            await s.delete(step)
        await s.delete(await s.get(Route, w.route_id))
        await s.commit()


async def _seed(w: World) -> set[str]:
    async with w.factory() as s:
        out = await seed.seed_plant_register_demo(s, [w.project_id])
        await s.commit()
    assert out["projects"] == 1 and out["items"] == 13
    async with w.factory() as s:
        rows = await s.execute(select(PlantItem.status).where(PlantItem.project_id == w.project_id))
        return set(rows.scalars())


_PAST_ORDERED = {"manufactured", "delivered", "commissioned", "handed_over"}


async def test_a_project_whose_construction_gate_is_decided_gets_the_full_story(world: World) -> None:
    from app.modules.project_governance.models import GovernanceGate

    await _as_demo_project(world)
    async with world.factory() as s:
        assert await seed._before_construction_gate(s, world.project_id) is True
        gates = await s.execute(select(GovernanceGate).where(GovernanceGate.project_id == world.project_id))
        for gate in gates.scalars():
            if gate.to_phase == "execution":
                gate.status = "decided"  # the fixture's shortcut for a decision taken earlier
        await s.commit()
    async with world.factory() as s:
        assert await seed._before_construction_gate(s, world.project_id) is False
    assert await _seed(world) >= _PAST_ORDERED


async def test_a_project_without_a_governance_model_gets_the_full_story(world: World) -> None:
    from app.modules.projects.models import Project
    from tests.pg.governance_fixtures import add_project

    async with world.factory() as s:
        bare = await add_project(s, world.manager, [world.area_owner])
        (await s.get(Project, bare)).metadata_ = {"demo_id": "plant-demo-bare"}
        await s.commit()
        assert await seed._before_construction_gate(s, bare) is False
    world.provider.plans[bare] = world.provider.plans[world.project_id]
    async with world.factory() as s:
        out = await seed.seed_plant_register_demo(s, [bare])
        await s.commit()
        rows = await s.execute(select(PlantItem.status).where(PlantItem.project_id == bare))
        states = set(rows.scalars())
    assert out["projects"] == 1 and states >= _PAST_ORDERED


async def test_a_project_before_its_construction_gate_is_seeded_as_that_day(world: World) -> None:
    await _as_demo_project(world)
    today = datetime.now(UTC).date()
    async with world.factory() as s:
        out = await seed.seed_plant_register_demo(s, [world.project_id])
        await s.commit()
    assert out["projects"] == 1 and out["items"] == 13

    async with world.factory() as s:
        items = list((await s.execute(select(PlantItem).where(PlantItem.project_id == world.project_id))).scalars())
        slots = list(
            (await s.execute(select(SlotReservation).where(SlotReservation.project_id == world.project_id))).scalars()
        )
        papers = list(
            (await s.execute(select(DecisionPaper).where(DecisionPaper.project_id == world.project_id))).scalars()
        )
        services = list((await s.execute(select(ItService).where(ItService.project_id == world.project_id))).scalars())
        views = await PlantService(s).item_views(world.project_id, today=today)

    # Nothing of execution has happened and nothing is ordered: the first order is placed after the decision.
    assert {i.status for i in items} == {"identified", "specified", "enquired", "route_set", "cancelled"}
    by_code = {i.code: i for i in items}
    assert by_code["PL-001"].status == "enquired"
    assert sorted(s.status for s in slots) == ["held", "requested"]
    assert [p.status for p in papers] == ["approved"]

    start = today + timedelta(days=seed.CONSTRUCTION_START_DAYS)
    gate = today + timedelta(days=seed.GATE_TARGET_DAYS)
    assert all(i.need_date_fixed > start for i in items)
    dated = [v for v in views if v["long_lead"] and v["item"].status != "cancelled" and v["latest_order_date"]]
    # The items that cannot wait for the gate: their order date falls before it, and none is overdue today.
    urgent = [v for v in dated if v["latest_order_date"] < gate]
    assert len(urgent) >= 5
    assert {v["code"]: v["latest_order_date"] for v in urgent if v["latest_order_date"] < today} == {}
    assert len({v["latest_order_date"] for v in urgent}) > 1
    # The transformer's order date is the one the commitment for its supply order reads: a few days out,
    # before the gate and well before its production slot has to be converted.
    transformer = next(v for v in views if v["code"] == "PL-001")
    assert transformer["latest_order_date"] == today + timedelta(days=4)
    # Every other long-lead item can be ordered after the decision.
    assert all(v["latest_order_date"] >= gate for v in dated if v not in urgent)
    assert "overdue" not in {v["order_status"] for v in views}

    assert {x.status for x in services} == {"planned"}
    assert all(x.needed_from >= today + timedelta(days=seed.MOBILISATION_DAYS) for x in services)
