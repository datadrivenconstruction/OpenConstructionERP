# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Requisitions: designated approvers, line-level ordering, external orders and the feed (issue #516).

Drives ``/api/v1/procurement/requisitions`` over HTTP against PostgreSQL with
the world of ``test_a_requisition_is_approved_and_ordered_once``: a manager, two
editors, an outsider, a bill on the cost spine and three suppliers.

What is pinned here:

* designated approvers decide in their order; every approval but the last is an
  intermediate step that leaves the requisition ``submitted``; nobody else, and
  never the requester, decides; a repeat is a no-op;
* a line can be ordered in parts over several orders, several requisitions can
  share one order, and requested, ordered, received and outstanding follow the
  order lines and confirmed receipts, restated in the line's unit; cancelling
  one order gives back only what it held; a retried conversion is one order;
* with the project ordering in an external system nothing is converted here,
  the external lines reconcile without a purchase order, and a repeated report
  records nothing;
* every change lands in a replayable feed whose cursor never skips;
* every new route refuses a caller outside the project.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from tests.pg.test_a_requisition_is_approved_and_ordered_once import (  # noqa: F401 - the fixture is used by name
    BASE,
    REQ,
    World,
    _approved,
    _body,
    _submitted,
    _user,
    client_as,
    world,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.tenant_isolation]


async def _member_manager(w: World) -> uuid.UUID:
    """A second manager who belongs to the project's team."""
    from app.modules.teams.models import Team, TeamMembership

    async with w.factory() as s:
        uid = await _user(s, "manager")
        team = (await s.execute(select(Team).where(Team.project_id == w.project_id))).scalars().first()
        s.add(TeamMembership(team_id=team.id, user_id=uid))
        await s.commit()
    return uid


async def _po_count(w: World) -> int:
    from app.modules.procurement.models import PurchaseOrder

    async with w.factory() as s:
        return int(
            (
                await s.execute(
                    select(func.count()).select_from(PurchaseOrder).where(PurchaseOrder.project_id == w.project_id)
                )
            ).scalar_one()
        )


def _line(req: dict, description: str) -> dict:
    return next(i for i in req["items"] if i["description"] == description)


def D(value: str) -> Decimal:
    """Quantities are compared as numbers; their scale follows the stored request."""
    return Decimal(value)


# ── Designated approvers ────────────────────────────────────────────────────


async def test_designated_approvers_decide_in_their_order(world: World) -> None:
    second = await _member_manager(world)
    chain = [str(world.manager), str(second)]
    async with client_as(world, world.editor, "editor") as c:
        created = await c.post(f"{REQ}/", json={**_body(world), "approval_chain": chain})
        assert created.status_code == 201, created.text
        submitted = (await c.post(f"{REQ}/{created.json()['id']}/submit")).json()
    rid = submitted["id"]
    assert submitted["status"] == "submitted"
    assert [s["state"] for s in submitted["approval_chain"]] == ["next", "waiting"]
    assert submitted["next_approver_id"] == str(world.manager)

    async with client_as(world, second, "manager") as c:
        out_of_turn = await c.post(f"{REQ}/{rid}/approve", json={})
        reject_out_of_turn = await c.post(f"{REQ}/{rid}/reject", json={"comment": "No"})
    assert out_of_turn.status_code == 403
    assert reject_out_of_turn.status_code == 403

    async with client_as(world, world.manager, "manager") as c:
        step = await c.post(f"{REQ}/{rid}/approve", json={"comment": "Budget fine"})
        repeat = await c.post(f"{REQ}/{rid}/approve", json={})
    body = step.json()
    assert step.status_code == 200, step.text
    assert body["status"] == "submitted", "an intermediate approval is not the approval"
    assert body["approval_step"] == 1
    assert [s["state"] for s in body["approval_chain"]] == ["approved", "next"]
    assert body["approval_chain"][0]["comment"] == "Budget fine"
    assert body["approval_chain"][0]["name"] == "Req manager"
    assert body["approver_id"] is None
    assert repeat.status_code == 200 and repeat.json()["approval_step"] == 1
    steps = [d for name, d in world.events if name == "procurement.requisition.approval_step"]
    assert len(steps) == 1 and steps[0]["final"] is False

    async with client_as(world, second, "manager") as c:
        final = await c.post(f"{REQ}/{rid}/approve", json={})
    assert final.json()["status"] == "approved"
    assert final.json()["approver_id"] == str(second)
    assert [s["state"] for s in final.json()["approval_chain"]] == ["approved", "approved"]
    actions = [h["action"] for h in final.json()["history"]]
    assert actions == ["created", "submitted", "approval_step", "approved"]


async def test_an_approver_who_cannot_approve_is_refused_when_named(world: World) -> None:
    async with client_as(world, world.editor, "editor") as c:
        editor_named = await c.post(f"{REQ}/", json={**_body(world), "approval_chain": [str(world.second_editor)]})
        outsider_named = await c.post(f"{REQ}/", json={**_body(world), "approval_chain": [str(world.outsider)]})
        twice = await c.post(
            f"{REQ}/", json={**_body(world), "approval_chain": [str(world.manager), str(world.manager)]}
        )
    assert editor_named.status_code == 422, "an editor holds no approval permission"
    assert outsider_named.status_code == 422, "the outsider cannot open the project"
    assert twice.status_code == 422


async def test_a_designated_approver_cannot_submit_it_or_be_the_requester(world: World) -> None:
    async with client_as(world, world.manager, "manager") as c:
        created = await c.post(f"{REQ}/", json={**_body(world), "approval_chain": [str(world.manager)]})
        validated = await c.get(f"{REQ}/{created.json()['id']}/validate")
        refused = await c.post(f"{REQ}/{created.json()['id']}/submit")
    assert created.status_code == 201, created.text
    rule = [r for r in validated.json()["results"] if r["rule_id"] == "procurement.requisition_approver_not_requester"]
    assert [r["passed"] for r in rule] == [False]
    assert refused.status_code == 422


async def test_without_designated_approvers_one_approval_is_final(world: World) -> None:
    approved = await _approved(world)
    assert approved["status"] == "approved"
    assert approved["approval_chain"] == []
    assert approved["next_approver_id"] is None


async def test_the_project_default_approvers_land_on_new_requisitions(world: World) -> None:
    second = await _member_manager(world)
    async with client_as(world, world.editor, "editor") as c:
        by_editor = await c.put(
            f"{REQ}/settings",
            params={"project_id": str(world.project_id)},
            json={"default_approval_chain": [str(second)]},
        )
    async with client_as(world, world.manager, "manager") as c:
        saved = await c.put(
            f"{REQ}/settings",
            params={"project_id": str(world.project_id)},
            json={"default_approval_chain": [str(second)]},
        )
    assert by_editor.status_code == 403
    assert saved.status_code == 200, saved.text
    assert [a["user_id"] for a in saved.json()["default_approvers"]] == [str(second)]
    async with client_as(world, world.editor, "editor") as c:
        created = (await c.post(f"{REQ}/", json=_body(world))).json()
        explicit = (await c.post(f"{REQ}/", json={**_body(world), "approval_chain": []})).json()
    assert [a["user_id"] for a in created["approval_chain"]] == [str(second)]
    assert explicit["approval_chain"] == []


# ── Line-level ordering ─────────────────────────────────────────────────────


def _convert(w: World, ids: list[str], **extra) -> dict:
    return {"project_id": str(w.project_id), "requisition_ids": ids, **extra}


async def test_a_line_is_ordered_in_parts_over_two_orders(world: World) -> None:
    req = await _approved(world, vendor=world.vendor_active)
    concrete = _line(req, "Concrete C30/37")
    async with client_as(world, world.editor, "editor") as c:
        first = await c.post(
            f"{REQ}/convert-to-po",
            json=_convert(world, [req["id"]], lines=[{"requisition_item_id": concrete["id"], "quantity": "30"}]),
        )
        assert first.status_code == 201, first.text
        partial = (await c.get(f"{REQ}/{req['id']}")).json()
        too_much = await c.post(
            f"{REQ}/convert-to-po",
            json=_convert(world, [req["id"]], lines=[{"requisition_item_id": concrete["id"], "quantity": "41.5"}]),
        )
        rest = await c.post(f"{REQ}/convert-to-po", json=_convert(world, [req["id"]]))
        assert rest.status_code == 201, rest.text
        full = (await c.get(f"{REQ}/{req['id']}")).json()
        again = await c.post(f"{REQ}/convert-to-po", json=_convert(world, [req["id"]]))
        second_po = (await c.get(f"{BASE}/{rest.json()['po_id']}")).json()

    assert first.json()["line_count"] == 1
    assert first.json()["fully_ordered_requisition_ids"] == []
    assert partial["status"] == "approved", "quantity is left to order, so it can be ordered further"
    assert partial["order_progress"] == "partial"
    assert D(_line(partial, "Concrete C30/37")["quantity_ordered"]) == D("30")
    assert D(_line(partial, "Concrete C30/37")["quantity_to_order"]) == D("41.4")
    assert D(_line(partial, "Rebar B500")["quantity_to_order"]) == D("3.25")
    assert too_much.status_code == 409
    assert too_much.json()["detail"]["code"] == "quantity_exceeds_remaining"
    assert sorted((i["description"], D(i["quantity"])) for i in second_po["items"]) == [
        ("Concrete C30/37", D("41.4")),
        ("Rebar B500", D("3.25")),
    ]
    assert full["status"] == "ordered"
    assert full["order_progress"] == "full"
    assert [p["po_id"] for p in full["purchase_orders"]] == [first.json()["po_id"], rest.json()["po_id"]]
    assert [D(p["quantity"]) for p in _line(full, "Concrete C30/37")["po_items"]] == [D("30"), D("41.4")]
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "requisition_already_ordered"
    assert [h["action"] for h in full["history"]][-2:] == ["partially_ordered", "ordered"]


async def test_two_requisitions_share_one_order_with_their_own_quantities(world: World) -> None:
    walls = await _approved(world, vendor=world.vendor_active, title="Walls")
    slab = await _approved(world, vendor=world.vendor_active, title="Slab")
    async with client_as(world, world.editor, "editor") as c:
        converted = await c.post(
            f"{REQ}/convert-to-po",
            json=_convert(
                world,
                [walls["id"], slab["id"]],
                lines=[
                    {"requisition_item_id": _line(walls, "Concrete C30/37")["id"], "quantity": "10"},
                    {"requisition_item_id": _line(slab, "Concrete C30/37")["id"], "quantity": "20"},
                ],
            ),
        )
        assert converted.status_code == 201, converted.text
        po = (await c.get(f"{BASE}/{converted.json()['po_id']}")).json()
        after = {rid: (await c.get(f"{REQ}/{rid}")).json() for rid in (walls["id"], slab["id"])}

    assert len(po["items"]) == 2, "lines of two requisitions are never merged into one order line"
    assert {i["requisition_item_id"]: D(i["quantity"]) for i in po["items"]} == {
        _line(walls, "Concrete C30/37")["id"]: D("10"),
        _line(slab, "Concrete C30/37")["id"]: D("20"),
    }
    assert D(_line(after[walls["id"]], "Concrete C30/37")["quantity_ordered"]) == D("10")
    assert D(_line(after[slab["id"]], "Concrete C30/37")["quantity_ordered"]) == D("20")
    assert D(after[walls["id"]]["reconciliation"]["to_order"]) == D("71.4") - 10 + D("3.25")


async def test_a_line_must_belong_to_the_requisitions_converted(world: World) -> None:
    walls = await _approved(world, vendor=world.vendor_active, title="Walls")
    slab = await _approved(world, vendor=world.vendor_active, title="Slab")
    async with client_as(world, world.editor, "editor") as c:
        foreign = await c.post(
            f"{REQ}/convert-to-po",
            json=_convert(
                world, [walls["id"]], lines=[{"requisition_item_id": slab["items"][0]["id"], "quantity": "1"}]
            ),
        )
        zero = await c.post(
            f"{REQ}/convert-to-po",
            json=_convert(
                world, [walls["id"]], lines=[{"requisition_item_id": walls["items"][0]["id"], "quantity": "0"}]
            ),
        )
    assert foreign.status_code == 422
    assert zero.status_code == 422
    assert await _po_count(world) == 0


async def test_a_retried_conversion_is_one_order(world: World) -> None:
    req = await _approved(world, vendor=world.vendor_active)
    body = _convert(
        world,
        [req["id"]],
        idempotency_key="erp-sync-42",
        lines=[{"requisition_item_id": _line(req, "Concrete C30/37")["id"], "quantity": "5"}],
    )
    async with client_as(world, world.editor, "editor") as c:
        first = await c.post(f"{REQ}/convert-to-po", json=body)
        second = await c.post(f"{REQ}/convert-to-po", json=body)
        after = (await c.get(f"{REQ}/{req['id']}")).json()
    assert first.status_code == 201, first.text
    assert second.status_code == 201
    assert second.json()["po_id"] == first.json()["po_id"]
    assert second.json()["replayed"] is True
    assert await _po_count(world) == 1
    assert D(_line(after, "Concrete C30/37")["quantity_ordered"]) == D("5")


async def test_received_and_outstanding_follow_confirmed_receipts_in_the_line_unit(world: World) -> None:
    from app.modules.procurement.models import GoodsReceipt, GoodsReceiptItem, PurchaseOrderItem

    req = await _approved(world, vendor=world.vendor_active)
    async with client_as(world, world.editor, "editor") as c:
        converted = (await c.post(f"{REQ}/convert-to-po", json=_convert(world, [req["id"]]))).json()
        po = (await c.get(f"{BASE}/{converted['po_id']}")).json()
        # The buyer restates the rebar line in kilograms on the draft order.
        lines = [
            {
                "description": i["description"],
                "quantity": "3250" if i["unit"] == "t" else i["quantity"],
                "unit": "kg" if i["unit"] == "t" else i["unit"],
                "unit_rate": "1",
                "requisition_item_id": i["requisition_item_id"],
            }
            for i in po["items"]
        ]
        patched = await c.patch(f"{BASE}/{po['id']}", json={"items": lines})
        assert patched.status_code == 200, patched.text
        restated = (await c.get(f"{REQ}/{req['id']}")).json()

    assert D(_line(restated, "Rebar B500")["quantity_ordered"]) == D("3.25"), "3250 kg is 3.25 t"
    assert restated["status"] == "ordered"

    async with world.factory() as s:
        items = (
            (await s.execute(select(PurchaseOrderItem).where(PurchaseOrderItem.po_id == uuid.UUID(po["id"]))))
            .scalars()
            .all()
        )
        concrete_item = next(i for i in items if i.description == "Concrete C30/37")
        rebar_item = next(i for i in items if i.description == "Rebar B500")
        for status, qty_concrete in (("confirmed", "40"), ("draft", "31.4")):
            receipt = GoodsReceipt(po_id=uuid.UUID(po["id"]), receipt_date=date.today().isoformat(), status=status)
            s.add(receipt)
            await s.flush()
            s.add(GoodsReceiptItem(receipt_id=receipt.id, po_item_id=concrete_item.id, quantity_received=qty_concrete))
            s.add(GoodsReceiptItem(receipt_id=receipt.id, po_item_id=rebar_item.id, quantity_received="1000"))
        await s.commit()

    async with client_as(world, world.editor, "editor") as c:
        received = (await c.get(f"{REQ}/{req['id']}")).json()
    concrete = _line(received, "Concrete C30/37")
    rebar = _line(received, "Rebar B500")
    assert D(concrete["quantity_received"]) == D("40"), "a draft receipt is not received yet"
    assert D(concrete["quantity_outstanding"]) == D("31.4")
    assert D(rebar["quantity_received"]) == D("1"), "1000 kg received is 1 t of the line"
    assert D(rebar["quantity_outstanding"]) == D("2.25")
    assert D(received["reconciliation"]["received"]) == D("41")


async def test_an_order_line_in_an_unconvertible_unit_is_shown_and_not_counted(world: World) -> None:
    req = await _approved(world, vendor=world.vendor_active)
    async with client_as(world, world.editor, "editor") as c:
        converted = (await c.post(f"{REQ}/convert-to-po", json=_convert(world, [req["id"]]))).json()
        po = (await c.get(f"{BASE}/{converted['po_id']}")).json()
        lines = [
            {
                "description": i["description"],
                "quantity": i["quantity"],
                "unit": "pcs" if i["unit"] == "t" else i["unit"],
                "unit_rate": "1",
                "requisition_item_id": i["requisition_item_id"],
            }
            for i in po["items"]
        ]
        await c.patch(f"{BASE}/{po['id']}", json={"items": lines})
        after = (await c.get(f"{REQ}/{req['id']}")).json()
        report = (await c.get(f"{REQ}/{req['id']}/validate")).json()
    rebar = _line(after, "Rebar B500")
    assert rebar["po_items"][0]["unit_mismatch"] is True
    assert D(rebar["quantity_ordered"]) == 0
    assert after["status"] == "approved", "the uncounted line leaves quantity to order"
    assert any("requisition_order_unit_mismatch" in str(r.get("rule_id")) for r in report["results"])


async def test_cancelling_one_of_two_orders_gives_back_only_its_quantity(world: World) -> None:
    req = await _approved(world, vendor=world.vendor_active)
    concrete = _line(req, "Concrete C30/37")
    async with client_as(world, world.editor, "editor") as c:
        first = (
            await c.post(
                f"{REQ}/convert-to-po",
                json=_convert(world, [req["id"]], lines=[{"requisition_item_id": concrete["id"], "quantity": "30"}]),
            )
        ).json()
        second = (await c.post(f"{REQ}/convert-to-po", json=_convert(world, [req["id"]]))).json()
    async with client_as(world, world.manager, "manager") as c:
        cancelled = await c.post(f"{BASE}/{second['po_id']}/cancel/", json={"reason": "Wrong supplier"})
        after = (await c.get(f"{REQ}/{req['id']}")).json()
    assert cancelled.status_code == 200, cancelled.text
    assert after["status"] == "approved"
    assert after["po_id"] == first["po_id"], "it names the order that still stands"
    assert D(_line(after, "Concrete C30/37")["quantity_ordered"]) == D("30")
    assert D(_line(after, "Rebar B500")["quantity_ordered"]) == 0
    assert {p["status"] for p in after["purchase_orders"]} == {"draft", "cancelled"}


# ── External orders ─────────────────────────────────────────────────────────


async def _external_project(w: World) -> None:
    async with client_as(w, w.manager, "manager") as c:
        saved = await c.put(
            f"{REQ}/settings", params={"project_id": str(w.project_id)}, json={"order_owner": "external"}
        )
    assert saved.status_code == 200, saved.text
    assert saved.json()["order_owner"] == "external"


async def test_an_external_system_orders_and_nothing_is_ordered_here(world: World) -> None:
    from app.modules.procurement.models import RequisitionExternalOrderLine

    await _external_project(world)
    req = await _approved(world, vendor=world.vendor_active)
    concrete, rebar = _line(req, "Concrete C30/37"), _line(req, "Rebar B500")
    report = {
        "external_system": "ERP-X",
        "external_order_number": "4500012345",
        "lines": [
            {"requisition_item_id": concrete["id"], "external_line_ref": "10", "quantity_ordered": "71.4"},
            {
                "requisition_item_id": rebar["id"],
                "external_line_ref": "20",
                "quantity_ordered": "3250",
                "unit": "kg",
                "status": "confirmed",
                "confirmed_delivery_date": (date.today() + timedelta(days=9)).isoformat(),
            },
        ],
    }
    async with client_as(world, world.editor, "editor") as c:
        refused = await c.post(f"{REQ}/convert-to-po", json=_convert(world, [req["id"]]))
        first = await c.post(f"{REQ}/{req['id']}/external-orders", json=report)
        repeat = await c.post(f"{REQ}/{req['id']}/external-orders", json=report)
        received_report = {
            **report,
            "lines": [dict(report["lines"][0], quantity_received="20", status="partially_received")],
        }
        received = await c.post(f"{REQ}/{req['id']}/external-orders", json=received_report)
        bad_unit = await c.post(
            f"{REQ}/{req['id']}/external-orders",
            json={**report, "lines": [dict(report["lines"][0], unit="pcs")]},
        )

    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "requisition_orders_external"
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["order_owner"] == "external"
    assert body["status"] == "ordered"
    assert D(_line(body, "Rebar B500")["quantity_ordered"]) == D("3.25")
    assert _line(body, "Rebar B500")["external_orders"][0]["confirmed_delivery_date"]
    assert await _po_count(world) == 0, "no local order, so no second commitment"
    assert repeat.json()["row_version"] == body["row_version"], "the same report changes nothing"
    assert len(repeat.json()["history"]) == len(body["history"])
    assert D(_line(received.json(), "Concrete C30/37")["quantity_received"]) == D("20")
    assert D(_line(received.json(), "Concrete C30/37")["quantity_outstanding"]) == D("51.4")
    assert bad_unit.status_code == 422
    async with world.factory() as s:
        rows = (await s.execute(select(func.count()).select_from(RequisitionExternalOrderLine))).scalar_one()
    assert rows == 2


async def test_an_ocerp_requisition_takes_no_external_report(world: World) -> None:
    req = await _approved(world, vendor=world.vendor_active)
    async with client_as(world, world.editor, "editor") as c:
        refused = await c.post(
            f"{REQ}/{req['id']}/external-orders",
            json={
                "external_system": "ERP-X",
                "external_order_number": "1",
                "lines": [{"requisition_item_id": req["items"][0]["id"], "quantity_ordered": "1"}],
            },
        )
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "requisition_orders_in_ocerp"


async def test_switching_the_project_keeps_existing_requisitions_as_they_were(world: World) -> None:
    before = await _approved(world, vendor=world.vendor_active)
    await _external_project(world)
    async with client_as(world, world.editor, "editor") as c:
        converted = await c.post(f"{REQ}/convert-to-po", json=_convert(world, [before["id"]]))
    assert converted.status_code == 201, "a requisition keeps the owner it was created with"


# ── Idempotent create and the feed ──────────────────────────────────────────


async def test_a_retried_create_is_one_requisition(world: World) -> None:
    body = {**_body(world), "client_request_id": "site-app-7f3a"}
    async with client_as(world, world.editor, "editor") as c:
        first = await c.post(f"{REQ}/", json=body)
        second = await c.post(f"{REQ}/", json=body)
        listed = (await c.get(f"{REQ}/", params={"project_id": str(world.project_id)})).json()
    assert first.json()["id"] == second.json()["id"]
    assert listed["total"] == 1


async def test_every_change_is_in_the_feed_and_the_cursor_never_skips(world: World) -> None:
    async with client_as(world, world.editor, "editor") as c:
        created = (await c.post(f"{REQ}/", json=_body(world))).json()
        await c.patch(f"{REQ}/{created['id']}", json={"items": _body(world)["items"][:1]})
        await c.post(f"{REQ}/{created['id']}/submit")
        await c.post(f"{REQ}/{created['id']}/cancel", json={"reason": "Not needed"})
        params = {"project_id": str(world.project_id), "settle_seconds": 0, "limit": 2}
        page1 = (await c.get(f"{REQ}/feed", params=params)).json()
        page2 = (await c.get(f"{REQ}/feed", params={**params, "after": page1["next_cursor"]})).json()
        page3 = (await c.get(f"{REQ}/feed", params={**params, "after": page2["next_cursor"]})).json()
        replay = (await c.get(f"{REQ}/feed", params={**params, "after": page1["next_cursor"]})).json()
        unsettled = (
            await c.get(f"{REQ}/feed", params={"project_id": str(world.project_id), "settle_seconds": 600})
        ).json()
        bad = await c.get(f"{REQ}/feed", params={"project_id": str(world.project_id), "after": "not-a-cursor"})

    events = [e["event"] for e in page1["items"] + page2["items"] + page3["items"]]
    assert events == ["created", "updated", "submitted", "cancelled"]
    assert page1["has_more"] is True
    assert page3["items"] == [] or page3["items"][-1]["event"] == "cancelled"
    assert [e["row_version"] for e in page1["items"] + page2["items"]] == [1, 2, 3, 4]
    updated = page1["items"][1]
    assert len(updated["payload"]["lines_before"]) == 2, "the line change is recorded, not only its name"
    assert len(updated["payload"]["lines_after"]) == 1
    assert [e["id"] for e in replay["items"]] == [e["id"] for e in page2["items"]], "replay returns the same entries"
    assert page3["next_cursor"], "an empty page keeps the cursor where it was"
    assert unsettled["items"] == [], "entries younger than the settle window are held back"
    assert bad.status_code == 422


async def test_the_feed_entry_commits_with_its_change(world: World) -> None:
    from app.modules.procurement.models import RequisitionChange

    async with client_as(world, world.editor, "editor") as c:
        created = (await c.post(f"{REQ}/", json=_body(world))).json()
        refused = await c.post(f"{REQ}/{created['id']}/approve", json={})
    assert refused.status_code == 403
    async with world.factory() as s:
        rows = (
            (
                await s.execute(
                    select(RequisitionChange.event).where(RequisitionChange.requisition_id == uuid.UUID(created["id"]))
                )
            )
            .scalars()
            .all()
        )
    assert rows == ["created"]


# ── Access ──────────────────────────────────────────────────────────────────


async def test_an_outsider_reaches_none_of_the_new_routes(world: World) -> None:
    req = await _approved(world, vendor=world.vendor_active)
    pid = str(world.project_id)
    async with client_as(world, world.outsider, "manager") as c:
        responses = {
            "settings": await c.get(f"{REQ}/settings", params={"project_id": pid}),
            "settings_put": await c.put(
                f"{REQ}/settings", params={"project_id": pid}, json={"order_owner": "external"}
            ),
            "feed": await c.get(f"{REQ}/feed", params={"project_id": pid, "settle_seconds": 0}),
            "external": await c.post(
                f"{REQ}/{req['id']}/external-orders",
                json={
                    "external_system": "X",
                    "external_order_number": "1",
                    "lines": [{"requisition_item_id": req["items"][0]["id"], "quantity_ordered": "1"}],
                },
            ),
            "convert_lines": await c.post(
                f"{REQ}/convert-to-po",
                json=_convert(
                    world, [req["id"]], lines=[{"requisition_item_id": req["items"][0]["id"], "quantity": "1"}]
                ),
            ),
        }
    for name, response in responses.items():
        assert response.status_code in (403, 404), (name, response.status_code)
    assert await _po_count(world) == 0
    async with client_as(world, world.manager, "manager") as c:
        settings = (await c.get(f"{REQ}/settings", params={"project_id": pid})).json()
    assert settings["order_owner"] == "ocerp", "the outsider's write did not land"


async def test_the_feed_of_one_project_never_shows_another(world: World) -> None:
    from app.modules.projects.models import Project

    other = uuid.uuid4()
    async with world.factory() as s:
        s.add(Project(id=other, name="Other", currency="EUR", status="active", owner_id=world.outsider, metadata_={}))
        await s.commit()
    await _submitted(world, by=world.editor)
    async with client_as(world, world.outsider, "manager") as c:
        own = (await c.get(f"{REQ}/feed", params={"project_id": str(other), "settle_seconds": 0})).json()
    assert own["items"] == []
