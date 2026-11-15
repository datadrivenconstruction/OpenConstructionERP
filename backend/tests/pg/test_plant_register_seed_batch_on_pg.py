# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The plant demo seed writes its audit trail in one insert and the data stays what it was.

Counts, the status of every item and the audit trail (rows and their order) are pinned
here, so a change to how the seed writes cannot change what it writes.
"""

from __future__ import annotations

import uuid
from collections import Counter

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.audit_log import ActivityLog, deferred_audit, log_activity
from app.modules.plant_register import seed
from app.modules.plant_register.models import PlantItem
from app.modules.plant_register.ports import unregister_commitment_provider, unregister_package_plan_provider
from tests._pg import isolated_engine
from tests.pg.plant_fixtures import World, build_world
from tests.pg.test_plant_register_seed_people_on_pg import _demo_project

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def world():
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        yield await build_world(factory)
    unregister_package_plan_provider()
    unregister_commitment_provider()


async def test_the_seed_pins_its_rows_statuses_and_audit_trail(world: World) -> None:
    pid = await _demo_project(world, [world.editor])
    async with world.factory() as s:
        out = await seed.seed_plant_register_demo(s, [pid])
        await s.commit()
    assert (out["projects"], out["items"], out["quotes"], out["papers_left_draft"]) == (1, 13, 12, 0)

    async with world.factory() as s:
        items = (await s.execute(select(PlantItem).where(PlantItem.project_id == pid))).scalars().all()
        assert Counter(i.status for i in items) == {
            "enquired": 3,
            "route_set": 2,
            "cancelled": 1,
            "commissioned": 1,
            "delivered": 1,
            "handed_over": 1,
            "identified": 1,
            "manufactured": 1,
            "ordered": 1,
            "specified": 1,
        }
        by_id = {str(i.id): i.code for i in items}
        trail = (
            (
                await s.execute(
                    select(ActivityLog)
                    .where(ActivityLog.entity_type.like(r"plant\_%"))
                    .order_by(ActivityLog.created_at, ActivityLog.id)
                )
            )
            .scalars()
            .all()
        )
    # Every row of the trail carries a time of its own call, so the order of events is the order of the work.
    assert Counter((r.entity_type, r.action) for r in trail) == {
        ("plant_decision_paper", "created"): 1,
        ("plant_decision_paper", "status_changed"): 2,
        ("plant_it_service", "created"): 4,
        ("plant_item", "created"): 13,
        ("plant_item", "delivery_limits_set"): 9,
        ("plant_item", "route_set"): 9,
        ("plant_item", "status_changed"): 37,
        ("plant_item", "updated"): 5,
        ("plant_lead_time_quote", "created"): 12,
        ("plant_slot_reservation", "created"): 2,
        ("plant_slot_reservation", "status_changed"): 1,
        ("plant_spare_part", "created"): 8,
    }
    created = [by_id[r.entity_id] for r in trail if (r.entity_type, r.action) == ("plant_item", "created")]
    assert created == [spec["code"] for spec in seed._ITEMS]
    first_change = {}
    for r in trail:
        if r.entity_type == "plant_item" and r.action == "status_changed":
            first_change.setdefault(r.entity_id, r)
    assert all(r.from_status == "identified" and r.to_status == "specified" for r in first_change.values())


async def test_deferred_audit_rows_match_direct_ones_and_vanish_with_a_failed_body(world: World) -> None:
    async def write(s: AsyncSession, tag: str) -> None:
        for n in range(3):
            await log_activity(
                s, actor_id=world.manager, entity_type="probe", entity_id=f"{tag}-{n}", action="created", module="probe"
            )

    async def fail_in_body(s: AsyncSession) -> None:
        async with deferred_audit(s):
            await write(s, "lost")
            raise RuntimeError

    async with world.factory() as s:
        await write(s, "direct")
        async with deferred_audit(s):
            await write(s, "deferred")
            assert (
                await s.execute(select(func.count()).select_from(ActivityLog).where(ActivityLog.module == "probe"))
            ).scalar_one() == 3
        with pytest.raises(RuntimeError):
            await fail_in_body(s)
        await s.commit()
    async with world.factory() as s:
        rows = (
            (await s.execute(select(ActivityLog).where(ActivityLog.module == "probe").order_by(ActivityLog.created_at)))
            .scalars()
            .all()
        )
    assert [r.entity_id for r in rows] == [f"{t}-{n}" for t in ("direct", "deferred") for n in range(3)]
    assert all(isinstance(r.id, uuid.UUID) and r.actor_id == world.manager for r in rows)
