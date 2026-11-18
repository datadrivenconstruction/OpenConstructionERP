# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Mine survey course, lessons 1-5, through the API on PostgreSQL, on the installed Riverside Yard demo."""

from __future__ import annotations

import json
from pathlib import Path

from httpx import AsyncClient

from tests.modules.survey_core.conftest import (  # noqa: F401
    app_instance,
    client,
    header,
    login,
    project_id,
    viewer,
)

BASE = "/api/v1/mine-survey"
VOL = "/api/v1/surfaces-volumes"
DEMO = Path(__file__).resolve().parents[3] / "app" / "modules" / "survey_core" / "demo" / "riverside"
EXPECTED = json.loads((DEMO / "expected.json").read_text(encoding="utf-8"))["mine_survey"]


async def _demo(client: AsyncClient, header: dict) -> tuple[str, dict, dict]:
    installed = await client.post("/api/demo/install/survey-riverside-yard", headers=header)
    assert installed.status_code in (200, 201), installed.text
    pid = installed.json()["project_id"]
    [period] = (await client.get(f"{BASE}/projects/{pid}/periods", headers=header)).json()["items"]
    detail = (await client.get(f"{BASE}/periods/{period['id']}", headers=header)).json()
    return pid, period, detail


async def test_lesson_1_the_demo_seeds_the_october_plan(client: AsyncClient, header: dict) -> None:
    _, period, detail = await _demo(client, header)
    assert period["label"] == EXPECTED["period_label"]
    assert period["profile_label"] == "Demo values, not a standard"
    [entry] = detail["entries"]
    assert entry["unit_name"] == EXPECTED["unit"]
    assert entry["plan_m3"] == EXPECTED["lesson_1"]["plan_m3"]
    assert entry["plan_t"] == EXPECTED["lesson_1"]["plan_t"]
    assert entry["actual_m3"] is None
    assert entry["actual"] is None


async def test_lessons_2_to_5_actual_compliance_trucks_and_claim(client: AsyncClient, header: dict) -> None:
    pid, _, detail = await _demo(client, header)
    entry = detail["entries"][0]
    surfaces = (await client.get(f"{VOL}/projects/{pid}/surfaces", headers=header)).json()["items"]
    by_name = {s["name"]: s["id"] for s in surfaces}

    l2 = EXPECTED["lesson_2"]
    computed = await client.post(
        f"{BASE}/entries/{entry['id']}/compute-actual",
        json={
            "start_surface_id": by_name["Pit N 2026-10-01"],
            "end_surface_id": by_name["Pit N 2026-10-31"],
            "cell_size_m": l2["cell_size_m"],
        },
        headers=header,
    )
    assert computed.status_code == 200, computed.text
    e = computed.json()
    assert e["actual_m3"] == l2["actual_m3"]
    assert e["actual"]["coverage_pct"] == l2["coverage_pct"]
    assert e["actual"]["status"] == "draft"

    l3 = EXPECTED["lesson_3"]
    assert e["compliance_pct"] == l3["compliance_pct"]
    assert l3["finding"] in {f["rule_id"] for f in e["findings"]}

    early = await client.post(
        f"{BASE}/entries/{entry['id']}/add-to-claim", json={"position_id": entry["id"]}, headers=header
    )
    assert early.status_code == 409

    l4 = EXPECTED["lesson_4"]
    trucks = await client.post(
        f"{BASE}/entries/{entry['id']}/truck-loads",
        json={"text": (DEMO / EXPECTED["truck_file"]).read_text(encoding="utf-8"), "filename": EXPECTED["truck_file"]},
        headers=header,
    )
    assert trucks.status_code == 200, trucks.text
    t = trucks.json()
    assert (t["truck_loads"], t["truck_t"], t["survey_t"]) == (l4["loads"], l4["truck_t"], l4["survey_t"])
    assert t["truck_factor_pct"] == l4["truck_factor_pct"]
    assert l4["finding"] in {f["rule_id"] for f in t["findings"]}

    confirmed = await client.post(f"{BASE}/entries/{entry['id']}/confirm-actual", json={}, headers=header)
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["actual"]["status"] == "confirmed"
    assert confirmed.json()["actual"]["confirmed_by_name"]

    [pos] = (
        await client.get(f"{VOL}/projects/{pid}/boq-positions", params={"q": "Bulk excavation"}, headers=header)
    ).json()["items"]
    claim = await client.post(
        f"{BASE}/entries/{entry['id']}/add-to-claim", json={"position_id": pos["id"]}, headers=header
    )
    assert claim.status_code == 200, claim.text
    assert claim.json()["quantity_m3"] == EXPECTED["lesson_5"]["claim_quantity_m3"]
    entries = await client.get("/api/v1/progress/entries/", params={"project_id": pid}, headers=header)
    assert any(x["id"] == claim.json()["progress_entry_id"] for x in entries.json())

    again = await client.post(
        f"{BASE}/entries/{entry['id']}/compute-actual",
        json={"start_surface_id": by_name["Pit N 2026-10-01"], "end_surface_id": by_name["Pit N 2026-10-31"]},
        headers=header,
    )
    assert again.status_code == 409

    period = (await client.get(f"{BASE}/periods/{entry['period_id']}", headers=header)).json()
    assert period["totals"]["compliance_pct"] == EXPECTED["lesson_3"]["compliance_pct"]
    assert period["totals"]["truck_factor_pct"] == l4["truck_factor_pct"]
    assert period["entries"][0]["claim_entry_id"] == claim.json()["progress_entry_id"]

    pdf = await client.get(f"{BASE}/periods/{entry['period_id']}/report.pdf", headers=header)
    assert pdf.status_code == 200
    assert pdf.content[:5] == b"%PDF-"


async def test_confirm_and_claim_need_the_survey_permission(client: AsyncClient, header: dict, viewer: dict) -> None:
    _, _, detail = await _demo(client, header)
    entry = detail["entries"][0]
    denied = await client.post(f"{BASE}/entries/{entry['id']}/confirm-actual", json={}, headers=viewer)
    assert denied.status_code == 403
    denied = await client.post(
        f"{BASE}/entries/{entry['id']}/add-to-claim", json={"position_id": entry["id"]}, headers=viewer
    )
    assert denied.status_code == 403
    write = await client.patch(f"{BASE}/entries/{entry['id']}", json={"note": "x"}, headers=viewer)
    assert write.status_code == 403


async def test_a_period_is_unique_per_month_and_a_unit_per_period(
    client: AsyncClient, header: dict, project_id: str
) -> None:
    body = {"label": "2026-09", "band_lo_pct": 95, "band_hi_pct": 105}
    first = await client.post(f"{BASE}/projects/{project_id}/periods", json=body, headers=header)
    assert first.status_code == 201, first.text
    dup = await client.post(f"{BASE}/projects/{project_id}/periods", json=body, headers=header)
    assert dup.status_code == 409
    line = {"unit_name": "Block 7", "unit_type": "block", "plan_m3": 1000, "density_t_m3": 2.4}
    ok = await client.post(f"{BASE}/periods/{first.json()['id']}/entries", json=line, headers=header)
    assert ok.status_code == 201, ok.text
    assert ok.json()["plan_t"] == 2400.0
    again = await client.post(f"{BASE}/periods/{first.json()['id']}/entries", json=line, headers=header)
    assert again.status_code == 409
    bad = await client.post(
        f"{BASE}/projects/{project_id}/periods", json={"label": "2026-08", "band_lo_pct": 95}, headers=header
    )
    assert bad.status_code == 422
