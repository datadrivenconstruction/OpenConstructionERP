# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Allowed moves of the logistics plan against PostgreSQL, through the routes.

A ``can`` flag is only worth showing when the write behind it answers the same.
So every record here is walked through its states over HTTP, and at each stop
every flag that says no is tried for real: the route must refuse with the code
the flag carries. The flags that say yes are the steps of the walk itself.

The second test is the pickers: what a link field can point at is a row of this
project, and a stored link to a row of another project is refused by name.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.site_logistics import planning as pl
from app.modules.site_logistics.permissions import register_site_logistics_permissions
from app.modules.site_logistics.plan_service import LogisticsPlanService
from tests._pg import isolated_engine
from tests.pg.governance_fixtures import add_project
from tests.pg.site_logistics_fixtures import BASE, World, build_world, client_as, window

pytestmark = pytest.mark.asyncio

OK = {"allowed": True, "applies": True, "reason": None}


@pytest_asyncio.fixture
async def world():
    register_site_logistics_permissions()
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        yield await build_world(factory)


def _no(reason: str, applies: bool = True) -> dict[str, Any]:
    return {"allowed": False, "applies": applies, "reason": reason}


def _code(r: Response) -> str | None:
    """The code a route refused with; ``None`` when it did what was asked."""
    if r.status_code < 400:
        return None
    if r.status_code == 403:
        return "permission_denied"
    detail = r.json()["detail"]
    return detail["code"] if isinstance(detail, dict) else str(detail)


async def _made(r: Response) -> dict[str, Any]:
    assert r.status_code in (200, 201), r.text
    return r.json()


async def _listed(c: AsyncClient, url: str, rid: str) -> dict[str, Any]:
    page = await _made(await c.get(url))
    return next(i for i in page["items"] if i["id"] == rid)


async def _refusals_agree(c: AsyncClient, url: str, can: dict[str, Any]) -> int:
    """Try every action the flags refuse. Each must be refused with the flag's code; nothing changes."""
    tried = 0
    if "edit" in can and not can["edit"]["allowed"]:
        assert _code(await c.patch(url, json={})) == can["edit"]["reason"], (url, "edit")
        tried += 1
    if "delete" in can and not can["delete"]["allowed"]:
        assert _code(await c.delete(url)) == can["delete"]["reason"], (url, "delete")
        tried += 1
    for target, flag in can.get("transitions", {}).items():
        assert set(flag) == {"allowed", "applies", "reason"}
        if not flag["allowed"]:
            got = _code(await c.post(f"{url}/transition", json={"target": target}))
            assert got == flag["reason"], (url, target, flag)
            tried += 1
    return tried


async def _move(c: AsyncClient, url: str, can: dict[str, Any], target: str) -> dict[str, Any]:
    """Take a step the flags allow; the route must take it."""
    assert can["transitions"][target] == OK, (url, target, can["transitions"][target])
    body = await _made(await c.post(f"{url}/transition", json={"target": target}))
    assert body["state"] == target
    return body


async def test_every_flag_agrees_with_its_write(world: World) -> None:
    from app.modules.procurement.models import GoodsReceipt, PurchaseOrder

    pid = world.project_id
    root = f"{BASE}/projects/{pid}"
    start, end = window(1, 9, 1)
    async with world.factory() as s:
        po = PurchaseOrder(project_id=pid, po_number="PO-1")
        s.add(po)
        await s.commit()

    async with client_as(world, world.manager, "manager") as c, client_as(world, world.editor, "editor") as editor:
        # ── stages: the only stage stays, a stage in use stays ──────────────
        stages = await _made(await c.get(f"{root}/stages"))
        assert stages["can"] == {"create": OK}
        first = stages["items"][0]
        assert first["can"]["delete"] == _no("last_stage")
        assert await _refusals_agree(c, f"{root}/stages/{first['id']}", first["can"]) >= 2
        second = await _made(await c.post(f"{root}/stages", json={"code": "s2", "title": "Fit-out"}))
        assert second["can"]["delete"] == OK
        active = await _move(
            c, f"{root}/stages/{first['id']}", (await _listed(c, f"{root}/stages", first["id"]))["can"], "active"
        )
        assert active["can"]["delete"] == _no("stage_active")
        assert await _refusals_agree(c, f"{root}/stages/{first['id']}", active["can"]) >= 2
        assert (await c.delete(f"{root}/stages/{second['id']}")).status_code == 204

        # ── media: contracted only with a capacity ──────────────────────────
        media = await _made(await c.post(f"{root}/media", json={"media_kind": "power"}))
        url = f"{root}/media/{media['id']}"
        for target in ("requested", "offered"):
            assert await _refusals_agree(c, url, media["can"]) >= 3
            media = await _move(c, url, media["can"], target)
        assert media["can"]["transitions"]["contracted"] == _no("contracted_capacity_required")
        assert await _refusals_agree(c, url, media["can"]) >= 4
        media = await _made(await c.patch(url, json={"contracted_capacity": "250"}))
        media = await _move(c, url, media["can"], "contracted")

        # ── permit: validity before it is granted, frozen after ─────────────
        permit = await _made(
            await c.post(f"{root}/permits", json={"permit_kind": "oversize_permit", "reference": "OS-9"})
        )
        url = f"{root}/permits/{permit['id']}"
        assert permit["can"]["frozen_fields"] == [] and permit["can"]["delete"] == OK
        assert await _refusals_agree(c, url, permit["can"]) == len(pl.PERMIT_FSM) - 2
        permit = await _move(c, url, permit["can"], "applied")
        assert permit["can"]["transitions"]["granted"] == _no("validity_required")
        assert await _refusals_agree(c, url, permit["can"]) >= 3
        validity = {"valid_from": start.date().isoformat(), "valid_to": end.date().isoformat()}
        permit = await _made(await c.patch(url, json=validity))
        permit = await _move(c, url, permit["can"], "granted")
        assert permit["can"]["delete"] == _no("permit_frozen")
        assert "valid_to" in permit["can"]["frozen_fields"] and permit["can"]["edit"] == OK
        assert await _refusals_agree(c, url, permit["can"]) >= 4
        # A frozen field is refused with the code of the frozen record; the others still save.
        assert _code(await c.patch(url, json={"valid_to": "2031-01-01"})) == "permit_frozen"
        assert _code(await c.patch(url, json={"conditions": "Escort booked"})) is None
        assert (await _listed(c, f"{root}/permits", permit["id"]))["can"] == permit["can"]

        # ── transport: a manager moves it, the receipt lets it arrive ───────
        body = {
            "direction": "inbound",
            "transport_kind": "inbound_delivery",
            "title": "Facade elements",
            "po_id": str(po.id),
            "planned_window_start": start.isoformat(),
            "planned_window_end": end.isoformat(),
        }
        transport = await _made(await c.post(f"{root}/transports", json=body))
        url = f"{root}/transports/{transport['id']}"
        assert transport["can"]["edit"] == OK and transport["can"]["frozen_fields"] == []
        # The editor reads the same record: editing is theirs, the slot is the manager's.
        seen = await _made(await editor.get(url))
        assert seen["can"]["edit"] == OK
        assert seen["can"]["transitions"]["scheduled"] == _no("permission_denied")
        assert await _refusals_agree(editor, url, seen["can"]) >= len(pl.TRANSPORT_FSM) - 1
        assert (await _made(await editor.get(f"{root}/transports")))["can"] == {"create": OK}

        assert await _refusals_agree(c, url, transport["can"]) >= 3
        transport = await _move(c, url, transport["can"], "scheduled")
        transport = await _move(c, url, transport["can"], "in_transit")
        assert transport["can"]["delete"] == _no("transport_under_way")
        assert transport["can"]["transitions"]["arrived"] == _no("goods_receipt_missing")
        assert "gross_weight_t" in transport["can"]["frozen_fields"]
        assert "route_notes" not in transport["can"]["frozen_fields"]
        assert await _refusals_agree(c, url, transport["can"]) == len(pl.TRANSPORT_FSM)
        assert _code(await c.patch(url, json={"gross_weight_t": "12.5"})) == "transport_under_way"
        assert _code(await c.patch(url, json={"route_notes": "Via the ring road"})) is None
        async with world.factory() as s:
            today = await LogisticsPlanService(s).site_today(pid)
            s.add(GoodsReceipt(po_id=po.id, receipt_date=today.isoformat(), status="confirmed"))
            await s.commit()
        transport = await _made(await c.get(url))
        transport = await _move(c, url, transport["can"], "arrived")
        transport = await _move(c, url, transport["can"], "closed")
        assert transport["can"]["edit"] == _no("transport_closed")
        assert await _refusals_agree(c, url, transport["can"]) == len(pl.TRANSPORT_FSM) + 1
        page = await _made(await c.get(f"{root}/transports"))
        assert next(i for i in page["items"] if i["id"] == transport["id"])["can"] == transport["can"]

        # A transport the rules do not let on the road says which rule, before anybody tries.
        heavy_start, heavy_end = window(7, 10, 2)
        heavy = await _made(
            await c.post(
                f"{root}/transports",
                json={
                    "direction": "inbound",
                    "transport_kind": "heavy_oversize",
                    "title": "Transformer",
                    "gross_weight_t": "96",
                    "width_m": "3.6",
                    "planned_window_start": heavy_start.isoformat(),
                    "planned_window_end": heavy_end.isoformat(),
                },
            )
        )
        assert heavy["can"]["transitions"]["scheduled"] == _no("heavy_without_permit")
        assert await _refusals_agree(c, f"{root}/transports/{heavy['id']}", heavy["can"]) >= 4

        # ── customs: documents and lines before it is declared ──────────────
        case = await _made(
            await c.post(
                f"{root}/customs",
                json={"direction": "import", "title": "Switchgear", "incoterm": "FCA", "transport_mode": "road"},
            )
        )
        url = f"{root}/customs/{case['id']}"
        assert case["can"]["transitions"]["documents_complete"] == _no("required_document_missing")
        assert case["can"]["add_line"] == OK and case["can"]["add_document"] == OK
        assert await _refusals_agree(c, url, case["can"]) == len(pl.CUSTOMS_FSM) - 1
        line = await _made(await c.post(f"{url}/lines", json={"description": "Panel", "hs_code": "853710"}))
        assert line["can"] == {"edit": OK, "delete": OK}
        case = await _made(await c.get(url))
        documents = case["documents"]
        assert documents and all(d["can"]["edit"] == OK for d in documents)
        for d in documents:
            if d["required"]:
                assert d["can"]["transitions"]["received"] == OK
                received = await c.patch(
                    f"{root}/customs-documents/{d['id']}", json={"state": "received", "document_ref": "R-1"}
                )
                assert (await _made(received))["can"]["transitions"]["verified"] == OK
        case = await _made(await c.get(url))
        case = await _move(c, url, case["can"], "documents_complete")
        case = await _move(c, url, case["can"], "declared")
        assert case["can"]["delete"] == case["can"]["add_line"] == _no("customs_declared")
        assert case["can"]["add_document"] == _no("customs_declared")
        assert case["can"]["frozen_fields"] == ["direction", "incoterm", "transport_mode"]
        assert await _refusals_agree(c, url, case["can"]) >= 4
        assert _code(await c.patch(url, json={"incoterm": "DDP"})) == "customs_declared"
        assert _code(await c.post(f"{url}/lines", json={"hs_code": "853710"})) == "customs_declared"
        full = await _made(await c.get(url))
        for x in full["lines"]:
            assert x["can"] == {"edit": _no("customs_declared"), "delete": _no("customs_declared")}
            assert _code(await c.patch(f"{root}/customs-lines/{x['id']}", json={})) == "customs_declared"
            assert _code(await c.delete(f"{root}/customs-lines/{x['id']}")) == "customs_declared"
        for d in full["documents"]:
            assert d["can"]["edit"] == _no("customs_declared")
            assert (
                _code(await c.patch(f"{root}/customs-documents/{d['id']}", json={"state": "verified"}))
                == "customs_declared"
            )
        lines = await _made(await c.get(f"{url}/lines"))
        assert lines["can"] == {"create": _no("customs_declared")}
        # Held: customs asked for something, so documents move again, but nothing declared is taken back.
        case = await _move(c, url, case["can"], "held")
        assert case["can"]["add_document"] == OK and case["can"]["add_line"] == _no("customs_declared")
        held = (await _made(await c.get(url)))["documents"]
        required = next(d for d in held if d["required"])
        assert required["can"]["transitions"]["missing"] == _no("customs_declared")
        assert (
            _code(await c.patch(f"{root}/customs-documents/{required['id']}", json={"state": "missing"}))
            == "customs_declared"
        )
        assert required["can"]["transitions"]["verified"] == OK
        assert _code(await c.patch(f"{root}/customs-documents/{required['id']}", json={"state": "verified"})) is None
        case = await _move(c, url, case["can"], "cleared")
        assert case["can"]["edit"] == _no("customs_closed")
        assert await _refusals_agree(c, url, case["can"]) >= len(pl.CUSTOMS_FSM)
        assert (await _listed(c, f"{root}/customs", case["id"]))["can"] == case["can"]

        # ── complaint: a response before it closes, a record after ──────────
        issue = await _made(
            await c.post(f"{root}/neighbour-issues", json={"kind": "noise", "description": "Early pump"})
        )
        url = f"{root}/neighbour-issues/{issue['id']}"
        issue = await _move(c, url, issue["can"], "acknowledged")
        assert issue["can"]["transitions"]["closed"] == _no("response_required")
        assert await _refusals_agree(c, url, issue["can"]) == 3
        issue = await _made(await c.patch(url, json={"response": "Pump moved to nine o'clock."}))
        issue = await _move(c, url, issue["can"], "closed")
        assert issue["can"]["edit"] == _no("complaint_closed") and issue["can"]["delete"] == OK
        assert await _refusals_agree(c, url, issue["can"]) == len(pl.COMPLAINT_FSM)

        # ── what has no states still says who may write it ──────────────────
        concept = await _made(await c.get(f"{root}/concept"))
        assert concept["can"] == {"edit": OK, "pin_catalogue": OK}
        theirs = await _made(await editor.get(f"{root}/concept"))
        assert theirs["can"] == {"edit": OK, "pin_catalogue": _no("permission_denied")}
        pin = {"source": concept["catalogue_source"], "catalogue_id": concept["catalogue_id"]}
        assert _code(await editor.put(f"{root}/catalogue", json=pin)) == "permission_denied"
        assert (await _made(await c.get(f"{root}/neighbourhood")))["plan"]["can"] == {"edit": OK}
        assert (await _made(await c.get(f"{root}/areas")))["can"] == {"create": OK}
        assert (await _made(await c.get(f"{root}/coordination")))["can"] == {"create": OK}


async def test_pickers_offer_only_rows_of_the_project_and_links_are_checked(world: World) -> None:
    from app.modules.documents.models import Document
    from app.modules.procurement.models import PurchaseOrder

    pid = world.project_id
    root = f"{BASE}/projects/{pid}"
    async with world.factory() as s:
        other = await add_project(s, world.manager, [])
        mine = PurchaseOrder(project_id=pid, po_number="PO-MINE-7")
        theirs = PurchaseOrder(project_id=other, po_number="PO-THEIRS-7")
        plan = Document(project_id=pid, name="Site plan stage 1.png", mime_type="image/png")
        foreign = Document(project_id=other, name="Site plan of another site.png", mime_type="image/png")
        s.add_all([mine, theirs, plan, foreign])
        await s.commit()

    async with client_as(world, world.manager, "manager") as c, client_as(world, world.outsider, "manager") as out:
        orders = await _made(await c.get(f"{root}/link-options/purchase_order"))
        assert [(i["id"], i["label"]) for i in orders["items"]] == [(str(mine.id), "PO-MINE-7")]
        assert orders["total"] == 1
        # The search text is matched as written: a wildcard of the caller finds nothing by itself.
        assert (await _made(await c.get(f"{root}/link-options/purchase_order", params={"search": "mine"})))[
            "total"
        ] == 1
        assert (await _made(await c.get(f"{root}/link-options/purchase_order", params={"search": "%"})))["total"] == 0
        assert (await _made(await c.get(f"{root}/link-options/purchase_order", params={"search": "THEIRS"})))[
            "total"
        ] == 0
        docs = await _made(await c.get(f"{root}/link-options/document"))
        assert [(i["id"], i["label"], i["mime_type"]) for i in docs["items"]] == [
            (str(plan.id), "Site plan stage 1.png", "image/png")
        ]
        for kind in ("activity", "takt_schedule", "takt_location"):
            assert await _made(await c.get(f"{root}/link-options/{kind}")) == {"items": [], "total": 0}
        refused = await c.get(f"{root}/link-options/vendor")
        assert (refused.status_code, _code(refused)) == (422, "unknown_link_kind")
        assert (await out.get(f"{root}/link-options/purchase_order")).status_code in (403, 404)

        # A link stored on a record is checked against the project, whatever the picker offered.
        stage = (await _made(await c.get(f"{root}/stages")))["items"][0]
        url = f"{root}/stages/{stage['id']}"
        wrong = await c.patch(url, json={"plan_document_id": str(foreign.id)})
        assert (wrong.status_code, _code(wrong)) == (404, "plan_document_not_found")
        unknown = await c.patch(url, json={"plan_document_id": str(uuid.uuid4())})
        assert (unknown.status_code, _code(unknown)) == (404, "plan_document_not_found")
        loose = await c.patch(url, json={"plan_metres_per_pixel": "0.05"})
        assert (loose.status_code, _code(loose)) == (422, "plan_calibration_without_image")
        saved = await _made(
            await c.patch(
                url,
                json={
                    "plan_document_id": str(plan.id),
                    "plan_metres_per_pixel": "0.05",
                    "plan_origin_px": [120, 840.5],
                },
            )
        )
        assert (saved["plan_document_id"], saved["plan_origin_px"]) == (str(plan.id), [120.0, 840.5])
        assert Decimal(saved["plan_metres_per_pixel"]) == Decimal("0.05")
        start, end = window(2, 9, 1)
        body = {
            "direction": "inbound",
            "transport_kind": "inbound_delivery",
            "title": "Order of another project",
            "planned_window_start": start.isoformat(),
            "planned_window_end": end.isoformat(),
        }
        wrong = await c.post(f"{root}/transports", json={**body, "po_id": str(theirs.id)})
        assert (wrong.status_code, _code(wrong)) == (404, "po_not_found")
        assert (await c.post(f"{root}/transports", json={**body, "po_id": str(mine.id)})).status_code == 201


async def test_gates_zones_and_deliveries_carry_flags_that_agree_with_their_writes(world: World) -> None:
    pid = str(world.project_id)
    start, end = window(3, 9, 1)
    later, later_end = window(4, 9, 1)

    def booking(a, b, **extra) -> dict[str, Any]:
        return {
            "project_id": pid,
            "gate_id": gate["id"],
            "supplier_name": "Supplier",
            "window_start": a.isoformat(),
            "window_end": b.isoformat(),
            **extra,
        }

    async with client_as(world, world.manager, "manager") as c, client_as(world, world.editor, "editor") as editor:
        board = await _made(await c.get(f"{BASE}/can/", params={"project_id": pid}))
        assert board == {kind: {"create": OK} for kind in ("gate", "zone", "delivery")}
        assert await _made(await editor.get(f"{BASE}/can/", params={"project_id": pid})) == board

        gate = await _made(
            await c.post(f"{BASE}/gates/", json={"project_id": pid, "name": "North", "max_gross_t": "20"})
        )
        assert gate["can"] == {"edit": OK, "delete": OK}
        zone = await _made(await c.post(f"{BASE}/laydown-zones/", json={"project_id": pid, "name": "Laydown A"}))
        assert zone["can"] == {"edit": OK, "delete": OK}
        listed = await _made(await c.get(f"{BASE}/gates/", params={"project_id": pid}))
        assert [g["can"] for g in listed] == [gate["can"]]

        first = await _made(await c.post(f"{BASE}/deliveries/", json=booking(start, end)))
        rival = await _made(await c.post(f"{BASE}/deliveries/", json=booking(start, end)))
        heavy = await _made(await c.post(f"{BASE}/deliveries/", json=booking(later, later_end, gross_weight_t="40")))
        assert first["status"] == "requested"
        assert first["can"] == {"edit": OK, "delete": OK, "approve": OK, "reject": OK}

        # The load of the gate is known before anybody presses approve.
        assert heavy["can"]["approve"] == _no("gate_load_exceeded")
        refused = await c.post(f"{BASE}/deliveries/{heavy['id']}/approve/")
        assert refused.status_code == 400 and str(refused.json()["detail"]).startswith("gate_load_exceeded")

        # The editor books and edits; the slot is the manager's decision.
        seen = await _made(await editor.get(f"{BASE}/deliveries/{first['id']}"))
        assert seen["can"]["edit"] == OK
        assert seen["can"]["approve"] == seen["can"]["reject"] == _no("permission_denied")
        assert (await editor.post(f"{BASE}/deliveries/{first['id']}/approve/")).status_code == 403

        approved = await _made(await c.post(f"{BASE}/deliveries/{first['id']}/approve/"))
        assert approved["status"] == "approved"
        assert approved["can"]["approve"] == _no("invalid_transition", applies=False)
        assert approved["can"]["reject"] == OK

        # The window is taken now: the rival says so, and its approval is refused for that reason.
        rival = await _made(await c.get(f"{BASE}/deliveries/{rival['id']}"))
        assert rival["can"]["approve"] == _no("slot_taken")
        clash = await c.post(f"{BASE}/deliveries/{rival['id']}/approve/")
        assert clash.status_code == 400 and "clashes" in str(clash.json()["detail"])
        rejected = await _made(await c.post(f"{BASE}/deliveries/{rival['id']}/reject/"))
        assert rejected["can"]["reject"] == _no("invalid_transition", applies=False)
        # Rejecting the rival freed nothing it held; it is still refused while the first holds the slot.
        assert rejected["can"]["approve"] == _no("slot_taken")

        page = await _made(await c.get(f"{BASE}/deliveries/", params={"project_id": pid}))
        assert {d["id"]: d["can"] for d in page} == {
            first["id"]: approved["can"],
            rival["id"]: rejected["can"],
            heavy["id"]: heavy["can"],
        }
