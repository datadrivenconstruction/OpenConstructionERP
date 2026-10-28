# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The readiness criteria of a catalogue as a checklist per area, over HTTP against PostgreSQL."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.modules.project_governance.events as gov_events
from app.modules.project_governance.permissions import register_governance_permissions
from app.modules.project_governance.service import GovernanceService
from tests._pg import isolated_engine
from tests.pg.governance_fixtures import World, areas, build_world, client_as, gate, project_url

pytestmark = pytest.mark.asyncio

FRAMEWORK = "elf_module_framework"
GATE = "development_to_execution"
AREA = "m01_project_management"
CRITERION = "frame_document_approved"
NAME_KEY = f"governance.catalogue.{FRAMEWORK}.criterion.{CRITERION}"


@pytest_asyncio.fixture
async def world(monkeypatch: pytest.MonkeyPatch):
    register_governance_permissions()
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        monkeypatch.setattr(gov_events, "async_session_factory", factory)
        w = await build_world(factory, catalogue_id=FRAMEWORK)
        async with factory() as s:
            area = (await areas(w))[AREA]
            await GovernanceService(s).update_area(
                w.project_id, area.id, changes={"owner_user_id": w.owner}, actor_id=w.manager
            )
            await s.commit()
        yield w


async def test_the_tick_is_offered_to_the_owner_only(world: World) -> None:
    g = await gate(world, GATE)
    offered = {}
    for name, user in (("owner", world.owner), ("editor", world.editor), ("manager", world.manager)):
        async with client_as(world, user, "editor") as c:
            detail = (await c.get(f"{project_url(world)}/gates/{g.id}")).json()
        offered[name] = {a["code"]: a for a in detail["areas"]}[AREA]["can_tick"]
    assert offered == {"owner": True, "editor": False, "manager": False}


async def _checklist(w: World, gate_id: uuid.UUID, area_code: str = AREA) -> list[dict]:
    async with client_as(w, w.manager, "manager") as c:
        r = await c.get(f"{project_url(w)}/gates/{gate_id}")
    assert r.status_code == 200, r.text
    return {a["code"]: a for a in r.json()["areas"]}[area_code]["criteria"]


async def _tick(w: World, user: uuid.UUID, gate_id: uuid.UUID, code: str, body: dict, area_code: str = AREA):
    area = (await areas(w))[area_code]
    async with client_as(w, user, "editor") as c:
        return await c.put(f"{project_url(w)}/gates/{gate_id}/checks/{area.id}/criteria/{code}", json=body)


async def test_the_criteria_of_the_model_are_listed_unticked_with_their_names(world: World) -> None:
    g = await gate(world, GATE)
    rows = await _checklist(world, g.id)
    assert rows, "the framework defines criteria for this area at this gate"
    first = {r["code"]: r for r in rows}[CRITERION]
    assert first == {
        "code": CRITERION,
        "met": False,
        "note": "",
        "ticked_by": None,
        "ticked_at": None,
        "name": {"key": NAME_KEY, "text": None},
    }


async def test_the_owner_ticks_a_criterion_and_the_server_says_who_and_when(world: World) -> None:
    g = await gate(world, GATE)
    before = datetime.now(UTC) - timedelta(seconds=5)
    r = await _tick(
        world, world.owner, g.id, CRITERION, {"met": True, "note": "Approved by the board", "ticked_at": "2001-01-01"}
    )
    assert r.status_code == 200, r.text
    row = {x["code"]: x for x in await _checklist(world, g.id)}[CRITERION]
    assert (row["met"], row["note"], row["ticked_by"]) == (True, "Approved by the board", str(world.owner))
    assert datetime.fromisoformat(row["ticked_at"]) >= before
    # Ticking the list is not attesting: the area is still not assessed and still blocks.
    async with client_as(world, world.manager, "manager") as c:
        detail = (await c.get(f"{project_url(world)}/gates/{g.id}")).json()
    assert {a["code"]: a for a in detail["areas"]}[AREA]["check"]["status"] == "not_assessed"
    assert any(b["code"] == "area_not_ready" and b["area_code"] == AREA for b in detail["blockers"])

    back = await _tick(world, world.owner, g.id, CRITERION, {"met": False, "note": "Withdrawn"})
    assert back.status_code == 200, back.text
    row = {x["code"]: x for x in await _checklist(world, g.id)}[CRITERION]
    assert (row["met"], row["note"], row["ticked_by"]) == (False, "Withdrawn", str(world.owner))


async def test_only_the_owner_of_the_area_ticks_and_only_criteria_of_the_model(world: World) -> None:
    g = await gate(world, GATE)
    stranger = await _tick(world, world.editor, g.id, CRITERION, {"met": True})
    assert stranger.status_code == 403, stranger.text
    assert stranger.json()["detail"]["code"] == "not_area_owner"
    invented = await _tick(world, world.owner, g.id, "no_such_criterion", {"met": True})
    assert invented.status_code == 422, invented.text
    assert invented.json()["detail"]["code"] == "unknown_criterion"
    assert all(not r["met"] for r in await _checklist(world, g.id))
