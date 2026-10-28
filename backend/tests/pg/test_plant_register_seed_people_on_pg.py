# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Whose name the plant demo seed may write, on PostgreSQL.

The seed runs on real installations when a pack with demo projects is
installed. It may act as the project owner and let the decision paper be
decided by the demo cast or a team member of the project. An account that
merely exists in the installation is somebody's own login and appears on no
seeded row, and a project without a second person is a legal state: the paper
stays a draft, said at info level and in the result.
"""

from __future__ import annotations

import logging
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database import GUID, Base
from app.modules.plant_register import seed
from app.modules.plant_register.models import DecisionPaper, PlantItem
from app.modules.plant_register.ports import unregister_commitment_provider, unregister_package_plan_provider
from tests._pg import isolated_engine
from tests.pg.governance_fixtures import add_project, add_user
from tests.pg.plant_fixtures import World, build_world

pytestmark = pytest.mark.asyncio

# Rows that are the person, not something written in their name.
_OWN_TABLES = ("oe_users_",)


@pytest_asyncio.fixture
async def world():
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        yield await build_world(factory)
    unregister_package_plan_provider()
    unregister_commitment_provider()


async def _demo_project(w: World, members: list[uuid.UUID]) -> uuid.UUID:
    """A demo project owned by the world's manager, with no approval route of its own."""
    from app.modules.projects.models import Project

    async with w.factory() as s:
        pid = await add_project(s, w.manager, members)
        (await s.get(Project, pid)).metadata_ = {"demo_id": f"plant-people-{pid.hex[:6]}"}
        await s.commit()
    w.provider.plans[pid] = w.provider.plans[w.project_id]
    return pid


async def _rows_naming(w: World, user_id: uuid.UUID) -> dict[str, int]:
    """Every table and column of the schema that holds ``user_id``, the person's own rows left out."""
    found: dict[str, int] = {}
    async with w.factory() as s:
        for table in Base.metadata.sorted_tables:
            if table.name.startswith(_OWN_TABLES):
                continue
            for column in table.columns:
                if not isinstance(column.type, GUID):
                    continue
                count = (await s.execute(select(func.count()).select_from(table).where(column == user_id))).scalar_one()
                if count:
                    found[f"{table.name}.{column.name}"] = count
    return found


def _above_info(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        f"{r.levelname} {r.getMessage()}"
        for r in caplog.records
        if r.name.startswith("app.modules.plant_register") and r.levelno > logging.INFO
    ]


async def _papers(w: World, pid: uuid.UUID) -> list[str]:
    async with w.factory() as s:
        return list((await s.execute(select(DecisionPaper.status).where(DecisionPaper.project_id == pid))).scalars())


async def test_an_account_outside_the_project_is_on_no_seeded_row(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    async with world.factory() as s:
        # Real accounts of the installation, none of them on the demo project. The seed used to take
        # "the first active user who is not the owner", so there are several and one of each role.
        foreign = [await add_user(s, role) for role in ("admin", "manager", "editor", "viewer")]
        await s.commit()
    foreign.append(world.outsider)
    member = world.editor
    pid = await _demo_project(world, [member])
    before = {user: await _rows_naming(world, user) for user in foreign}

    caplog.set_level(logging.INFO)
    async with world.factory() as s:
        out = await seed.seed_plant_register_demo(s, [pid])
        await s.commit()

    assert (out["projects"], out["items"]) == (1, 13)
    # The paper was decided, and by the one team member of the project.
    assert await _papers(world, pid) == ["approved"] and out["papers_left_draft"] == 0 and out["notes"] == []
    assert any(name.startswith("oe_approval") for name in await _rows_naming(world, member))
    # Nobody else of the installation gained a row anywhere in the schema.
    assert {user: await _rows_naming(world, user) for user in foreign} == before
    assert _above_info(caplog) == []


async def test_without_a_second_person_the_paper_stays_a_draft_and_the_result_says_so(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    pid = await _demo_project(world, [])
    everyone_else = [world.area_owner, world.editor, world.approver, world.outsider]
    before = {user: await _rows_naming(world, user) for user in everyone_else}

    caplog.set_level(logging.INFO)
    async with world.factory() as s:
        out = await seed.seed_plant_register_demo(s, [pid])
        await s.commit()

    # A legal state, not a failure: the register is seeded, the paper waits for a person the project does not have.
    assert (out["projects"], out["items"], out["papers_left_draft"]) == (1, 13, 1)
    assert out["notes"] == [{"project_id": str(pid), "note": "decision_paper_left_draft"}]
    assert await _papers(world, pid) == ["draft"]
    assert {user: await _rows_naming(world, user) for user in everyone_else} == before
    assert _above_info(caplog) == []
    async with world.factory() as s:
        statuses = set((await s.execute(select(PlantItem.status).where(PlantItem.project_id == pid))).scalars())
    # The item that needs the paper stops before its route is set; the others are not held back by it.
    assert "handed_over" in statuses


async def test_a_route_that_names_somebody_outside_the_project_is_left_alone(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    from app.modules.plant_register.service import PAPER_TARGET_KIND
    from tests.pg.governance_fixtures import add_route

    pid = await _demo_project(world, [world.editor])
    async with world.factory() as s:
        await add_route(s, pid, PAPER_TARGET_KIND, world.outsider)
        await s.commit()
    before = await _rows_naming(world, world.outsider)

    caplog.set_level(logging.INFO)
    async with world.factory() as s:
        out = await seed.seed_plant_register_demo(s, [pid])
        await s.commit()

    # The project sends its papers to that desk; the seed neither signs for that person nor queues work there.
    assert await _papers(world, pid) == ["draft"] and out["papers_left_draft"] == 1
    assert await _rows_naming(world, world.outsider) == before
    assert _above_info(caplog) == []


async def _seeded(w: World) -> uuid.UUID:
    pid = await _demo_project(w, [w.editor])
    async with w.factory() as s:
        out = await seed.seed_plant_register_demo(s, [pid])
        await s.commit()
    assert out["projects"] == 1
    return pid


async def test_the_held_slot_of_the_transformer_binds_no_money_and_says_where_money_is_bound(world: World) -> None:
    import re

    from app.modules.plant_register.models import SlotReservation

    pid = await _seeded(world)
    async with world.factory() as s:
        item = (
            await s.execute(select(PlantItem).where(PlantItem.project_id == pid, PlantItem.code == "PL-001"))
        ).scalar_one()
        slot = (await s.execute(select(SlotReservation).where(SlotReservation.plant_item_id == item.id))).scalar_one()
    # One slot story: the slot is held free of charge, and the amount of a reservation lives only in the
    # commitment the project plans for it. The seed repeats no figure and invents no link.
    assert (item.status, slot.status, slot.reservation_fee, slot.commitment_item_id) == ("enquired", "held", 0, None)
    assert "commitment" in slot.terms and "without a fee" in slot.terms
    assert "costs" not in slot.terms
    assert re.search(r"\d", slot.terms) is None


async def test_the_seeded_switchgear_can_still_be_given_an_owner_furnished_route(world: World) -> None:
    from app.modules.plant_register.service import PlantService

    pid = await _seeded(world)
    async with world.factory() as s:
        svc = PlantService(s)
        item = (
            await s.execute(select(PlantItem).where(PlantItem.project_id == pid, PlantItem.code == "PL-002"))
        ).scalar_one()
        assert (item.status, item.procurement_route) == ("route_set", seed.ROUTE)
        assert svc.route_refusal(item) is None
        calls = world.provider.ensure_calls
        # The delivery model takes the item over: the owner buys it, the installation package fits it.
        changed = await svc.set_route(
            pid,
            item.id,
            route="owner_furnished_contractor_installed",
            contract_package_id=world.installer_pkg,
            actor_id=world.manager,
        )
        await s.commit()
    assert (changed.status, changed.procurement_route) == ("route_set", "owner_furnished_contractor_installed")
    assert changed.owner_furnished_item_id is not None and world.provider.ensure_calls == calls + 1
