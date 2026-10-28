# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Site plant positions over HTTP against PostgreSQL: place, move, remove, and who may.

A position is a point on the site plan (local metres, y up) with a kind from
the plant catalogue, optionally the register item it places and the expansion
stage it belongs to. Every link is checked against the project, the point is
stored exactly as given, and the listing carries the server's own verdict on
what the caller may do.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.plant_register.errors import PlantError
from app.modules.plant_register.permissions import register_plant_permissions
from app.modules.plant_register.ports import unregister_package_plan_provider
from app.modules.plant_register.router import router
from app.modules.plant_register.site_plant import (
    SitePlantService,
    StageRef,
    clean,
    position_project,
    register_stage_provider,
    unregister_stage_provider,
)
from app.modules.site_logistics.models import LaydownZone, SitePlantPosition
from tests._pg import isolated_engine
from tests.pg.governance_fixtures import add_project
from tests.pg.plant_fixtures import World, build_world, item

pytestmark = [pytest.mark.asyncio, pytest.mark.tenant_isolation]

BASE = "/api/v1/plant-register"


@dataclass
class FakeStages:
    """The site logistics plan: it knows the stages it was given, per project."""

    stages: dict[tuple[uuid.UUID, uuid.UUID], StageRef] = field(default_factory=dict)

    async def get_stage(self, session: Any, project_id: uuid.UUID, stage_id: uuid.UUID) -> StageRef | None:
        return self.stages.get((project_id, stage_id))

    def add(self, project_id: uuid.UUID, code: str) -> uuid.UUID:
        sid = uuid.uuid4()
        self.stages[(project_id, sid)] = StageRef(sid, code, code.title())
        return sid


@pytest_asyncio.fixture
async def world():
    register_plant_permissions()
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        yield await build_world(factory)
    unregister_package_plan_provider()
    unregister_stage_provider()


@asynccontextmanager
async def client_as(w: World, user_id: uuid.UUID, role: str):
    from app.dependencies import get_current_user_id, get_current_user_payload, get_session

    app = FastAPI()
    app.include_router(router, prefix=BASE)

    async def _session():
        async with w.factory() as s:
            yield s
            await s.commit()

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_current_user_id] = lambda: str(user_id)
    app.dependency_overrides[get_current_user_payload] = lambda: {
        "sub": str(user_id),
        "role": role,
        "permissions": [],
        "tenant_id": str(user_id),
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://plant-test") as c:
        yield c


def _url(w: World, tail: str = "") -> str:
    return f"{BASE}/projects/{w.project_id}/site-plant-positions{tail}"


_CRANE = {"kind": "tower_crane", "name": "Tower crane 1", "x": "42.500", "y": "-28.125", "reach_m": "60.00"}


async def _stored(w: World, position_id: str) -> SitePlantPosition | None:
    async with w.factory() as s:
        return await s.get(SitePlantPosition, uuid.UUID(position_id))


async def _count(w: World) -> int:
    async with w.factory() as s:
        rows = await s.execute(select(SitePlantPosition.id).where(SitePlantPosition.project_id == w.project_id))
        return len(rows.all())


# ── place, move, remove ───────────────────────────────────────────────────


async def test_a_position_is_placed_moved_and_removed_and_the_point_is_kept_exactly(world: World) -> None:
    stages = FakeStages()
    register_stage_provider(stages)
    earthworks, structure = stages.add(world.project_id, "earthworks"), stages.add(world.project_id, "structure")
    iid = await item(world, "PL-1", "power_transformer")
    async with client_as(world, world.area_owner, "editor") as c:
        placed = await c.post(_url(world), json={**_CRANE, "stage_id": str(earthworks)})
        assert placed.status_code == 201, placed.text
        pid = placed.json()["id"]
        pad = await c.post(
            _url(world),
            json={"kind": "mobile_crane_pad", "x": "12", "y": "64", "plant_item_id": str(iid), "max_load_t": "120.00"},
        )
        assert pad.status_code == 201, pad.text
        # y grows upwards and is stored as sent: no flip, no rounding, a negative y stays negative.
        row = await _stored(world, pid)
        assert (row.x, row.y, row.reach_m, row.stage_id) == (
            Decimal("42.500"),
            Decimal("-28.125"),
            Decimal("60.00"),
            earthworks,
        )

        moved = await c.patch(_url(world, f"/{pid}"), json={"x": "40.000", "y": "30.500", "stage_id": str(structure)})
        assert moved.status_code == 200, moved.text
        assert (moved.json()["x"], moved.json()["y"], moved.json()["stage_id"]) == ("40.000", "30.500", str(structure))
        assert moved.json()["name"] == "Tower crane 1"  # a move changes what it names, nothing else

        listed = (await c.get(_url(world))).json()
        on_structure = (await c.get(_url(world), params={"stage_id": str(structure)})).json()
        of_item = (await c.get(_url(world), params={"plant_item_id": str(iid)})).json()
        assert listed["total"] == 2 and [p["id"] for p in on_structure["items"]] == [pid]
        assert [(p["plant_item_code"], p["plant_item_title"]) for p in of_item["items"]] == [("PL-1", "Item PL-1")]

        cleared = await c.patch(_url(world, f"/{pid}"), json={"stage_id": None, "reach_m": None})
        assert (cleared.json()["stage_id"], cleared.json()["reach_m"]) == (None, None)

        gone = await c.delete(_url(world, f"/{pid}"))
        again = await c.delete(_url(world, f"/{pid}"))
    assert (gone.status_code, again.status_code) == (204, 404)
    assert again.json()["detail"]["code"] == "position_not_found"
    assert await _stored(world, pid) is None and await _count(world) == 1


# ── links resolve inside the project ──────────────────────────────────────


async def test_the_plant_item_the_stage_and_the_zone_must_belong_to_the_project(world: World) -> None:
    stages = FakeStages()
    register_stage_provider(stages)
    async with world.factory() as s:
        other_project = await add_project(s, world.outsider, [])
        zone = LaydownZone(project_id=other_project, name="Their yard")
        s.add(zone)
        await s.commit()
        foreign_zone = zone.id
    foreign_stage = stages.add(other_project, "theirs")
    cancelled = await item(world, "PL-9", "lift")
    async with world.factory() as s:
        from app.modules.plant_register.models import PlantItem

        (await s.get(PlantItem, cancelled)).status = "cancelled"
        await s.commit()

    async with client_as(world, world.manager, "manager") as c:
        answers = {}
        for name, extra in (
            ("unknown item", {"plant_item_id": str(uuid.uuid4())}),
            ("cancelled item", {"plant_item_id": str(cancelled)}),
            ("foreign stage", {"stage_id": str(foreign_stage)}),
            ("unknown stage", {"stage_id": str(uuid.uuid4())}),
            ("foreign zone", {"laydown_zone_id": str(foreign_zone)}),
            ("unknown kind", {"kind": "catapult"}),
        ):
            r = await c.post(_url(world), json={**_CRANE, **extra})
            answers[name] = (r.status_code, r.json()["detail"]["code"])
        placed = (await c.post(_url(world), json=_CRANE)).json()["id"]
        patched = await c.patch(_url(world, f"/{placed}"), json={"stage_id": str(foreign_stage)})
    assert answers == {
        "unknown item": (404, "item_not_found"),
        "cancelled item": (409, "item_closed"),
        "foreign stage": (404, "stage_not_found"),
        "unknown stage": (404, "stage_not_found"),
        "foreign zone": (404, "laydown_zone_not_found"),
        "unknown kind": (422, "unknown_site_plant_kind"),
    }
    assert (patched.status_code, patched.json()["detail"]["code"]) == (404, "stage_not_found")
    assert await _count(world) == 1 and (await _stored(world, placed)).stage_id is None


async def test_a_stage_id_is_not_stored_while_nobody_can_confirm_it(world: World) -> None:
    async with client_as(world, world.manager, "manager") as c:
        refused = await c.post(_url(world), json={**_CRANE, "stage_id": str(uuid.uuid4())})
        without = await c.post(_url(world), json=_CRANE)
    assert (refused.status_code, refused.json()["detail"]["code"]) == (422, "stage_unavailable")
    assert without.status_code == 201 and await _count(world) == 1


async def test_a_position_of_another_project_is_not_reached(world: World) -> None:
    async with world.factory() as s:
        other_project = await add_project(s, world.outsider, [])
        row = SitePlantPosition(project_id=other_project, kind="hoist", x=Decimal(1), y=Decimal(2))
        s.add(row)
        await s.commit()
        foreign = row.id
        assert await position_project(s, foreign) == other_project
        assert await position_project(s, uuid.uuid4()) is None
    async with client_as(world, world.manager, "manager") as c:
        codes = [
            (await c.patch(_url(world, f"/{foreign}"), json={"x": "5"})).status_code,
            (await c.delete(_url(world, f"/{foreign}"))).status_code,
            (await c.get(_url(world, f"/{foreign}"))).status_code,
        ]
        mine = (await c.get(_url(world))).json()["total"]
    async with client_as(world, world.outsider, "manager") as c:
        stranger = [
            (await c.get(_url(world))).status_code,
            (await c.post(_url(world), json=_CRANE)).status_code,
        ]
    assert codes == [404, 404, 404] and mine == 0
    assert all(code in (403, 404) for code in stranger) and await _count(world) == 0
    assert (await _stored(world, str(foreign))).x == Decimal(1)


# ── the point and its numbers ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "body",
    [
        {"x": None},
        {"y": None},
        {"kind": None},
        {"x": "12.3456"},  # finer than a millimetre is not stored, so it is not accepted
        {"x": "1234567890"},  # does not fit the column
        {"y": "NaN"},
        {"y": "Infinity"},
        {"x": 12.5},  # a float is not an exact length
        {"reach_m": "-1"},
        {"max_load_t": "-0.01"},
        {"power_demand_kva": "-5"},
        {"reach_m": "60.005"},
        {"from_date": "2027-06-01", "to_date": "2027-05-31"},
    ],
)
async def test_a_point_or_a_number_the_table_cannot_hold_is_refused(world: World, body: dict[str, Any]) -> None:
    async with client_as(world, world.manager, "manager") as c:
        placed = (await c.post(_url(world), json=_CRANE)).json()["id"]
        created = await c.post(_url(world), json={**_CRANE, **body})
        patched = await c.patch(_url(world, f"/{placed}"), json=body)
    assert (created.status_code, patched.status_code) == (422, 422), (created.text, patched.text)
    row = await _stored(world, placed)
    assert (row.x, row.y, row.reach_m, row.kind) == (
        Decimal("42.500"),
        Decimal("-28.125"),
        Decimal("60.00"),
        "tower_crane",
    )
    assert await _count(world) == 1


async def test_a_position_needs_its_kind_and_its_point(world: World) -> None:
    async with client_as(world, world.manager, "manager") as c:
        codes = [
            (await c.post(_url(world), json={"kind": "hoist", "x": "1"})).status_code,
            (await c.post(_url(world), json={"x": "1", "y": "2"})).status_code,
        ]
        # A national grid runs to millions of metres: that is a valid local frame.
        grid = await c.post(_url(world), json={"kind": "hoist", "x": "3456789.125", "y": "5678901.250"})
    assert codes == [422, 422] and grid.status_code == 201
    assert (grid.json()["x"], grid.json()["y"]) == ("3456789.125", "5678901.250")


async def test_the_service_types_what_a_direct_caller_hands_in(world: World) -> None:
    assert clean({"x": "42.5", "y": Decimal("3"), "note": None, "unknown": 1}) == {
        "x": Decimal("42.5"),
        "y": Decimal("3"),
        "note": "",
    }
    with pytest.raises(PlantError) as exc:
        clean({"x": 1.5})
    assert (exc.value.code, exc.value.detail) == ("position_number_invalid", "x")
    async with world.factory() as s:
        row = await SitePlantService(s).place(
            world.project_id, {"kind": "hoist", "x": "7", "y": "8", "from_date": "2027-01-10"}, actor_id=world.manager
        )
        await s.commit()
    stored = await _stored(world, str(row.id))
    assert (stored.x, stored.from_date.isoformat()) == (Decimal(7), "2027-01-10")


# ── who may, and what the listing says about it ───────────────────────────


async def test_the_listing_says_what_the_caller_may_do_and_the_write_agrees(world: World) -> None:
    async with client_as(world, world.manager, "manager") as c:
        pid = (await c.post(_url(world), json=_CRANE)).json()["id"]
    verdicts = {}
    for name, user, role in (
        ("manager", world.manager, "manager"),
        ("area_owner", world.area_owner, "editor"),
        ("editor", world.editor, "editor"),
        ("viewer", world.editor, "viewer"),
    ):
        async with client_as(world, user, role) as c:
            listed = (await c.get(_url(world))).json()
            place = await c.post(_url(world), json={**_CRANE, "name": name})
            move = await c.patch(_url(world, f"/{pid}"), json={"note": name})
        row_can = listed["items"][0]["can"]
        # The actions exist for everyone; who may not use them sees them refused with a reason.
        assert [v["applies"] for v in (listed["can"]["place"], row_can["move"], row_can["remove"])] == [True] * 3
        assert row_can["move"]["reason"] == row_can["remove"]["reason"] == listed["can"]["place"]["reason"]
        verdicts[name] = (
            listed["can"]["place"]["allowed"],
            listed["can"]["place"]["reason"],
            row_can["move"]["allowed"],
            row_can["remove"]["allowed"],
            place.status_code,
            move.status_code,
        )
    assert verdicts == {
        "manager": (True, None, True, True, 201, 200),
        "area_owner": (True, None, True, True, 201, 200),
        "editor": (False, "not_equipment_owner", False, False, 403, 403),
        "viewer": (False, "edit_permission_required", False, False, 403, 403),
    }
