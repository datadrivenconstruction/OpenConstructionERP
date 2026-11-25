"""The whole CAD/BIM -> ERP chain in one project, on real services and seed data, numbers to the cent.

Brief -> quick massing -> revision 1 -> estimate with provenance -> BOQ quantity link -> schedule -> procurement
package and RFQ -> revision 2 diff -> change order draft. Worked numbers (DE starter rules, EUR): slab 401.2 m2
at 120 = 48144; external wall 82.5 m2 at 10 = 825 (88.1 m2 after revision 2, a change of 5.6 m2 = 56).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from .conftest import LINK, make_user
from .ddcrev import example_rows, package
from .test_change_orders import NEW_DOOR, _items, _orders
from .test_design_brief import EXAMPLE
from .test_design_revisions import BASE, BIM, DOOR, WALL, _linked_project, _upload
from .test_estimate_rules import _by_rule, _rows2
from .test_quick_massing_api import OFFICE

pytestmark = pytest.mark.asyncio

D = Decimal
HIDDEN = (403, 404)


def _d(v) -> Decimal:
    return Decimal(str(v))


async def _bill(client, h, boq_id) -> dict:
    return {x["id"]: x for x in (await client.get(f"/api/v1/boq/boqs/{boq_id}", headers=h)).json()["positions"]}


async def test_chain_from_brief_to_change_order(client):
    uid, h, pid, tok = await _linked_project(client)
    _, viewer = await make_user(client, role="viewer")
    _, stranger = await make_user(client)

    # 1. brief and quick massing: the project's own currency, a stranger is turned away
    assert (await client.put(f"{BASE}/projects/{pid}/brief", json=EXAMPLE, headers=h)).status_code == 200
    q = await client.post(f"{BASE}/projects/{pid}/quick", json=OFFICE, headers={**h, **LINK})
    assert q.status_code == 200, q.text
    assert _d(q.json()["cost"]["total"]) == D("7440000") and q.json()["cost"]["currency"] == "EUR"
    out = await client.post(f"{BASE}/projects/{pid}/quick", json=OFFICE, headers={**stranger, **LINK})
    assert out.status_code in HIDDEN

    # 2. revision 1: publishing is for a manager session; a viewer, the link token and a stranger cannot
    rows1 = example_rows()
    d1, _ = package(pid, rows1)
    rev1 = (await _upload(client, pid, tok, d1)).json()
    r1 = rev1["revision_id"]
    assert (await client.post(f"{BASE}/revisions/{r1}/accept", headers=viewer)).status_code in HIDDEN
    assert (await client.post(f"{BASE}/revisions/{r1}/accept", headers=tok)).status_code == 403
    assert (await client.get(f"{BASE}/revisions/{r1}", headers=stranger)).status_code in HIDDEN
    assert (await client.get(f"{BASE}/projects/{pid}/revisions", headers=stranger)).status_code in HIDDEN
    assert (await client.post(f"{BASE}/revisions/{r1}/accept", headers=h)).status_code == 200

    # 3. estimate positions with provenance back to the revision
    est = f"{BASE}/projects/{pid}/estimate"
    assert (await client.post(f"{est}/rules/starter", json={"country": "DE"}, headers=h)).status_code == 201
    assert (await client.post(f"{est}/run", headers=h)).status_code == 200
    assert (await client.get(est, headers=stranger)).status_code in HIDDEN
    s1 = (await client.get(est, headers=h)).json()
    pos = _by_rule(s1)
    wall_pos, slab_pos = pos["wall_ext"]["position_id"], pos["slab"]["position_id"]
    price = {"source_url": "https://example.org/rates", "price_date": "2026-01-15"}
    for p, rate in ((slab_pos, "120"), (wall_pos, "10")):
        r = await client.post(f"{est}/positions/{p}/price", headers=h, json={"unit_rate": rate, **price})
        assert r.status_code == 204, r.text
    boq_id = s1["boq_id"]
    bill = await _bill(client, h, boq_id)
    assert (_d(bill[slab_pos]["quantity"]), _d(bill[slab_pos]["total"])) == (D("401.2"), D("48144"))
    assert (_d(bill[wall_pos]["quantity"]), _d(bill[wall_pos]["total"])) == (D("82.5"), D("825"))
    for p, rule in ((slab_pos, "slab"), (wall_pos, "wall_ext")):
        meta = bill[p].get("metadata_") or bill[p].get("metadata") or {}
        assert (meta["provenance"]["module"], meta["provenance"]["rule"]) == ("oe_design", rule)
        assert meta["provenance"]["revision_id"] == r1 and meta["provenance"]["boq_position_id"] == p

    # 4. BOQ quantity link to the model element, applied on request; the BIM hub serves the same number
    mid1 = rev1["bim_model_id"]
    manual = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/positions/",
        json={"boq_id": boq_id, "ordinal": "99.001", "description": "Wall finish", "unit": "m2", "quantity": 1.0},
        headers=h,
    )
    assert manual.status_code == 201, manual.text
    mp = manual.json()["id"]
    body = {"model_id": mid1, "element_stable_ids": [WALL], "quantity_field": "area_m2", "aggregation": "sum"}
    foreign = await client.post(f"/api/v1/boq/positions/{mp}/quantity-links/", json=body, headers=stranger)
    assert foreign.status_code in HIDDEN
    link = await client.post(f"/api/v1/boq/positions/{mp}/quantity-links/", json=body, headers=h)
    assert link.status_code == 201, link.text
    assert _d((await _bill(client, h, boq_id))[mp]["quantity"]) == D("1")  # creating a link proposes only
    ap = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/quantity-links/apply/", json={"link_ids": [link.json()["id"]]}, headers=h
    )
    assert ap.status_code == 200, ap.text
    assert _d((await _bill(client, h, boq_id))[mp]["quantity"]) == D("82.5")
    els = {e["stable_id"]: e for e in (await client.get(f"{BIM}/models/{mid1}/elements/", headers=h)).json()["items"]}
    assert _d(els[WALL]["quantities"]["area_m2"]) == D("82.5")

    # 5. schedule: wall 82.5 m2 at the sourced rate, 4 workers = 3 days
    sch = await client.post(f"{BASE}/projects/{pid}/schedule/setup", json={"start_date": "2027-03-01"}, headers=h)
    assert sch.status_code == 201, sch.text
    wall_act = next(a for a in sch.json()["activities"] if a["rule"] == "wall_ext")
    assert wall_act["days"] == 3 and wall_act["boq_position_ids"] == [wall_pos]
    assert wall_act["provenance"]["crew_source"] == "source"
    assert (await client.get(f"{BASE}/projects/{pid}/schedule", headers=stranger)).status_code in HIDDEN

    # 6. procurement package and a draft RFQ whose line quantity is the take-off
    ps = await client.post(f"{BASE}/projects/{pid}/procurement/setup", json={"group_by": "type_key"}, headers=h)
    assert ps.status_code == 201, ps.text
    wall_line = next(x for x in ps.json()["lines"] if x["group_key"] == "wall/ext-masonry-365")
    other = await client.post(f"{BASE}/projects/{pid}/procurement/packages/IfcWall/rfq", headers=stranger)
    assert other.status_code in HIDDEN
    rfq = await client.post(f"{BASE}/projects/{pid}/procurement/packages/IfcWall/rfq", headers=h)
    assert rfq.status_code == 201 and rfq.json()["status"] == "draft", rfq.text
    lines = (await client.get(f"/api/v1/rfq-bidding/{rfq.json()['rfq_id']}/lines/", headers=h)).json()
    lines = lines.get("items", lines) if isinstance(lines, dict) else lines
    [line] = lines
    src = (line.get("metadata_") or line.get("metadata"))["provenance"]
    assert _d(line["quantity"]) == D("82.5") and src["revision_id"] == r1
    assert src["boq_position_id"] == wall_line["position_id"]

    # 7. revision 2: the diff names the changes; a viewer cannot publish; the order is a draft
    d2, _ = package(pid, _rows2(), parent_id=r1, parent_rows=rows1)
    rev2 = (await _upload(client, pid, tok, d2)).json()
    r2, mid2 = rev2["revision_id"], rev2["bim_model_id"]
    diff = await client.post(f"{BIM}/models/{mid2}/diff/{mid1}", headers=h)
    assert diff.status_code == 201, diff.text
    det = diff.json()["diff_details"]
    assert [a["stable_id"] for a in det["added"]] == [NEW_DOOR] and [x["stable_id"] for x in det["deleted"]] == [DOOR]
    assert WALL in {m["stable_id"] for m in det["modified"]}
    no = await client.post(f"{BASE}/revisions/{r2}/accept", json={"change_order": True}, headers=viewer)
    assert no.status_code in HIDDEN and await _orders(pid) == []
    acc = await client.post(f"{BASE}/revisions/{r2}/accept", json={"change_order": True}, headers=h)
    assert acc.status_code == 200, acc.text
    co = (await client.get(f"{BASE}/revisions/{r2}/change-order", headers=h)).json()
    assert co["state"] == "created" and co["change_order"]["status"] == "draft"
    [order] = await _orders(pid)
    items = {i.metadata_["design_rule"]: i for i in await _items(order.id)}
    wall_it, slab_it = items["wall_ext"], items["slab"]
    assert (_d(wall_it.original_quantity), _d(wall_it.new_quantity)) == (D("82.5"), D("88.1"))
    assert _d(wall_it.cost_delta).quantize(D("0.01")) == D("56.00")
    assert _d(slab_it.new_quantity) - _d(slab_it.original_quantity) == D("3.8")
    assert _d(slab_it.cost_delta).quantize(D("0.01")) == D("456.00")  # 3.8 m2 x 120
    assert order.metadata_["design"]["elements"]["added"] == [NEW_DOOR]
    assert order.status == "draft" and order.approved_by is None
    assert (await client.get(f"/api/v1/changeorders/{order.id}", headers=stranger)).status_code in HIDDEN

    # the bill and the element link both follow the accepted revision
    bill2 = await _bill(client, h, boq_id)
    assert (_d(bill2[wall_pos]["quantity"]), _d(bill2[wall_pos]["total"])) == (D("88.1"), D("881"))
    assert (_d(bill2[slab_pos]["quantity"]), _d(bill2[slab_pos]["total"])) == (D("405.0"), D("48600"))
    assert (await client.post(f"/api/v1/boq/boqs/{boq_id}/quantity-links/refresh/", headers=h)).status_code == 200
    assert (
        await client.post(
            f"/api/v1/boq/boqs/{boq_id}/quantity-links/apply/", json={"link_ids": [link.json()["id"]]}, headers=h
        )
    ).status_code == 200
    assert _d((await _bill(client, h, boq_id))[mp]["quantity"]) == D("88.1")
