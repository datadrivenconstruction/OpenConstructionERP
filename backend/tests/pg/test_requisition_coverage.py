# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""How much of each BOQ resource the requisitions hold, and whether a line adds up (issue #516).

Drives ``/api/v1/procurement/requisitions`` and the buy list over HTTP against
PostgreSQL. Pinned here:

* a draft reserves nothing; a submitted requisition does; withdrawing or
  cancelling gives the quantity back;
* two units are two figures and are never added;
* going over the BOQ demand is a warning the requester can answer with a
  reason, and never blocks the submission;
* a line whose quantity differs from its sources is refused on submit and only
  a warning while it is a draft.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from decimal import Decimal

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from tests.pg.test_a_requisition_is_approved_and_ordered_once import (  # noqa: F401 - world is a fixture
    BASE,
    REQ,
    World,
    world,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.tenant_isolation]

C30 = "0:C30"
RULE_OVER = "procurement.requisition_over_allocated"
RULE_SUM = "procurement.requisition_sources_reconcile"


@asynccontextmanager
async def client_as(w: World, user_id: uuid.UUID, role: str):
    from app.dependencies import get_current_user_id, get_current_user_payload, get_session
    from app.modules.procurement.router import router as procurement_router
    from app.modules.resource_summary.permissions import register_resource_summary_permissions
    from app.modules.resource_summary.router import router as summary_router

    register_resource_summary_permissions()
    app = FastAPI()
    app.include_router(procurement_router, prefix=BASE)
    app.include_router(summary_router, prefix="/api/v1/resource_summary")

    async def _session():
        async with w.factory() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_current_user_id] = lambda: str(user_id)
    app.dependency_overrides[get_current_user_payload] = lambda: {"sub": str(user_id), "role": role, "permissions": []}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://req-test") as c:
        yield c


async def _give_resources(w: World) -> None:
    """Concrete on both positions (51 and 20.4 m3 of demand) and rebar on the first (3.25 t)."""
    from app.modules.boq.models import Position

    async with w.factory() as s:
        first = await s.get(Position, w.positions[0])
        second = await s.get(Position, w.positions[1])
        first.metadata_ = {
            "resources": [
                {
                    "type": "material",
                    "name": "Concrete C30",
                    "code": "C30",
                    "unit": "m3",
                    "quantity": "1.02",
                    "unit_rate": "90",
                    "currency": "EUR",
                },
                {"type": "material", "name": "Rebar B500", "code": "B500", "unit": "t", "quantity": "0.065"},
            ]
        }
        second.metadata_ = {
            "resources": [{"type": "material", "name": "Concrete C30", "code": "C30", "unit": "m3", "quantity": "1.02"}]
        }
        await s.commit()


def _sources(w: World) -> list[dict]:
    return [
        {"boq_position_id": str(w.positions[0]), "resource_key": C30, "quantity": "51", "unit": "m3"},
        {"boq_position_id": str(w.positions[1]), "resource_key": C30, "quantity": "20.4", "unit": "m3"},
    ]


def _line(w: World, quantity: str, *, unit: str = "m3", sources: list[dict] | None = None, **extra: object) -> dict:
    return {
        "description": "Concrete C30",
        "unit": unit,
        "quantity_requested": quantity,
        "sources": sources
        if sources is not None
        else [{"boq_position_id": str(w.positions[0]), "resource_key": C30, "quantity": quantity, "unit": unit}],
        **extra,
    }


async def _create(c: AsyncClient, w: World, *lines: dict) -> dict:
    created = await c.post(f"{REQ}/", json={"project_id": str(w.project_id), "title": "Slab", "items": list(lines)})
    assert created.status_code == 201, created.text
    return created.json()


async def _coverage(c: AsyncClient, w: World) -> list[dict]:
    got = await c.get(f"{REQ}/coverage", params={"project_id": str(w.project_id)})
    assert got.status_code == 200, got.text
    return got.json()["sources"]


async def _buy_source(c: AsyncClient, w: World, position: uuid.UUID, key: str = C30) -> dict:
    got = await c.get(f"/api/v1/resource_summary/projects/{w.project_id}/buy-list")
    assert got.status_code == 200, got.text
    for item in got.json()["items"]:
        for source in item["sources"]:
            if source["position_id"] == str(position) and source["resource_key"] == key:
                return source
    raise AssertionError("source not on the buy list")


def _failed(report: dict, rule_id: str) -> list[dict]:
    return [r for r in report["results"] if r.get("rule_id") == rule_id and not r.get("passed")]


async def test_a_draft_reserves_nothing_and_a_submitted_requisition_does(world: World) -> None:
    await _give_resources(world)
    async with client_as(world, world.editor, "editor") as c:
        req = await _create(c, world, _line(world, "30"))
        assert await _coverage(c, world) == []
        before = await _buy_source(c, world, world.positions[0])
        assert Decimal(before["covered_quantity"]) == 0
        assert Decimal(before["remaining_quantity"]) == Decimal("51")

        assert (await c.post(f"{REQ}/{req['id']}/submit")).status_code == 200
        rows = await _coverage(c, world)
        assert [(r["resource_key"], r["unit"], Decimal(r["covered_quantity"])) for r in rows] == [(C30, "m3", 30)]
        after = await _buy_source(c, world, world.positions[0])
        assert Decimal(after["covered_quantity"]) == 30
        assert Decimal(after["remaining_quantity"]) == 21
        assert Decimal(after["unit_rate"]) == 90
        assert after["currency"] == "EUR"


async def test_withdrawing_and_cancelling_give_the_quantity_back(world: World) -> None:
    await _give_resources(world)
    async with client_as(world, world.editor, "editor") as c:
        req = await _create(c, world, _line(world, "30"))
        await c.post(f"{REQ}/{req['id']}/submit")
        assert len(await _coverage(c, world)) == 1
        assert (await c.post(f"{REQ}/{req['id']}/withdraw")).status_code == 200
        assert await _coverage(c, world) == []
        await c.post(f"{REQ}/{req['id']}/submit")
        assert len(await _coverage(c, world)) == 1
        assert (await c.post(f"{REQ}/{req['id']}/cancel", json={"reason": "No longer needed"})).status_code == 200
        assert await _coverage(c, world) == []
        assert Decimal((await _buy_source(c, world, world.positions[0]))["remaining_quantity"]) == 51


async def test_two_units_are_reported_apart_and_never_summed(world: World) -> None:
    await _give_resources(world)
    async with client_as(world, world.editor, "editor") as c:
        for quantity, unit in (("10", "m3"), ("4000", "kg")):
            req = await _create(c, world, _line(world, quantity, unit=unit))
            assert (await c.post(f"{REQ}/{req['id']}/submit")).status_code == 200
        rows = await _coverage(c, world)
        assert sorted((r["unit"], Decimal(r["covered_quantity"])) for r in rows) == [("kg", 4000), ("m3", 10)]
        source = await _buy_source(c, world, world.positions[0])
        assert Decimal(source["covered_quantity"]) == 10, "only the buy-list unit counts"


async def test_going_over_the_demand_warns_and_a_reason_answers_it(world: World) -> None:
    await _give_resources(world)
    async with client_as(world, world.editor, "editor") as c:
        first = await _create(c, world, _line(world, "45"))
        assert (await c.post(f"{REQ}/{first['id']}/submit")).status_code == 200

        plain = await _create(c, world, _line(world, "10"))
        submitted = await c.post(f"{REQ}/{plain['id']}/submit")
        assert submitted.status_code == 200, "an over-allocation never blocks the submission"
        warning = _failed((await c.get(f"{REQ}/{plain['id']}/validate")).json(), RULE_OVER)
        assert len(warning) == 1
        assert warning[0]["severity"] == "warning"
        assert Decimal((await _buy_source(c, world, world.positions[0]))["remaining_quantity"]) == -4

        reasoned = await _create(c, world, _line(world, "10", over_allocation_reason="Spare for the second pour"))
        assert reasoned["items"][0]["over_allocation_reason"] == "Spare for the second pour"
        assert (await c.post(f"{REQ}/{reasoned['id']}/submit")).status_code == 200
        assert _failed((await c.get(f"{REQ}/{reasoned['id']}/validate")).json(), RULE_OVER) == []


async def test_a_line_that_differs_from_its_sources_is_refused_on_submit_and_only_warned_on_a_draft(
    world: World,
) -> None:
    await _give_resources(world)
    async with client_as(world, world.editor, "editor") as c:
        req = await _create(c, world, _line(world, "70", sources=_sources(world)))
        draft = _failed((await c.get(f"{REQ}/{req['id']}/validate")).json(), RULE_SUM)
        assert [r["severity"] for r in draft] == ["warning"]

        refused = await c.post(f"{REQ}/{req['id']}/submit")
        assert refused.status_code == 422
        assert RULE_SUM in str(refused.json())
        assert await _coverage(c, world) == []

        fixed = await c.patch(f"{REQ}/{req['id']}", json={"items": [_line(world, "71.4", sources=_sources(world))]})
        assert fixed.status_code == 200, fixed.text
        assert (await c.post(f"{REQ}/{req['id']}/submit")).status_code == 200


async def test_an_outsider_cannot_read_the_coverage(world: World) -> None:
    async with client_as(world, world.outsider, "manager") as c:
        got = await c.get(f"{REQ}/coverage", params={"project_id": str(world.project_id)})
    assert got.status_code in (403, 404)
