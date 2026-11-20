"""R6 corner cases: elements that move between positions, rules that start matching, override equal to the
model, money and unit mismatches, who may touch the estimate, repeated installs."""

from __future__ import annotations

import copy
import uuid

import pytest

from .conftest import LINK, make_project, make_user
from .ddcrev import example_rows, package
from .test_design_revisions import BASE, WALL, _linked_project, _token, _upload
from .test_estimate_rules import SLAB, D, _by_rule, _link_of, _set_quantity

pytestmark = pytest.mark.asyncio

ROOF = "b1/s06/roof/0"


async def _publish(client, h, tok, pid, rows, parent=None, parent_rows=None):
    data, m = package(pid, rows, parent_id=parent, parent_rows=parent_rows)
    rev = await _upload(client, pid, tok, data)
    assert rev.status_code == 201, rev.text
    acc = await client.post(f"{BASE}/revisions/{rev.json()['revision_id']}/accept", headers=h)
    assert acc.status_code == 200, acc.text
    return m["revision_id"], rows


async def _summary(client, h, pid):
    return _by_rule((await client.get(f"{BASE}/projects/{pid}/estimate", headers=h)).json())


def _with_roof(rows):
    base = copy.deepcopy(next(r for r in rows if r["element_key"] == SLAB))
    base.update(
        id=ROOF,
        stable_id=ROOF,
        element_key=ROOF,
        element_type="Roof",
        ifc_class="IfcRoof",
        type_key="roof/flat-bitumen",
        area_m2=150.0,
        volume_m3=None,
        geometry_hash="0badc0ffee0ddf00",
        material=None,
        storey="DG",
    )
    return rows + [base]


async def test_rule_starts_matching_and_an_element_moves_between_positions(client):
    uid, h, pid, tok = await _linked_project(client)
    est = f"{BASE}/projects/{pid}/estimate"
    rows1 = example_rows()
    rid1, _ = await _publish(client, h, tok, pid, rows1)
    assert (await client.post(f"{est}/rules/starter", json={"country": "DE"}, headers=h)).status_code == 201
    assert (await client.post(f"{est}/run", headers=h)).status_code == 200
    p1 = await _summary(client, h, pid)
    assert "no_match" in p1["roof"]["flags"] and D(p1["roof"]["quantity"]) == 0
    assert D(p1["wall_ext"]["quantity"]) == D("82.5") and D(p1["wall_int"]["quantity"]) == 0

    # a roof appears; the exterior wall is re-typed as an interior wall: the quantity moves between positions
    rows2 = _with_roof(copy.deepcopy(rows1))
    wall = next(r for r in rows2 if r["element_key"] == WALL)
    wall.update(type_key="wall/int-brick-115", geometry_hash="5e5e5e5e5e5e5e5e")
    from .ddcrev import glb

    data, m2 = package(pid, rows2, parent_id=rid1, parent_rows=rows1, files={"geometry.glb": glb(rows2)})
    up = await _upload(client, pid, tok, data)
    assert up.status_code == 201, up.text
    # the dry run says what will move before anybody accepts
    imp = (await client.get(f"{BASE}/revisions/{up.json()['revision_id']}/impact", headers=h)).json()
    by = {r["rule"]: r for r in imp["rows"]}
    assert D(by["roof"]["quantity_delta"]) == D("150") and "no_match" not in by["roof"]["flags"]
    assert D(by["wall_ext"]["quantity_delta"]) == D("-82.5") and by["wall_ext"]["elements"]["removed"] == [WALL]
    assert D(by["wall_int"]["quantity_delta"]) == D("82.5") and by["wall_int"]["elements"]["added"] == [WALL]
    assert (await _summary(client, h, pid))["roof"]["quantity"] == p1["roof"]["quantity"]  # a dry run

    assert (await client.post(f"{BASE}/revisions/{up.json()['revision_id']}/accept", headers=h)).status_code == 200
    p2 = await _summary(client, h, pid)
    assert D(p2["roof"]["quantity"]) == D("150") and "no_match" not in p2["roof"]["flags"]
    assert (await _link_of(p2["roof"]["position_id"])) == [("active", [ROOF])]
    assert D(p2["wall_ext"]["quantity"]) == 0 and "no_match" in p2["wall_ext"]["flags"]
    assert D(p2["wall_int"]["quantity"]) == D("82.5") and (await _link_of(p2["wall_int"]["position_id"])) == [
        ("active", [WALL])
    ]
    assert p2["wall_ext"]["position_id"] == p1["wall_ext"]["position_id"]  # positions are never recreated

    # the roof goes away again: quantity back to zero, position and its history stay
    rid2 = m2["revision_id"]
    rows3 = [r for r in rows2 if r["element_key"] != ROOF]
    await _publish(client, h, tok, pid, rows3, parent=rid2, parent_rows=rows2)
    p3 = await _summary(client, h, pid)
    assert D(p3["roof"]["quantity"]) == 0 and "no_match" in p3["roof"]["flags"]
    assert p3["roof"]["position_id"] == p1["roof"]["position_id"]


async def test_override_equal_to_the_model_is_not_an_override_and_reverting_follows_the_model(client):
    uid, h, pid, tok = await _linked_project(client)
    est = f"{BASE}/projects/{pid}/estimate"
    rows1 = example_rows()
    rid1, _ = await _publish(client, h, tok, pid, rows1)
    await client.post(f"{est}/rules/starter", json={"country": "DE"}, headers=h)
    await client.post(f"{est}/run", headers=h)
    s1 = await _summary(client, h, pid)
    pos = s1["wall_ext"]["position_id"]

    # typing the very value the model gives is not a deviation
    await _set_quantity(pos, "82.5")
    assert not (await _summary(client, h, pid))["wall_ext"]["override"]
    # a different value is, with or without a reason
    await _set_quantity(pos, "70")
    assert (await _summary(client, h, pid))["wall_ext"]["override"]

    rows2 = copy.deepcopy(rows1)
    next(r for r in rows2 if r["element_key"] == WALL).update(area_m2=88.1, geometry_hash="9f2c4a1e0b7d3c66")
    rid2, _ = await _publish(client, h, tok, pid, rows2, parent=rid1, parent_rows=rows1)
    s2 = await _summary(client, h, pid)
    assert D(s2["wall_ext"]["quantity"]) == 70 and s2["wall_ext"]["override"]
    assert D(s2["wall_ext"]["model_quantity"]) == D("88.1")

    # the person sets it back to what the model says now: follows the model again on the next change
    await _set_quantity(pos, "88.1")
    assert not (await _summary(client, h, pid))["wall_ext"]["override"]
    rows3 = copy.deepcopy(rows2)
    next(r for r in rows3 if r["element_key"] == WALL).update(area_m2=91.0, geometry_hash="a1a1a1a1a1a1a1a1")
    await _publish(client, h, tok, pid, rows3, parent=rid2, parent_rows=rows2)
    s3 = await _summary(client, h, pid)
    assert D(s3["wall_ext"]["quantity"]) == D("91") and not s3["wall_ext"]["override"]


async def test_rate_mismatches_are_refused(client):
    uid, h, pid, tok = await _linked_project(client)
    est = f"{BASE}/projects/{pid}/estimate"
    await _publish(client, h, tok, pid, example_rows())
    await client.post(f"{est}/rules/starter", json={"country": "DE"}, headers=h)
    await client.post(f"{est}/run", headers=h)
    pos = (await _summary(client, h, pid))["wall_ext"]["position_id"]
    url = f"{est}/positions/{pos}/price"
    good = {"unit_rate": "10", "source_url": "https://example.org/r", "price_date": "2026-01-15"}
    assert (await client.post(url, json={**good, "currency": "USD"}, headers=h)).status_code == 422  # project is EUR
    assert (await client.post(url, json={**good, "unit_rate": "-1"}, headers=h)).status_code == 422
    assert (await client.post(url, json={**good, "price_date": "15.01.2026"}, headers=h)).status_code == 422
    assert (await client.post(url, json={**good, "price_date": "2026-13-45x"}, headers=h)).status_code == 422
    assert (await client.post(url, json={**good, "currency": "EURO"}, headers=h)).status_code == 422
    assert (await client.post(url, json={"cost_item_id": str(uuid.uuid4())}, headers=h)).status_code == 422
    assert (await client.post(url, json={}, headers=h)).status_code == 422
    assert D((await _summary(client, h, pid))["wall_ext"]["unit_rate"] or 0) == 0  # nothing was written
    assert (await client.post(url, json={**good, "currency": "eur"}, headers=h)).status_code == 204
    assert D((await _summary(client, h, pid))["wall_ext"]["unit_rate"]) == 10
    # a position that is not one of the estimate's
    other = f"{est}/positions/{uuid.uuid4()}/price"
    assert (await client.post(other, json=good, headers=h)).status_code == 404


async def test_cost_item_in_another_unit_or_currency_is_refused(client):
    from app.database import async_session_factory
    from app.modules.costs.models import CostItem

    uid, h, pid, tok = await _linked_project(client)
    est = f"{BASE}/projects/{pid}/estimate"
    await _publish(client, h, tok, pid, example_rows())
    await client.post(f"{est}/rules/starter", json={"country": "DE"}, headers=h)
    await client.post(f"{est}/run", headers=h)
    pos = (await _summary(client, h, pid))["wall_ext"]["position_id"]
    ids = {}
    async with async_session_factory() as s:
        for tag, unit, cur in (("m3", "m3", "EUR"), ("usd", "m2", "USD"), ("ok", "M2", "EUR")):
            item = CostItem(
                code=f"DSG-{tag}-{uuid.uuid4().hex[:6]}",
                description="Test",
                unit=unit,
                rate="55.5",
                currency=cur,
                source="test",
                is_active=True,
            )
            s.add(item)
            await s.flush()
            ids[tag] = str(item.id)
        await s.commit()
    url = f"{est}/positions/{pos}/price"
    assert (await client.post(url, json={"cost_item_id": ids["m3"]}, headers=h)).status_code == 422
    assert (await client.post(url, json={"cost_item_id": ids["usd"]}, headers=h)).status_code == 422
    assert (await client.post(url, json={"cost_item_id": ids["ok"]}, headers=h)).status_code == 204
    assert D((await _summary(client, h, pid))["wall_ext"]["unit_rate"]) == D("55.5")


async def test_who_may_touch_the_estimate(client):
    owner, h_owner = await make_user(client)
    viewer, h_viewer = await make_user(client, role="viewer")
    stranger, h_stranger = await make_user(client, role="manager")
    pid = await make_project(owner)
    tok = await _token(client, h_owner, pid)
    assert (await client.post(f"{BASE}/projects/{pid}/lock", headers=tok)).status_code == 200
    await _publish(client, h_owner, tok, pid, example_rows())
    est = f"{BASE}/projects/{pid}/estimate"
    assert (
        await client.post(f"{est}/rules/starter", json={"country": "DE"}, headers={**h_owner, **LINK})
    ).status_code == 201
    assert (await client.post(f"{est}/run", headers=h_owner)).status_code == 200
    pos = (await _summary(client, h_owner, pid))["wall_ext"]["position_id"]
    for h in (h_viewer, h_stranger):  # no project access at all
        hh = {**h, **LINK}
        for method, url in (
            ("GET", est),
            ("GET", f"{est}/rules"),
            ("POST", f"{est}/run"),
            ("POST", f"{est}/rules/starter"),
            ("PUT", f"{est}/positions/{pos}/override-reason"),
            ("POST", f"{est}/positions/{pos}/price"),
        ):
            assert (
                await client.request(method, url, headers=hh, json={"country": "DE", "reason": "x"})
            ).status_code == 404, url
    # the link token reads but cannot manage
    assert (await client.get(est, headers=tok)).status_code == 200
    assert (await client.get(f"{est}/rules", headers=tok)).status_code == 200
    for method, url, body in (
        ("POST", f"{est}/run", {}),
        ("PUT", f"{est}/positions/{pos}/override-reason", {"reason": "x"}),
        ("POST", f"{est}/positions/{pos}/price", {"unit_rate": "1"}),
    ):
        assert (await client.request(method, url, headers=tok, json=body)).status_code == 403


async def test_repeated_installs_and_odd_inputs(client):
    uid, h, pid, tok = await _linked_project(client)
    est = f"{BASE}/projects/{pid}/estimate"
    assert (await client.post(f"{est}/run", headers=h)).status_code == 404  # nothing accepted yet
    await _publish(client, h, tok, pid, example_rows())
    assert (await client.post(f"{est}/run", headers=h)).status_code == 200  # nothing to apply is not an error
    assert (await client.post(f"{est}/rules/starter", json={"country": "de"}, headers=h)).status_code == 201
    assert (await client.post(f"{est}/run", headers=h)).status_code == 200
    first = await _summary(client, h, pid)
    assert (await client.post(f"{est}/rules/starter", json={"country": "DE"}, headers=h)).status_code == 201
    assert (await client.post(f"{est}/run", headers=h)).status_code == 200
    again = await _summary(client, h, pid)
    assert {k: v["position_id"] for k, v in first.items()} == {k: v["position_id"] for k, v in again.items()}
    assert (await client.post(f"{est}/rules/starter", json={"country": "D"}, headers=h)).status_code == 422
    assert (await client.post(f"{est}/rules/starter", json={}, headers=h)).status_code == 422
    assert (await client.post(f"{est}/rules", json={"schema": "ddc-rules/2"}, headers=h)).status_code == 422
    assert (await client.post(f"{est}/rules", json=[], headers=h)).status_code == 422
    pos = again["wall_ext"]["position_id"]
    url = f"{est}/positions/{pos}/override-reason"
    assert (await client.put(url, json={"reason": "x" * 2001}, headers=h)).status_code == 422
    assert (await client.put(url, json={}, headers=h)).status_code == 422
    assert (
        await client.put(f"{est}/positions/{uuid.uuid4()}/override-reason", json={"reason": "x"}, headers=h)
    ).status_code == 404
    assert (await client.put(url, json={"reason": "gemessen"}, headers=h)).status_code == 204
    assert (await _summary(client, h, pid))["wall_ext"]["override_reason"] == "gemessen"
    run_bad = await client.post(f"{est}/run", json={"revision_id": str(uuid.uuid4())}, headers=h)
    assert run_bad.status_code == 404
    assert (await client.get(f"{BASE}/revisions/{uuid.uuid4()}/impact", headers=h)).status_code == 404


async def test_a_position_a_person_deleted_does_not_block_acceptance(client):
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.boq.repository import PositionRepository
    from app.modules.design.models import DesignEstimateBinding

    from .ddcrev import glb

    uid, h, pid, tok = await _linked_project(client)
    est = f"{BASE}/projects/{pid}/estimate"
    rows1 = example_rows()
    rid1, _ = await _publish(client, h, tok, pid, rows1)
    assert (await client.post(f"{est}/rules/starter", json={"country": "DE"}, headers=h)).status_code == 201
    assert (await client.post(f"{est}/run", headers=h)).status_code == 200
    cur = (await client.get(est, headers=h)).json()
    gone = next(p for p in cur["positions"] if p["rule"] == "wall_ext")
    rows2 = _with_roof(copy.deepcopy(rows1))
    data, m2 = package(pid, rows2, parent_id=rid1, parent_rows=rows1, files={"geometry.glb": glb(rows2)})
    up = await _upload(client, pid, tok, data)
    assert up.status_code == 201, up.text
    async with async_session_factory() as s:
        await PositionRepository(s).delete(uuid.UUID(gone["position_id"]))
        await s.commit()
    rev2 = up.json()["revision_id"]
    imp = await client.get(f"{BASE}/revisions/{rev2}/impact", headers=h)
    assert imp.status_code == 200, imp.text
    assert (await client.post(f"{BASE}/revisions/{rev2}/accept", headers=h)).status_code == 200
    after = (await client.get(est, headers=h)).json()
    assert "wall_ext" not in {p["rule"] for p in after["positions"]}
    async with async_session_factory() as s:
        b = (
            await s.execute(
                select(DesignEstimateBinding).where(
                    DesignEstimateBinding.project_id == uuid.UUID(str(pid)),
                    DesignEstimateBinding.rule_code == "wall_ext",
                )
            )
        ).scalar_one()
        assert "position_deleted" in b.flags
        assert await PositionRepository(s).get_by_id(uuid.UUID(gone["position_id"])) is None  # never recreated
