"""A design project flows past the bill: cost plan, rollup, budget, cash flow, validation, data paths.

Worked numbers (starter rules, DE, CHF project): the slab is 401.2 m2 at 120 = 48144, the external wall
a person set to 90 m2 at 10 = 900, so direct cost is 49044; a 10 % overhead adds 4904.40 and the bill's
grand total is 53948.40. Every downstream figure below is read against those.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from .ddcrev import example_rows, package
from .test_design_revisions import BASE, _linked_project, _upload
from .test_estimate_money_chain import _price, _set_currency
from .test_estimate_rules import _by_rule, _rows2, _set_quantity

pytestmark = pytest.mark.asyncio

D = Decimal


def _meta(row: dict) -> dict:
    return row.get("metadata_") or row.get("metadata") or {}


async def _priced_design(client):
    uid, h, pid, tok = await _linked_project(client)
    await _set_currency(pid, "CHF")
    est = f"{BASE}/projects/{pid}/estimate"
    d1, _ = package(pid, example_rows())
    rev = (await _upload(client, pid, tok, d1)).json()
    assert (await client.post(f"{BASE}/revisions/{rev['revision_id']}/accept", headers=h)).status_code == 200
    assert (await client.post(f"{est}/rules/starter", json={"country": "DE"}, headers=h)).status_code == 201
    assert (await client.post(f"{est}/run", headers=h)).status_code == 200
    p = _by_rule((await client.get(est, headers=h)).json())
    await _price(client, est, h, p["slab"]["position_id"], "120")
    await _price(client, est, h, p["wall_ext"]["position_id"], "10")
    await _set_quantity(p["wall_ext"]["position_id"], "90")
    s = (await client.get(est, headers=h)).json()
    mk = await client.post(
        f"/api/v1/boq/boqs/{s['boq_id']}/markups/",
        headers=h,
        json={"name": "Overhead", "category": "overhead", "percentage": 10, "apply_to": "direct_cost"},
    )
    assert mk.status_code in (200, 201), mk.text
    return h, pid, tok, s["boq_id"], rev


async def test_design_bill_is_the_cost_plan_and_the_rollup_to_the_cent(client):
    h, pid, _, boq_id, rev = await _priced_design(client)
    slab_pos = _by_rule((await client.get(f"{BASE}/projects/{pid}/estimate", headers=h)).json())["slab"]["position_id"]
    plan = await client.get(f"/api/v1/cost-plan/boqs/{boq_id}/nrm1", headers=h)
    assert plan.status_code == 200, plan.text
    body = plan.json()
    assert D(str(body["direct_cost"]["total"])) == D("49044")
    assert D(str(body["markups_total"]["total"])) == D("4904.40")
    assert D(str(body["grand_total"]["total"])) == D("53948.40")
    # drill-down: every row opens onto the positions it sums, and the rows add back to the direct cost
    codes = [g["code"] for g in body["groups"] + body["addon_groups"] if D(str(g["total"])) != 0]
    seen, drilled = set(), D("0")
    for code in [*codes, "unallocated"]:
        r = await client.get(f"/api/v1/cost-plan/boqs/{boq_id}/nrm1/sources", params={"code": code}, headers=h)
        assert r.status_code == 200, r.text
        rows = r.json()["positions"]
        assert sum(D(x["amount"]) for x in rows) == D(r.json()["total"])
        drilled += D(r.json()["total"])
        seen |= {x["position_id"] for x in rows}
        for x in rows:
            if x["position_id"] == slab_pos:
                assert D(x["amount"]) == D("48144") and x["provenance"]["module"] == "oe_design"
                assert x["provenance"]["rule"] == "slab" and x["provenance"]["revision_id"] == rev["revision_id"]
    assert drilled == D("49044") and slab_pos in seen
    roll = await client.get(f"/api/v1/estimate-rollup/projects/{pid}", headers=h)
    assert roll.status_code == 200, roll.text
    assert D(roll.json()["boq_base"]) == D("53948.40") and roll.json()["base_currency"] == "CHF"


async def test_design_bill_becomes_the_budget_baseline_and_its_cash_flow(client):
    h, pid, _, boq_id, rev = await _priced_design(client)
    b = await client.post(f"/api/v1/costmodel/projects/{pid}/5d/generate-budget/", json={"boq_id": boq_id}, headers=h)
    assert b.status_code == 201, b.text
    lines = b.json()
    budget = sum(D(str(line["planned_amount"])) for line in lines)
    # each budget line traces back: bill position -> design rule -> accepted revision
    slab = next(x for x in lines if (_meta(x)["provenance"]["origin"] or {}).get("rule") == "slab")
    src = _meta(slab)["provenance"]
    assert src["boq_position_id"] == slab["boq_position_id"] and D(src["rate"]["unit_rate"]) == 120
    assert src["origin"]["module"] == "oe_design" and src["origin"]["revision_id"] == rev["revision_id"]
    assert D(str(slab["planned_amount"])) == D("48144")  # 401.2 m2 x 120
    # the baseline carries the measured works (direct cost); markups stay on the bill
    assert budget == D("49044"), budget
    cf = await client.post(f"/api/v1/costmodel/projects/{pid}/5d/generate-cash-flow/", headers=h)
    assert cf.status_code == 201, cf.text
    # every franc of the baseline is paid out once in the forecast, scheduled or not
    entries = cf.json()
    assert sum(D(str(e["planned_outflow"])) for e in entries) == budget
    # each period names the budget lines it pays out, so a month of the curve opens onto its positions
    ids = {x["id"] for x in lines}
    for e in entries:
        parts = _meta(e)["sources"]
        assert parts and {p["budget_line_id"] for p in parts} <= ids
        assert sum(D(p["amount"]) for p in parts) == D(str(e["planned_outflow"]))  # to the cent, no float


async def test_accepted_revision_leaves_a_design_report_in_the_project_validation_view(client):
    h, pid, tok, _, rev1 = await _priced_design(client)
    d2, _ = package(pid, _rows2(), parent_id=rev1["revision_id"], parent_rows=example_rows())
    rev2 = (await _upload(client, pid, tok, d2)).json()
    assert (await client.post(f"{BASE}/revisions/{rev2['revision_id']}/accept", headers=h)).status_code == 200
    r = await client.get(
        "/api/v1/validation/reports/", params={"project_id": pid, "target_type": "design_project"}, headers=h
    )
    assert r.status_code == 200, r.text
    reports = r.json()
    # one stored run per accepted revision: R1 had no estimate yet (nothing to check), R2 checks the priced bill
    assert len(reports) == 2 and all(x["target_id"] == str(pid) and x["rule_set"] == "design" for x in reports)
    latest = reports[0]
    assert latest["status"] != "skipped" and latest["total_rules"] >= 1
    assert _meta(latest)["source"] == "design_accept"  # the run's origin, not a provenance record
    live = (await client.get(f"{BASE}/projects/{pid}/validation", headers=h)).json()
    assert latest["error_count"] == sum(1 for f in live["findings"] if f["severity"] == "error")


async def test_a_design_package_becomes_a_draft_rfq_whose_lines_name_their_source(client):
    uid, h, pid, tok = await _linked_project(client)
    d1, _ = package(pid, example_rows())
    rev = (await _upload(client, pid, tok, d1)).json()
    assert (await client.post(f"{BASE}/revisions/{rev['revision_id']}/accept", headers=h)).status_code == 200
    s = await client.post(f"{BASE}/projects/{pid}/procurement/setup", json={"group_by": "type_key"}, headers=h)
    assert s.status_code == 201, s.text
    wall = next(x for x in s.json()["lines"] if x["group_key"] == "wall/ext-masonry-365")
    made = await client.post(f"{BASE}/projects/{pid}/procurement/packages/IfcWall/rfq", headers=h)
    assert made.status_code == 201, made.text
    assert made.json()["status"] == "draft"  # a person checks and sends it
    rfq_id = made.json()["rfq_id"]
    again = await client.post(f"{BASE}/projects/{pid}/procurement/packages/IfcWall/rfq", headers=h)
    assert again.status_code == 409
    # read back through the RFQ module's own API
    one = await client.get(f"/api/v1/rfq-bidding/{rfq_id}", headers=h)
    assert one.status_code == 200, one.text
    assert _meta(one.json())["provenance"]["revision_id"] == rev["revision_id"]
    lines = (await client.get(f"/api/v1/rfq-bidding/{rfq_id}/lines/", headers=h)).json()
    lines = lines.get("items", lines) if isinstance(lines, dict) else lines
    [line] = lines
    src = _meta(line)["provenance"]
    # 82.5 m2 of external wall: the take-off quantity, from the accepted revision, on the bill position
    assert (line["unit"], D(str(line["quantity"]))) == ("m2", D("82.5"))
    assert src["module"] == "oe_design" and src["revision_id"] == rev["revision_id"]
    assert src["boq_position_id"] == wall["position_id"] and src["rule"] == "takeoff:wall/ext-masonry-365"
    assert D(src["quantity"]) == D("82.5") and src["quantity_override"] is False and src["basis"] == "area_m2"


async def _taken_off(client):
    uid, h, pid, tok = await _linked_project(client)
    d1, _ = package(pid, example_rows())
    rev = (await _upload(client, pid, tok, d1)).json()
    assert (await client.post(f"{BASE}/revisions/{rev['revision_id']}/accept", headers=h)).status_code == 200
    s = await client.post(f"{BASE}/projects/{pid}/procurement/setup", json={"group_by": "type_key"}, headers=h)
    assert s.status_code == 201, s.text
    return uid, h, pid


async def test_rfq_without_a_project_currency_is_refused_with_a_code(client):
    _, h, pid = await _taken_off(client)
    await _set_currency(pid, "")
    r = await client.post(f"{BASE}/projects/{pid}/procurement/packages/IfcWall/rfq", headers=h)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "project_currency_missing"
    await _set_currency(pid, "CHF")
    made = await client.post(f"{BASE}/projects/{pid}/procurement/packages/IfcWall/rfq", headers=h)
    assert made.status_code == 201, made.text
    one = (await client.get(f"/api/v1/rfq-bidding/{made.json()['rfq_id']}", headers=h)).json()
    assert one["currency_code"] == "CHF"


async def test_take_off_names_are_neutral_codes_with_an_i18n_key(client):
    import uuid

    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.boq.models import BOQ
    from app.modules.tendering.models import TenderPackage

    _, h, pid = await _taken_off(client)
    async with async_session_factory() as s:
        boq = (await s.execute(select(BOQ).where(BOQ.project_id == uuid.UUID(str(pid))))).scalars().all()
        pkgs = (await s.execute(select(TenderPackage).where(TenderPackage.project_id == uuid.UUID(str(pid))))).scalars()
        pkgs = list(pkgs)
    takeoff = next(b for b in boq if b.name == "design_takeoff")
    assert takeoff.metadata_["name_key"] == "design.takeoff.boq_name"
    wall = next(p for p in pkgs if p.name == "design_takeoff:IfcWall")
    assert wall.metadata_["name_key"] == "design.takeoff.package_name"
    assert wall.metadata_["name_params"] == {"ifc_class": "IfcWall"}
    assert all("Design take-off" not in (p.name + (p.description or "")) for p in pkgs)


async def test_two_rfq_requests_for_one_package_make_one_rfq(client):
    import asyncio
    import uuid

    from fastapi import HTTPException
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.design import procurement as prc
    from app.modules.rfq_bidding.models import RFQ

    uid, _, pid = await _taken_off(client)

    async def one():
        async with async_session_factory() as s:
            try:
                await prc.rfq_from_package(s, uuid.UUID(str(pid)), "IfcWall", uuid.UUID(str(uid)))
                await s.commit()
                return 201
            except HTTPException as exc:
                await s.rollback()
                return exc.status_code

    assert sorted(await asyncio.gather(one(), one())) == [201, 409]
    async with async_session_factory() as s:
        rows = (await s.execute(select(RFQ).where(RFQ.project_id == uuid.UUID(str(pid))))).scalars().all()
    assert len(rows) == 1


async def test_data_paths_show_design_reaching_documents_and_validation():
    from app.modules.design.data_paths import DATA_PATHS

    out = {p.module for p in DATA_PATHS.outputs}
    assert {
        "oe_boq",
        "oe_schedule",
        "oe_tendering",
        "oe_changeorders",
        "oe_documents",
        "oe_validation",
        "oe_rfq_bidding",
    } <= out


async def test_cash_flow_split_adds_back_to_the_cent():
    from app.modules.costmodel.service import split_cents

    assert split_cents(D("100"), 3) == [D("33.34"), D("33.33"), D("33.33")]
    assert sum(split_cents(D("48144"), 7)) == D("48144") and split_cents(D("-0.05"), 2) == [D("-0.03"), D("-0.02")]


async def test_provenance_has_one_shape():
    from app.core import record_provenance as provenance

    p = provenance.make("model_rule", "oe_design", revision_id="r", rule="slab", field="area_m2")
    assert provenance.read({"provenance": p}) == p
    # another module's plain-string "source" is not mistaken for a provenance record
    assert provenance.read({"source": "risk_contingency"}) is None and provenance.read({"provenance": "x"}) is None


async def test_recompute_writes_each_position_once(client, monkeypatch):
    from app.modules.boq.repository import PositionRepository

    h, pid, tok, _, rev1 = await _priced_design(client)
    calls: list[str] = []
    orig = PositionRepository.update_fields

    async def counting(self, position_id, **fields):
        calls.append(str(position_id))
        return await orig(self, position_id, **fields)

    monkeypatch.setattr(PositionRepository, "update_fields", counting)
    assert (await client.post(f"{BASE}/projects/{pid}/estimate/run", headers=h)).status_code == 200
    assert calls and max(calls.count(x) for x in set(calls)) == 1
