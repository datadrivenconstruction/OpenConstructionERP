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
    h, pid, _, boq_id, _ = await _priced_design(client)
    plan = await client.get(f"/api/v1/cost-plan/boqs/{boq_id}/nrm1", headers=h)
    assert plan.status_code == 200, plan.text
    body = plan.json()
    assert D(str(body["direct_cost"]["total"])) == D("49044")
    assert D(str(body["markups_total"]["total"])) == D("4904.40")
    assert D(str(body["grand_total"]["total"])) == D("53948.40")
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
    slab = next(x for x in lines if (_meta(x)["source"]["origin"] or {}).get("rule") == "slab")
    src = _meta(slab)["source"]
    assert src["boq_position_id"] == slab["boq_position_id"] and D(src["unit_rate"]) == 120
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
        assert abs(sum(D(p["amount"]) for p in parts) - D(str(e["planned_outflow"]))) <= D("0.01") * len(parts)


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
    assert _meta(latest)["source"] == "design_accept"
    live = (await client.get(f"{BASE}/projects/{pid}/validation", headers=h)).json()
    assert latest["error_count"] == sum(1 for f in live["findings"] if f["severity"] == "error")


async def test_data_paths_show_design_reaching_documents_and_validation():
    from app.modules.design.data_paths import DATA_PATHS

    out = {p.module for p in DATA_PATHS.outputs}
    assert {"oe_boq", "oe_schedule", "oe_tendering", "oe_changeorders", "oe_documents", "oe_validation"} <= out
