"""R9: a draft change order from an accepted revision, through the ERP's change-order service."""

from __future__ import annotations

import uuid
from decimal import ROUND_HALF_UP, Decimal

import pytest

from .conftest import make_user
from .ddcrev import example_rows, package
from .test_design_revisions import BASE, DOOR, WALL, _linked_project, _upload
from .test_estimate_rules import SLAB, _rows2

pytestmark = pytest.mark.asyncio
NEW_DOOR = "b1/s01/u2A/door-entry/1"


def D(v) -> Decimal:
    return Decimal(str(v))


def c2(v) -> Decimal:
    return D(v).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


async def _orders(pid):
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.changeorders.models import ChangeOrder

    async with async_session_factory() as s:
        return list((await s.execute(select(ChangeOrder).where(ChangeOrder.project_id == pid))).scalars())


async def _items(order_id):
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.changeorders.models import ChangeOrderItem

    async with async_session_factory() as s:
        q = select(ChangeOrderItem).where(ChangeOrderItem.change_order_id == order_id)
        return list((await s.execute(q)).scalars())


async def _positions(boq_id):
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.boq.models import Position

    async with async_session_factory() as s:
        return list((await s.execute(select(Position).where(Position.boq_id == uuid.UUID(boq_id)))).scalars())


async def _two_revisions(client, *, priced: bool = True, mode: str | None = None):
    """R1 accepted with rules run (wall priced at 10 from a named source), R2 shared."""
    uid, h, pid, tok = await _linked_project(client)
    if mode:
        r = await client.put(f"{BASE}/projects/{pid}/change-orders/settings", json={"mode": mode}, headers=h)
        assert r.status_code == 200, r.text
    rows1 = example_rows()
    d1, m1 = package(pid, rows1)
    rev1 = (await _upload(client, pid, tok, d1)).json()
    assert (await client.post(f"{BASE}/revisions/{rev1['revision_id']}/accept", headers=h)).status_code == 200
    est = f"{BASE}/projects/{pid}/estimate"
    assert (await client.post(f"{est}/rules/starter", json={"country": "DE"}, headers=h)).status_code == 201
    assert (await client.post(f"{est}/run", headers=h)).status_code == 200
    s1 = (await client.get(est, headers=h)).json()
    if priced:
        wall = next(p for p in s1["positions"] if p["rule"] == "wall_ext")["position_id"]
        ok = await client.post(
            f"{est}/positions/{wall}/price",
            headers=h,
            json={"unit_rate": "10", "source_url": "https://example.org/rates", "price_date": "2026-01-15"},
        )
        assert ok.status_code == 204, ok.text
    d2, m2 = package(pid, _rows2(), parent_id=m1["revision_id"], parent_rows=rows1)
    rev2 = (await _upload(client, pid, tok, d2)).json()
    return uid, h, pid, tok, rev1["revision_id"], rev2["revision_id"], s1["boq_id"]


async def test_accept_with_change_order_carries_impact_and_elements(client):
    uid, h, pid, tok, r1, r2, boq_id = await _two_revisions(client)
    st = (await client.get(f"{BASE}/projects/{pid}/change-orders/settings", headers=h)).json()
    assert st == {"mode": "ask", "can_change": True, "can_create": True}
    # the first accept (setting "ask", no answer) kept a snapshot and made no order
    assert (await client.get(f"{BASE}/revisions/{r1}/change-order", headers=h)).json()["state"] == "declined"
    imp = (await client.get(f"{BASE}/revisions/{r2}/impact", headers=h)).json()
    acc = await client.post(f"{BASE}/revisions/{r2}/accept", json={"comment": "ok", "change_order": True}, headers=h)
    assert acc.status_code == 200, acc.text

    view = (await client.get(f"{BASE}/revisions/{r2}/change-order", headers=h)).json()
    assert view["state"] == "created"
    co = view["change_order"]
    assert (
        co["status"] == "draft" and co["code"].startswith("CO-") and co["url"] == f"/changeorders?highlight={co['id']}"
    )
    [order] = await _orders(pid)
    assert str(order.id) == co["id"] and order.reason_category == "design_change" and order.currency == "EUR"
    assert order.status == "draft" and order.approved_by is None

    # numbers equal the impact the acceptance screen showed
    moving = [r for r in imp["rows"] if D(r["quantity_delta"]) != 0]
    items = {i.metadata_["design_rule"]: i for i in await _items(order.id)}
    assert set(items) == {r["rule"] for r in moving} and moving
    for r in moving:
        it = items[r["rule"]]
        assert D(it.original_quantity) == D(r["current_quantity"]) and D(it.new_quantity) == D(r["new_quantity"])
        assert D(it.new_rate) == D(it.original_rate) == D(r["unit_rate"])
        assert c2(it.cost_delta) == c2(r["cost_delta"]), r["rule"]
        assert it.metadata_["boq_position_id"] == r["position_id"] and it.metadata_["boq_id"] == boq_id
    assert c2(order.cost_impact) == c2(imp["totals"]["delta"]) == c2(co["cost_impact"])
    assert c2(items["wall_ext"].cost_delta) == c2(D("5.6") * 10)
    # unpriced: no rate is guessed, the item says so and is flagged
    slab = items["slab"]
    assert D(slab.new_rate) == 0 and D(slab.cost_delta) == 0 and slab.metadata_["unpriced"] is True
    assert "no rate" in slab.description and "slab" in order.metadata_["design"]["estimate"]["unpriced_positions"]
    assert "have no rate" in order.description and co["unpriced_positions"] >= 1

    # changed elements, keyed like the BIM elements, and the way back to the revision
    meta = order.metadata_
    assert meta["source"] == "design_revision" and meta["design_revision_id"] == r2
    els = meta["design"]["elements"]
    assert els["added"] == [NEW_DOOR] and els["removed"] == [DOOR] and {WALL, SLAB} <= set(els["changed"])
    assert els["bim_diff_id"] and els["bim_model_id"] != els["parent_bim_model_id"]
    assert meta["design"]["acceptance_url"] == f"/design/acceptance?revision={r2}"
    assert f"/design/acceptance?revision={r2}" in order.description
    assert meta["design"]["schedule"] is None and order.schedule_impact_days == 0

    # idempotent: asking again returns the same order; the revision cannot be accepted twice
    again = await client.post(f"{BASE}/revisions/{r2}/change-order", headers=h)
    assert again.status_code == 200 and again.json()["change_order"]["id"] == co["id"]
    assert (
        await client.post(f"{BASE}/revisions/{r2}/accept", json={"change_order": True}, headers=h)
    ).status_code == 409
    assert len(await _orders(pid)) == 1

    # a person approves in the register; the scope is not put into the design estimate a second time
    before = {p.id for p in await _positions(boq_id)}
    sub = await client.post(f"/api/v1/changeorders/{co['id']}/submit/", headers=h)
    assert sub.status_code == 200, sub.text
    _, boss = await make_user(client, role="admin")
    ap = await client.post(f"/api/v1/changeorders/{co['id']}/approve/", headers=boss)
    assert ap.status_code == 200, ap.text
    assert {p.id for p in await _positions(boq_id)} == before
    marker = [p for p in await _positions(boq_id) if p.unit == "section"]
    assert [m.metadata_["change_order_id"] for m in marker] == [co["id"]]


async def test_ask_declined_then_created_later_once(client):
    uid, h, pid, tok, r1, r2, _ = await _two_revisions(client)
    assert (
        await client.post(f"{BASE}/revisions/{r2}/accept", json={"change_order": False}, headers=h)
    ).status_code == 200
    v = (await client.get(f"{BASE}/revisions/{r2}/change-order", headers=h)).json()
    assert v["state"] == "declined" and v["snapshot"] is True and await _orders(pid) == []
    # the link token (editor) cannot create it; the manager can, from the snapshot taken at accept
    assert (await client.post(f"{BASE}/revisions/{r2}/change-order", headers=tok)).status_code == 403
    first = await client.post(f"{BASE}/revisions/{r2}/change-order", headers=h)
    assert first.status_code == 200, first.text
    second = await client.post(f"{BASE}/revisions/{r2}/change-order", headers=h)
    assert second.json()["change_order"]["id"] == first.json()["change_order"]["id"]
    [order] = await _orders(pid)
    assert c2(order.cost_impact) == c2(D("5.6") * 10)  # numbers from the snapshot, not from the moved positions


async def test_off_and_always(client):
    uid, h, pid, tok, r1, r2, _ = await _two_revisions(client, mode="off")
    assert (
        await client.post(f"{BASE}/revisions/{r2}/accept", json={"change_order": True}, headers=h)
    ).status_code == 200
    v = (await client.get(f"{BASE}/revisions/{r2}/change-order", headers=h)).json()
    assert v["mode"] == "off" and v["state"] == "none" and v["snapshot"] is False
    assert (await client.post(f"{BASE}/revisions/{r2}/change-order", headers=h)).status_code == 409
    assert await _orders(pid) == []

    uid, h, pid, tok, r1, r2, _ = await _two_revisions(client, mode="always")
    # "always" made one for the first revision too (no estimate yet: no items, says so)
    first = (await client.get(f"{BASE}/revisions/{r1}/change-order", headers=h)).json()
    assert first["state"] == "created" and D(first["change_order"]["cost_impact"]) == 0
    assert (await client.post(f"{BASE}/revisions/{r2}/accept", headers=h)).status_code == 200
    assert (await client.get(f"{BASE}/revisions/{r2}/change-order", headers=h)).json()["state"] == "created"
    orders = await _orders(pid)
    assert len(orders) == 2 and all(o.status == "draft" for o in orders)
    r1_order = next(o for o in orders if o.metadata_["design_revision_id"] == r1)
    assert "no design estimate" in r1_order.description and await _items(r1_order.id) == []


async def test_setting_and_creation_need_their_roles(client):
    from app.core.permissions import Role, permission_registry

    uid, h, pid, tok, r1, r2, _ = await _two_revisions(client)
    # the editor's link token and a stranger cannot change the setting
    assert (
        await client.put(f"{BASE}/projects/{pid}/change-orders/settings", json={"mode": "off"}, headers=tok)
    ).status_code == 403
    _, other = await make_user(client)
    assert (
        await client.put(f"{BASE}/projects/{pid}/change-orders/settings", json={"mode": "off"}, headers=other)
    ).status_code in (403, 404)
    assert (
        await client.put(f"{BASE}/projects/{pid}/change-orders/settings", json={"mode": "maybe"}, headers=h)
    ).status_code == 422

    old = permission_registry.get_min_role("changeorders.create")
    permission_registry.set_min_role("changeorders.create", Role.MANAGER)
    try:
        # the owner (an editor) may accept but not create change orders: refused before anything is written
        assert (await client.get(f"{BASE}/projects/{pid}/change-orders/settings", headers=h)).json()[
            "can_create"
        ] is False
        no = await client.post(f"{BASE}/revisions/{r2}/accept", json={"change_order": True}, headers=h)
        assert no.status_code == 403
        assert (await client.get(f"{BASE}/revisions/{r2}", headers=h)).json()["status"] == "shared"
        assert (
            await client.post(f"{BASE}/revisions/{r2}/accept", json={"change_order": False}, headers=h)
        ).status_code == 200
        assert (await client.post(f"{BASE}/revisions/{r2}/change-order", headers=h)).status_code == 403
        assert await _orders(pid) == []
    finally:
        permission_registry.set_min_role("changeorders.create", old)
