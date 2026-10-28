# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The ``can`` of a plant item over HTTP against PostgreSQL: the verdict and the write agree.

Every item answer says, per action, whether the action exists for the item in
its state (``applies``), whether this caller may use it (``allowed``) and the
code a refusal would carry (``reason``). The screen builds its buttons from
that alone, so a verdict that differs from what the route then answers is a
button that lies. These tests do not restate the rules: they read the verdict,
make the real request, and compare the two.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import date
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.plant_register import seed
from app.modules.plant_register.models import PlantItem
from app.modules.plant_register.permissions import register_plant_permissions
from app.modules.plant_register.ports import unregister_package_plan_provider
from app.modules.plant_register.router import router
from app.modules.plant_register.service import PlantService
from tests._pg import isolated_engine
from tests.pg.plant_fixtures import World, build_world, get, item, quote

TODAY = date(2026, 10, 11)

pytestmark = [pytest.mark.asyncio, pytest.mark.tenant_isolation]

BASE = "/api/v1/plant-register"
ACTIONS = (
    "edit",
    "edit_specification",
    "edit_classification",
    "set_route",
    "handover",
    "transition_specified",
    "transition_enquired",
    "transition_route_set",
    "transition_manufactured",
    "transition_cancelled",
)
# A class that is not critical, so an item of it reaches ``route_set`` without a decision paper.
PLAIN_CLASS = "escalator"


@pytest_asyncio.fixture
async def world():
    register_plant_permissions()
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        yield await build_world(factory)
    unregister_package_plan_provider()


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


def _url(w: World, item_id: uuid.UUID | None = None, tail: str = "") -> str:
    return f"{BASE}/projects/{w.project_id}/items" + (f"/{item_id}{tail}" if item_id else "")


async def _can(c: AsyncClient, w: World, item_id: uuid.UUID) -> dict[str, dict[str, Any]]:
    answer = await c.get(_url(w, item_id))
    assert answer.status_code == 200, answer.text
    can = answer.json()["can"]
    assert set(can) == set(ACTIONS)
    return can


async def _write(c: AsyncClient, w: World, item_id: uuid.UUID, action: str) -> Response:
    """The request the button of ``action`` sends, with input that no typed-input rule can object to."""
    if action == "edit":
        return await c.patch(_url(w, item_id), json={"title": "Renamed on the screen"})
    if action == "edit_specification":
        return await c.patch(_url(w, item_id), json={"component_class_code": "lift"})
    if action == "edit_classification":
        return await c.patch(
            _url(w, item_id),
            json={"long_lead_override": True, "long_lead_override_reason": "Stated by the manufacturer in writing"},
        )
    if action == "set_route":
        return await c.put(
            _url(w, item_id, "/route"),
            json={"procurement_route": seed.ROUTE, "contract_package_id": str(w.supplier_pkg)},
        )
    if action == "handover":
        return await c.post(
            _url(w, item_id, "/handover"),
            json={"confirm": True, "no_asset_reason": "Maintained by the operator's own staff."},
        )
    return await c.post(_url(w, item_id, "/transition"), json={"target": action.removeprefix("transition_")})


def _well_formed(action: str, verdict: dict[str, Any]) -> None:
    assert isinstance(verdict["applies"], bool) and isinstance(verdict["allowed"], bool), (action, verdict)
    if verdict["allowed"]:
        assert verdict["applies"] and verdict["reason"] is None, (action, verdict)
        return
    assert verdict["reason"], (action, verdict)
    if verdict["reason"] == "transition_blocked":
        # Several rules stand in the way: each is named, with the key of its text.
        assert len(verdict["violations"]) >= 2, (action, verdict)
        assert all(v["code"] and v["message_key"] for v in verdict["violations"]), (action, verdict)


async def _agree(c: AsyncClient, w: World, item_id: uuid.UUID, action: str) -> dict[str, Any]:
    """Read the verdict for ``action``, send the write, and hold the answer against the verdict."""
    verdict = (await _can(c, w, item_id))[action]
    _well_formed(action, verdict)
    answer = await _write(c, w, item_id, action)
    if verdict["allowed"]:
        assert answer.status_code < 300, (action, verdict, answer.text)
    else:
        assert answer.status_code in (403, 404, 409, 422), (action, verdict, answer.text)
        assert answer.json()["detail"]["code"] == verdict["reason"], (action, verdict, answer.text)
    return verdict


async def _items(w: World, prefix: str, state: str) -> dict[str, uuid.UUID]:
    """One item per action in ``state``, since a write that is allowed changes the item it is tried on."""
    out: dict[str, uuid.UUID] = {}
    for n, action in enumerate(ACTIONS):
        out[action] = await _item_in(w, f"{prefix}-{n:02d}", state)
    return out


async def _item_in(w: World, code: str, state: str) -> uuid.UUID:
    """An item of a plain class taken to ``state`` by the service, the way a user would get it there."""
    item_id = await item(w, code, PLAIN_CLASS)
    if state == "identified":
        return item_id
    await quote(w, item_id, set_basis=True)
    async with w.factory() as s:
        svc = PlantService(s)
        for target in ("specified", "enquired"):
            await svc.transition_item(w.project_id, item_id, target, actor_id=w.area_owner, today=TODAY)
        if state == "route_set":
            await svc.set_route(
                w.project_id, item_id, route=seed.ROUTE, contract_package_id=w.supplier_pkg, actor_id=w.area_owner
            )
            await svc.put_limits(
                w.project_id, item_id, [{"step": k, "party": v} for k, v in seed._LIMITS.items()], actor_id=w.area_owner
            )
            await svc.transition_item(w.project_id, item_id, "route_set", actor_id=w.area_owner, today=TODAY)
        await s.commit()
    assert (await get(w, PlantItem, item_id)).status == state
    return item_id


@pytest.mark.parametrize("state", ["identified", "enquired", "route_set"])
@pytest.mark.parametrize("who", ["area_owner", "manager"])
async def test_every_verdict_is_what_the_write_answers(world: World, state: str, who: str) -> None:
    items = await _items(world, "AG", state)
    user, role = (world.area_owner, "editor") if who == "area_owner" else (world.manager, "manager")
    seen: dict[str, dict[str, Any]] = {}
    async with client_as(world, user, role) as c:
        for action, item_id in items.items():
            seen[action] = await _agree(c, world, item_id, action)

    # The facts a screen relies on, beyond the agreement itself.
    assert seen["edit"]["allowed"] is True
    assert (seen["handover"]["applies"], seen["handover"]["reason"]) == (False, "handover_needs_commissioned")
    assert (seen["transition_manufactured"]["applies"], seen["transition_manufactured"]["reason"]) == (
        False,
        "invalid_transition",
    )
    assert seen["transition_cancelled"]["allowed"] is True
    frozen = state == "route_set"
    assert seen["edit_specification"]["applies"] is not frozen
    if frozen:
        assert seen["edit_specification"]["reason"] == "specification_frozen"
    if who == "manager":
        assert seen["edit_classification"]["applies"] is not frozen
        assert seen["edit_classification"]["reason"] == ("classification_frozen" if frozen else None)
    else:
        # Without the right to manage, the caller reads that, in every state, exactly as the PATCH answers.
        assert (seen["edit_classification"]["applies"], seen["edit_classification"]["reason"]) == (
            True,
            "manage_required",
        )


async def test_a_step_that_a_rule_blocks_stays_on_the_screen_with_its_reason(world: World) -> None:
    bare = await item(world, "BL-01", PLAIN_CLASS)
    async with world.factory() as s:
        await PlantService(s).transition_item(
            world.project_id, bare, "specified", actor_id=world.area_owner, today=TODAY
        )
        await s.commit()
    async with client_as(world, world.area_owner, "editor") as c:
        verdict = await _agree(c, world, bare, "transition_enquired")
    # No basis quote yet: the step exists, the user can still satisfy the rule, so it is shown and refused.
    assert (verdict["applies"], verdict["allowed"], verdict["reason"]) == (True, False, "basis_quote_required")
    assert (await get(world, PlantItem, bare)).status == "specified"


async def test_an_editor_who_does_not_own_the_plant_area_reads_that_on_every_action_that_exists(world: World) -> None:
    items = await _items(world, "NO", "identified")
    async with client_as(world, world.area_owner, "editor") as c:
        owners = {a: (await _can(c, world, i))[a] for a, i in items.items()}
    async with client_as(world, world.editor, "editor") as c:
        for action, item_id in items.items():
            verdict = (await _can(c, world, item_id))[action]
            _well_formed(action, verdict)
            if not verdict["applies"]:
                # What does not exist in this state does not exist for anyone: same code as the owner reads.
                assert verdict["reason"] == owners[action]["reason"], action
                continue
            assert (verdict["allowed"], verdict["reason"]) == (False, "not_equipment_owner"), action
            answer = await _write(c, world, item_id, action)
            assert (answer.status_code, answer.json()["detail"]["code"]) == (403, "not_equipment_owner"), action
    # Nothing was written by the refused requests.
    assert {(await get(world, PlantItem, i)).status for i in items.values()} == {"identified"}


async def test_a_viewer_reads_the_missing_right_and_cannot_write(world: World) -> None:
    item_id = await item(world, "VW-01", PLAIN_CLASS)
    async with client_as(world, world.editor, "viewer") as c:
        can = await _can(c, world, item_id)
        answers = [(await _write(c, world, item_id, a)).status_code for a in ("edit", "transition_specified")]
    for action, verdict in can.items():
        _well_formed(action, verdict)
        if verdict["applies"]:
            assert (verdict["allowed"], verdict["reason"]) == (False, "edit_permission_required"), action
    assert answers == [403, 403]
    stored = await get(world, PlantItem, item_id)
    assert (stored.status, stored.title) == ("identified", "Item VW-01")


async def test_the_list_the_single_read_and_the_answer_of_a_write_carry_the_same_verdicts(world: World) -> None:
    first = await item(world, "SM-01", PLAIN_CLASS)
    second = await _item_in(world, "SM-02", "route_set")
    async with client_as(world, world.manager, "manager") as c:
        listed = await c.get(_url(world))
        assert listed.status_code == 200, listed.text
        by_id = {row["id"]: row["can"] for row in listed.json()["items"]}
        for item_id in (first, second):
            assert by_id[str(item_id)] == await _can(c, world, item_id)
        # The two items stand in different states, so the verdicts are per item, not per project.
        assert by_id[str(first)] != by_id[str(second)]
        written = await c.post(_url(world, first, "/transition"), json={"target": "specified"})
        assert written.status_code == 200, written.text
        # The answer of the write already shows the buttons of the new state.
        assert written.json()["can"] == await _can(c, world, first)
        assert written.json()["can"] != by_id[str(first)]
