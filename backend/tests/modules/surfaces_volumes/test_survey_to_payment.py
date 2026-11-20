# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Course "Earthworks: from survey to payment" on the installed Riverside Yard demo.

The numbers come from ``survey_core/demo/riverside/expected.json`` (``payment``):
the measured cut goes into the open certificate after a preview, loose cut over
the bill raises MQ-001, the haul tickets linked to V-001 compare with its
excavated volume, and the haulier invoice shows its one deliberate mismatch.
"""

from __future__ import annotations

import json
from pathlib import Path

from httpx import AsyncClient

from tests.modules.survey_core.conftest import (  # noqa: F401
    app_instance,
    client,
    header,
    project_id,
    viewer,
)

VOL = "/api/v1/surfaces-volumes"
HAUL = "/api/v1/haul_tickets"
CON = "/api/v1/contracts"
MINE = "/api/v1/mine-survey"
DEMO = Path(__file__).resolve().parents[3] / "app" / "modules" / "survey_core" / "demo" / "riverside"
PAY = json.loads((DEMO / "expected.json").read_text(encoding="utf-8"))["payment"]


async def _demo(client: AsyncClient, header: dict) -> tuple[str, dict, dict]:
    """A fresh demo project: the reinstall drops what an earlier test certified or duplicated."""
    installed = await client.post("/api/demo/install/survey-riverside-yard?force=true", headers=header)
    assert installed.status_code in (200, 201), installed.text
    pid = installed.json()["project_id"]
    [v] = (await client.get(f"{VOL}/projects/{pid}/volumes", headers=header)).json()["items"]
    [pos] = (
        await client.get(f"{VOL}/projects/{pid}/boq-positions", params={"q": "Bulk excavation"}, headers=header)
    ).json()["items"]
    return pid, v, pos


async def test_measured_cut_goes_into_the_open_certificate(client: AsyncClient, header: dict) -> None:
    pid, v, pos = await _demo(client, header)
    early = await client.post(
        f"{VOL}/volumes/{v['id']}/certify/preview", json={"position_id": pos["id"]}, headers=header
    )
    assert early.status_code == 409  # a draft result feeds nothing
    assert (await client.post(f"{VOL}/volumes/{v['id']}/confirm", json={}, headers=header)).status_code == 200

    lesson = PAY["lesson_1"]
    body = {"position_id": pos["id"], "quantity": lesson["quantity_kind"]}
    preview = await client.post(f"{VOL}/volumes/{v['id']}/certify/preview", json=body, headers=header)
    assert preview.status_code == 200, preview.text
    p = preview.json()
    c = PAY["contract"]
    assert p["quantity"] == lesson["quantity"]
    assert p["contract"]["code"].startswith(c["code"])
    assert p["line"]["total_value"] == "14250.0000"
    assert (p["claim"]["number"], p["claim"]["status"]) == (c["certificate"]["number"], "draft")
    assert p["figures"]["percent_to_date"] == lesson["percent_to_date"]
    assert p["figures"]["period_qty"] == lesson["period_qty"]
    assert p["figures"]["period_value"] == lesson["period_value"]
    assert [f["rule_id"] for f in p["findings"]] == lesson["findings"]
    assert p["can_commit"] is True
    # Preview wrote nothing.
    lines = await client.get(f"{CON}/progress-claims/{p['claim']['id']}/lines", headers=header)
    assert lines.status_code == 200, lines.text
    assert lines.json() == [] or lines.json().get("items", []) == []

    done = await client.post(f"{VOL}/volumes/{v['id']}/certify", json=body, headers=header)
    assert done.status_code == 200, done.text
    claim = done.json()["claim"]
    totals = PAY["lesson_2"]
    assert (claim["gross_amount"], claim["retention_amount"], claim["net_due"]) == (
        totals["gross_amount"] + "00",
        totals["retention_amount"] + "00",
        totals["net_due"] + "00",
    )
    assert done.json()["progress_entry_id"]
    history = (await client.get(f"{VOL}/volumes/{v['id']}/history", headers=header)).json()["items"]
    assert [h["action"] for h in history][-2:] == ["progress", "certified"]

    # Populate-from-progress reads the same measured entry: nothing is left to bill twice.
    populate = await client.get(f"{CON}/progress-claims/{claim['id']}/populate-from-progress", headers=header)
    assert populate.status_code == 200, populate.text
    assert populate.json()["items"] == []

    # Loose cut over the bill: a warning a person reads, the line caps at its value.
    loose = PAY["lesson_3"]
    dup = await client.post(f"{VOL}/volumes/{v['id']}/duplicate", json={"swell_factor": 1.25}, headers=header)
    assert dup.status_code == 201, dup.text
    v2 = dup.json()
    assert (await client.post(f"{VOL}/volumes/{v2['id']}/confirm", json={}, headers=header)).status_code == 200
    over = await client.post(
        f"{VOL}/volumes/{v2['id']}/certify/preview",
        json={"position_id": pos["id"], "quantity": loose["quantity_kind"]},
        headers=header,
    )
    assert over.status_code == 200, over.text
    assert over.json()["quantity"] == loose["quantity"]
    assert [f["rule_id"] for f in over.json()["findings"]] == [loose["finding"]]
    assert over.json()["findings"][0]["key"] == "over_boq"
    assert over.json()["figures"]["capped"] is True
    assert over.json()["figures"]["period_value"] == loose["period_value"]
    assert over.json()["can_commit"] is True

    # A submitted certificate is locked: the preview says so and the write is refused.
    submitted = await client.post(f"{CON}/progress-claims/{claim['id']}/submit", headers=header)
    assert submitted.status_code == 200, submitted.text
    locked = await client.post(f"{VOL}/volumes/{v['id']}/certify/preview", json=body, headers=header)
    assert "MQ-003" in {f["rule_id"] for f in locked.json()["findings"]}
    assert locked.json()["can_commit"] is False
    refused = await client.post(f"{VOL}/volumes/{v['id']}/certify", json=body, headers=header)
    assert refused.status_code == 409
    assert "MQ-003" in refused.text


async def test_certify_needs_contract_rights(client: AsyncClient, header: dict, viewer: dict) -> None:
    _pid, v, pos = await _demo(client, header)
    await client.post(f"{VOL}/volumes/{v['id']}/confirm", json={}, headers=header)
    denied = await client.post(f"{VOL}/volumes/{v['id']}/certify", json={"position_id": pos["id"]}, headers=viewer)
    assert denied.status_code == 403


async def test_hauled_vs_excavated_and_the_invoice_mismatch(client: AsyncClient, header: dict) -> None:
    pid, v, _pos = await _demo(client, header)
    lesson = PAY["lesson_4"]
    r = await client.get(f"{HAUL}/projects/{pid}/hauled-vs-excavated", params={"volume_id": v["id"]}, headers=header)
    assert r.status_code == 200, r.text
    bank = r.json()
    assert (bank["tickets"], bank["loads"], bank["hauled_m3"]) == (
        lesson["tickets"],
        lesson["loads"],
        lesson["hauled_m3"],
    )
    by = {b["basis"]: b["hauled_m3"] for b in bank["by_basis"]}
    assert by == {"weighbridge": lesson["weighbridge_m3"], "capacity": lesson["capacity_m3"]}
    assert bank["excavated_basis"] == "bank_cut"
    assert bank["excavated_m3"] == lesson["bank"]["excavated_m3"]
    assert bank["difference_m3"] == lesson["bank"]["difference_m3"]
    assert bank["difference_pct"] == lesson["bank"]["difference_pct"]
    assert bank["threshold_pct"] == lesson["threshold_pct"]
    assert bank["within_threshold"] is False
    assert [f["rule_id"] for f in bank["findings"]] == [lesson["bank"]["finding"]]

    # The duplicate with the swell factor measures the same cut, so the same tickets count.
    await client.post(f"{VOL}/volumes/{v['id']}/confirm", json={}, headers=header)
    dup = await client.post(
        f"{VOL}/volumes/{v['id']}/duplicate", json={"swell_factor": lesson["loose"]["swell_factor"]}, headers=header
    )
    loose = (
        await client.get(
            f"{HAUL}/projects/{pid}/hauled-vs-excavated", params={"volume_id": dup.json()["id"]}, headers=header
        )
    ).json()
    assert loose["excavated_basis"] == "loose_cut"
    assert loose["excavated_m3"] == lesson["loose"]["excavated_m3"]
    assert loose["difference_m3"] == lesson["loose"]["difference_m3"]
    assert loose["difference_pct"] == lesson["loose"]["difference_pct"]
    assert loose["within_threshold"] is True
    assert loose["findings"] == []

    # A tighter threshold set by the project flags the loose comparison too.
    settings = (await client.get(f"{HAUL}/projects/{pid}/settings", headers=header)).json()
    assert settings["haul_variance_pct"] == lesson["threshold_pct"]
    settings["haul_variance_pct"] = 5
    put = await client.put(f"{HAUL}/projects/{pid}/settings", json=settings, headers=header)
    assert put.status_code == 200, put.text
    tight = (
        await client.get(
            f"{HAUL}/projects/{pid}/hauled-vs-excavated", params={"volume_id": dup.json()["id"]}, headers=header
        )
    ).json()
    assert tight["within_threshold"] is False

    invoices = (await client.get(f"{HAUL}/projects/{pid}/invoices", headers=header)).json()["items"]
    [inv] = invoices
    expected = PAY["lesson_5"]
    assert inv["status"] == expected["invoice_status"]
    statuses = {line["ticket_number"]: line["status"] for line in inv["result"]["lines"]}
    assert statuses.pop(expected["mismatch_ticket"]) == expected["mismatch_status"]
    assert set(statuses.values()) == {"matched"}
    assert inv["result"]["invoiced_total"] == expected["invoiced_total"]
    assert inv["result"]["expected_total"] == expected["expected_total"]


async def test_stockpile_panel_and_ticket_links(client: AsyncClient, header: dict) -> None:
    pid, v, _pos = await _demo(client, header)
    [pile] = (await client.get(f"/api/v1/stockpiles/projects/{pid}/stockpiles", headers=header)).json()["items"]
    empty = await client.get(
        f"{HAUL}/projects/{pid}/hauled-vs-excavated", params={"stockpile_id": pile["id"]}, headers=header
    )
    assert empty.status_code == 200, empty.text
    assert (empty.json()["tickets"], empty.json()["difference_pct"]) == (0, None)
    tickets = (await client.get(f"{HAUL}/projects/{pid}/tickets", headers=header)).json()["items"]
    t = tickets[0]
    assert t["survey_volume_id"] == v["id"]
    # A verified ticket stays locked for figures but can be linked to where the load came from.
    linked = await client.patch(f"{HAUL}/tickets/{t['id']}", json={"stockpile_id": pile["id"]}, headers=header)
    assert linked.status_code == 200, linked.text
    figures = await client.patch(f"{HAUL}/tickets/{t['id']}", json={"loads": 99}, headers=header)
    assert figures.status_code == 409
    foreign = await client.patch(f"{HAUL}/tickets/{t['id']}", json={"stockpile_id": v["id"]}, headers=header)
    assert foreign.status_code == 422
    one = (
        await client.get(
            f"{HAUL}/projects/{pid}/hauled-vs-excavated", params={"stockpile_id": pile["id"]}, headers=header
        )
    ).json()
    assert one["tickets"] == 1
    both = await client.get(f"{HAUL}/projects/{pid}/hauled-vs-excavated", headers=header)
    assert both.status_code == 422


async def test_mine_period_offers_its_chosen_quantity(client: AsyncClient, header: dict) -> None:
    pid, _v, pos = await _demo(client, header)
    periods = (await client.get(f"{MINE}/projects/{pid}/periods", headers=header)).json()["items"]
    detail = (await client.get(f"{MINE}/periods/{periods[0]['id']}", headers=header)).json()
    entry = detail["entries"][0]
    body = {"position_id": pos["id"], "quantity": "cut"}
    early = await client.post(f"{MINE}/entries/{entry['id']}/certify/preview", json=body, headers=header)
    assert early.status_code == 409
    surfaces = (await client.get(f"{VOL}/projects/{pid}/surfaces", headers=header)).json()["items"]
    by_name = {s["name"]: s["id"] for s in surfaces}
    computed = await client.post(
        f"{MINE}/entries/{entry['id']}/compute-actual",
        json={"start_surface_id": by_name["Pit N 2026-10-01"], "end_surface_id": by_name["Pit N 2026-10-31"]},
        headers=header,
    )
    assert computed.status_code == 200, computed.text
    assert (
        await client.post(f"{MINE}/entries/{entry['id']}/confirm-actual", json={}, headers=header)
    ).status_code == 200
    preview = await client.post(f"{MINE}/entries/{entry['id']}/certify/preview", json=body, headers=header)
    assert preview.status_code == 200, preview.text
    # 11 870 m3 against a bill of 1 500 m3: the warning shows and the line caps at its value.
    assert "MQ-001" in {f["rule_id"] for f in preview.json()["findings"]}
    assert preview.json()["figures"]["capped"] is True
