# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Suggested suppliers travel from the BOQ to requisition lines, and each line has its own date (issue #516).

Drives ``/api/v1/boq/positions/{id}/suggested-supplier`` and
``/api/v1/procurement/requisitions`` over HTTP against PostgreSQL, reusing the
world of the approval test: a manager, two editors, an outsider, a bill with two
positions and three suppliers (active, blacklisted, active).

What is pinned here:

* a suggestion is set on a position or on one material resource, must be in the
  Vendor directory, and leaves quantity, rate and total alone;
* a requisition line inherits the suggestion its BOQ sources agree on; sources
  that disagree leave the line empty and stay visible; the requisition's own
  supplier is never filled in from a suggestion; the requester overrides or
  clears it;
* a line's date is proposed from a schedule activity minus a buffer, a moved
  activity is reported but never rewrites the date, an activity of another
  project is refused;
* the requisition reports its latest ordering date and has no delivery
  forecast until it is ordered, then shows the order's date, and the order's
  dates appear beside each line;
* the outsider reaches none of it.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import date, timedelta

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from tests.pg.test_a_requisition_is_approved_and_ordered_once import (  # noqa: F401 - world is a fixture
    REQ,
    World,
    world,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.tenant_isolation]

BOQ = "/api/v1/boq"


@asynccontextmanager
async def client_as(w: World, user_id: uuid.UUID, role: str):
    from app.dependencies import get_current_user_id, get_current_user_payload, get_session
    from app.modules.boq.permissions import register_boq_permissions
    from app.modules.boq.router import router as boq_router
    from app.modules.procurement.router import router as procurement_router

    register_boq_permissions()
    app = FastAPI()
    app.include_router(procurement_router, prefix="/api/v1/procurement")
    app.include_router(boq_router, prefix=BOQ)

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
    """Two concrete resources on position 1.1 and one on 1.2, no suggestions yet."""
    from app.modules.boq.models import Position

    async with w.factory() as s:
        first = await s.get(Position, w.positions[0])
        second = await s.get(Position, w.positions[1])
        first.metadata_ = {
            "resources": [
                {"type": "material", "name": "Concrete C30", "code": "C30", "unit": "m3", "quantity": "1.02"},
                {"type": "material", "name": "Rebar B500", "code": "B500", "unit": "t", "quantity": "0.065"},
                {"type": "labor", "name": "Mason", "unit": "h", "quantity": "2"},
            ]
        }
        second.metadata_ = {
            "resources": [{"type": "material", "name": "Concrete C30", "code": "C30", "unit": "m3", "quantity": "1.02"}]
        }
        await s.commit()


async def _schedule(w: World, project_id: uuid.UUID, start: str) -> uuid.UUID:
    from app.modules.schedule.models import Activity, Schedule

    async with w.factory() as s:
        schedule = Schedule(project_id=project_id, name="Master", description="")
        s.add(schedule)
        await s.flush()
        activity = Activity(schedule_id=schedule.id, name="Pour slab", description="", start_date=start, end_date=start)
        s.add(activity)
        await s.commit()
        return activity.id


def _line(w: World) -> dict:
    return {
        "description": "Concrete C30",
        "unit": "m3",
        "quantity_requested": "71.4",
        "unit_cost": "95.50",
        "currency_code": "EUR",
        "sources": [
            {"boq_position_id": str(w.positions[0]), "resource_key": "0:C30", "quantity": "51", "unit": "m3"},
            {"boq_position_id": str(w.positions[1]), "resource_key": "0:C30", "quantity": "20.4", "unit": "m3"},
        ],
    }


def _create_body(w: World, *lines: dict, **header: object) -> dict:
    body: dict = {"project_id": str(w.project_id), "title": "Slab", "items": list(lines)}
    body.update(header)
    return body


# ── BOQ suggestion ──────────────────────────────────────────────────────────


async def test_a_suggestion_is_set_on_the_bill_and_leaves_the_prices_alone(world: World) -> None:
    from app.modules.boq.models import Position

    await _give_resources(world)
    async with world.factory() as s:
        before = await s.get(Position, world.positions[0])
        priced = (before.quantity, before.unit_rate, before.total)
    url = f"{BOQ}/positions/{world.positions[0]}/suggested-supplier"
    async with client_as(world, world.editor, "editor") as c:
        default = await c.put(url, json={"vendor_id": str(world.vendor_active)})
        own = await c.put(url, json={"vendor_id": str(world.vendor_other), "resource_key": "1:B500"})
        unknown = await c.put(url, json={"vendor_id": str(uuid.uuid4())})
        labour = await c.put(url, json={"vendor_id": str(world.vendor_other), "resource_key": "2"})
        read = await c.get(url)

    assert default.status_code == 200, default.text
    assert own.status_code == 200, own.text
    assert unknown.status_code == 422
    assert labour.status_code == 404, "only material resources take a supplier"
    body = read.json()
    assert body["default_vendor_name"] == "Beton Nord"
    by_key = {r["resource_key"]: r for r in body["resources"]}
    assert set(by_key) == {"0:C30", "1:B500"}
    assert (by_key["0:C30"]["effective_vendor_name"], by_key["0:C30"]["origin"]) == ("Beton Nord", "position")
    assert (by_key["1:B500"]["effective_vendor_name"], by_key["1:B500"]["origin"]) == ("Kies Sued", "resource")
    async with world.factory() as s:
        after = await s.get(Position, world.positions[0])
        assert (after.quantity, after.unit_rate, after.total) == priced
        assert [r.get("quantity") for r in after.metadata_["resources"]] == ["1.02", "0.065", "2"]


async def test_the_outsider_cannot_read_or_set_a_suggestion(world: World) -> None:
    await _give_resources(world)
    url = f"{BOQ}/positions/{world.positions[0]}/suggested-supplier"
    async with client_as(world, world.outsider, "manager") as c:
        answers = [
            await c.get(url),
            await c.put(url, json={"vendor_id": str(world.vendor_active)}),
            await c.get(f"{REQ}/schedule-activities", params={"project_id": str(world.project_id)}),
        ]
    assert [r.status_code for r in answers] == [404, 404, 404]


# ── Requisition lines ───────────────────────────────────────────────────────


async def test_agreeing_sources_give_the_line_its_suggestion_and_nothing_chooses_the_supplier(world: World) -> None:
    await _give_resources(world)
    async with client_as(world, world.editor, "editor") as c:
        for pos in world.positions:
            await c.put(f"{BOQ}/positions/{pos}/suggested-supplier", json={"vendor_id": str(world.vendor_active)})
        created = await c.post(f"{REQ}/", json=_create_body(world, _line(world)))

    assert created.status_code == 201, created.text
    req = created.json()
    [line] = req["items"]
    assert line["suggested_vendor_name"] == "Beton Nord"
    assert line["suggestion_conflict"] is False
    assert [s["suggested_vendor_name"] for s in line["sources"]] == ["Beton Nord", "Beton Nord"]
    assert [v["name"] for v in req["suggested_vendors"]] == ["Beton Nord"]
    assert req["vendor_id"] is None, "a suggestion never becomes the supplier by itself"


async def test_disagreeing_sources_stay_visible_and_the_requester_decides(world: World) -> None:
    await _give_resources(world)
    async with client_as(world, world.editor, "editor") as c:
        await c.put(
            f"{BOQ}/positions/{world.positions[0]}/suggested-supplier", json={"vendor_id": str(world.vendor_active)}
        )
        await c.put(
            f"{BOQ}/positions/{world.positions[1]}/suggested-supplier", json={"vendor_id": str(world.vendor_other)}
        )
        created = (await c.post(f"{REQ}/", json=_create_body(world, _line(world)))).json()
        report = (await c.get(f"{REQ}/{created['id']}/validate")).json()

        [line] = created["items"]
        assert line["suggested_vendor_id"] is None
        assert line["suggestion_conflict"] is True
        assert {v["name"] for v in line["source_suggested_vendors"]} == {"Beton Nord", "Kies Sued"}
        conflict = [r for r in report["results"] if r["rule_id"] == "procurement.requisition_suggestion_conflict"]
        assert [r["passed"] for r in conflict] == [False]

        # The editor picks one; the sources keep what the bill suggested.
        chosen = {**_line(world), "suggested_vendor_id": str(world.vendor_other)}
        chosen["sources"] = [
            {**src, "suggested_vendor_id": s["suggested_vendor_id"]}
            for src, s in zip(chosen["sources"], line["sources"], strict=True)
        ]
        picked = await c.patch(f"{REQ}/{created['id']}", json={"items": [chosen]})
        cleared = await c.patch(f"{REQ}/{created['id']}", json={"items": [{**chosen, "suggested_vendor_id": None}]})
        unknown = await c.patch(
            f"{REQ}/{created['id']}", json={"items": [{**chosen, "suggested_vendor_id": str(uuid.uuid4())}]}
        )

    assert picked.status_code == 200, picked.text
    assert picked.json()["items"][0]["suggested_vendor_name"] == "Kies Sued"
    assert picked.json()["items"][0]["suggestion_conflict"] is True, "the disagreement is still shown"
    assert cleared.json()["items"][0]["suggested_vendor_id"] is None
    assert unknown.status_code == 422


async def test_a_blacklisted_suggestion_warns_and_a_differing_one_is_shown_at_approval(world: World) -> None:
    await _give_resources(world)
    line = {**_line(world), "suggested_vendor_id": str(world.vendor_blacklisted)}
    async with client_as(world, world.editor, "editor") as c:
        created = (await c.post(f"{REQ}/", json=_create_body(world, line, vendor_id=str(world.vendor_active)))).json()
        report = (await c.get(f"{REQ}/{created['id']}/validate")).json()
    failed = {r["rule_id"]: r["severity"] for r in report["results"] if not r["passed"]}
    assert failed.get("procurement.requisition_suggested_vendor_active") == "warning"
    assert failed.get("procurement.requisition_suggested_vendor_differs") == "warning"


# ── Dates ───────────────────────────────────────────────────────────────────


async def test_a_line_date_comes_from_the_schedule_and_a_moved_activity_is_reported(world: World) -> None:
    from app.modules.schedule.models import Activity

    start = (date.today() + timedelta(days=40)).isoformat()
    activity_id = await _schedule(world, world.project_id, start)
    line = {**_line(world), "schedule_activity_id": str(activity_id), "schedule_buffer_days": 5}
    async with client_as(world, world.editor, "editor") as c:
        options = (await c.get(f"{REQ}/schedule-activities", params={"project_id": str(world.project_id)})).json()
        created = (await c.post(f"{REQ}/", json=_create_body(world, line))).json()

    assert [o["name"] for o in options["items"]] == ["Pour slab"]
    assert (options["total"], options["offset"]) == (1, 0)
    [item] = created["items"]
    proposed = (date.fromisoformat(start) - timedelta(days=5)).isoformat()
    assert (item["required_date"], item["required_date_source"], item["schedule_anchor_date"]) == (
        proposed,
        "schedule",
        start,
    )
    assert item["schedule_moved"] is False

    moved = (date.fromisoformat(start) + timedelta(days=7)).isoformat()
    async with world.factory() as s:
        (await s.get(Activity, activity_id)).start_date = moved
        await s.commit()
    async with client_as(world, world.editor, "editor") as c:
        again = (await c.get(f"{REQ}/{created['id']}")).json()
        # Saving the draft again echoes the anchor and must not re-anchor it.
        echoed = {**line, "required_date": proposed, "schedule_anchor_date": start}
        saved = (await c.patch(f"{REQ}/{created['id']}", json={"items": [echoed]})).json()
        report = (await c.get(f"{REQ}/{created['id']}/validate")).json()

    [item] = again["items"]
    assert item["required_date"] == proposed, "a schedule change never rewrites the agreed date"
    assert (item["schedule_activity_start"], item["schedule_moved"]) == (moved, True)
    assert saved["items"][0]["schedule_anchor_date"] == start
    moved_rule = [r for r in report["results"] if r["rule_id"] == "procurement.requisition_line_schedule_moved"]
    assert [r["passed"] for r in moved_rule] == [False]


async def test_an_activity_of_another_project_is_refused(world: World) -> None:
    from app.modules.projects.models import Project

    other = uuid.uuid4()
    async with world.factory() as s:
        s.add(
            Project(id=other, name="Elsewhere", currency="EUR", status="active", owner_id=world.outsider, metadata_={})
        )
        await s.commit()
    foreign = await _schedule(world, other, (date.today() + timedelta(days=10)).isoformat())
    line = {**_line(world), "schedule_activity_id": str(foreign)}
    async with client_as(world, world.editor, "editor") as c:
        refused = await c.post(f"{REQ}/", json=_create_body(world, line))
    assert refused.status_code == 422


async def test_the_header_date_is_the_default_and_the_forecast_waits_for_the_order(world: World) -> None:
    needed = date.today() + timedelta(days=30)
    plain = _line(world)
    own = {
        **_line(world),
        "description": "Concrete C30 for the lift pit",
        "required_date": (needed - timedelta(days=9)).isoformat(),
    }
    body = _create_body(
        world, plain, own, required_date=needed.isoformat(), lead_time_days=14, vendor_id=str(world.vendor_active)
    )
    async with client_as(world, world.editor, "editor") as c:
        created = (await c.post(f"{REQ}/", json=body)).json()
        await c.post(f"{REQ}/{created['id']}/submit")
    async with client_as(world, world.manager, "manager") as c:
        await c.post(f"{REQ}/{created['id']}/approve", json={})
        delivery = (needed - timedelta(days=2)).isoformat()
        converted = await c.post(
            f"{REQ}/convert-to-po",
            json={"project_id": str(world.project_id), "requisition_ids": [created["id"]], "delivery_date": delivery},
        )
        ordered = (await c.get(f"{REQ}/{created['id']}")).json()

    assert created["estimated_delivery_date"] is None, "no forecast before an order exists"
    assert created["latest_order_date"] == (needed - timedelta(days=14)).isoformat()
    first, second = created["items"]
    assert (first["effective_required_date"], first["required_date_source"]) == (needed.isoformat(), "requisition")
    assert (second["effective_required_date"], second["required_date_source"]) == (own["required_date"], "line")
    assert second["latest_order_date"] == (needed - timedelta(days=23)).isoformat()

    assert converted.status_code == 201, converted.text
    assert ordered["estimated_delivery_date"] == delivery
    assert ordered["items"][0]["po_items"][0]["po_delivery_date"] == delivery
    assert ordered["items"][0]["effective_required_date"] == needed.isoformat(), (
        "the need stays apart from the supplier's date"
    )


async def test_the_boot_repair_replaces_the_stored_ordering_deadline(world: World) -> None:
    """An install that heals at boot never runs v90's data half; the registered repair does it instead."""
    from sqlalchemy import update

    from app.modules.procurement.models import MaterialRequisition
    from app.modules.procurement.repairs import PROCUREMENT_REQUISITION_DELIVERY_DATE

    needed = date.today() + timedelta(days=30)
    delivery = (needed - timedelta(days=3)).isoformat()
    async with client_as(world, world.editor, "editor") as c:
        draft = (
            await c.post(f"{REQ}/", json=_create_body(world, _line(world), required_date=needed.isoformat()))
        ).json()
        ordered = (
            await c.post(
                f"{REQ}/",
                json=_create_body(
                    world, _line(world), required_date=needed.isoformat(), vendor_id=str(world.vendor_active)
                ),
            )
        ).json()
        await c.post(f"{REQ}/{ordered['id']}/submit")
    async with client_as(world, world.manager, "manager") as c:
        await c.post(f"{REQ}/{ordered['id']}/approve", json={})
        converted = await c.post(
            f"{REQ}/convert-to-po",
            json={"project_id": str(world.project_id), "requisition_ids": [ordered["id"]], "delivery_date": delivery},
        )
    assert converted.status_code == 201, converted.text

    stale = (needed - timedelta(days=14)).isoformat()
    async with world.factory() as s:
        await s.execute(
            update(MaterialRequisition)
            .where(MaterialRequisition.id.in_([uuid.UUID(draft["id"]), uuid.UUID(ordered["id"])]))
            .values(estimated_delivery_date=stale)
        )
        await s.commit()

    async with world.factory() as s:
        changed = await PROCUREMENT_REQUISITION_DELIVERY_DATE.run(s)
        await s.commit()
    async with world.factory() as s:
        again = await PROCUREMENT_REQUISITION_DELIVERY_DATE.run(s)
        await s.commit()
        rows = {
            str(r.id): r.estimated_delivery_date
            for r in (
                await s.execute(
                    MaterialRequisition.__table__.select().where(
                        MaterialRequisition.id.in_([uuid.UUID(draft["id"]), uuid.UUID(ordered["id"])])
                    )
                )
            ).all()
        }

    assert changed >= 2
    assert again == 0, "the repair is idempotent: a corrected database reports nothing to do"
    assert rows[draft["id"]] is None, "no order, no delivery date"
    assert rows[ordered["id"]] == delivery, "the order's delivery date replaces the ordering deadline"


async def test_moving_the_order_date_moves_the_requisition_forecast_at_once(world: World) -> None:
    needed = date.today() + timedelta(days=30)
    body = _create_body(world, _line(world), required_date=needed.isoformat(), vendor_id=str(world.vendor_active))
    async with client_as(world, world.editor, "editor") as c:
        created = (await c.post(f"{REQ}/", json=body)).json()
        await c.post(f"{REQ}/{created['id']}/submit")
    async with client_as(world, world.manager, "manager") as c:
        await c.post(f"{REQ}/{created['id']}/approve", json={})
        converted = await c.post(
            f"{REQ}/convert-to-po",
            json={
                "project_id": str(world.project_id),
                "requisition_ids": [created["id"]],
                "delivery_date": (needed - timedelta(days=2)).isoformat(),
            },
        )
        assert converted.status_code == 201, converted.text
        moved = (needed + timedelta(days=5)).isoformat()
        patched = await c.patch(f"/api/v1/procurement/{converted.json()['po_id']}", json={"delivery_date": moved})
        assert patched.status_code == 200, patched.text
        ordered = (await c.get(f"{REQ}/{created['id']}")).json()

    assert ordered["estimated_delivery_date"] == moved, "the forecast follows the order without waiting for a boot"
