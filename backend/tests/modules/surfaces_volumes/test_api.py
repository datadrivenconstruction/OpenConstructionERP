# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Volumes course, lessons 1-6, through the API on PostgreSQL.

Lessons 1-3 build the surfaces and the volume by hand; lessons 4-6 run on the
installed Riverside Yard demo, which also proves the demo seed.
"""

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

BASE = "/api/v1/surfaces-volumes"
CORE = "/api/v1/survey-core"
DEMO = Path(__file__).resolve().parents[3] / "app" / "modules" / "survey_core" / "demo" / "riverside"
EXPECTED = json.loads((DEMO / "expected.json").read_text(encoding="utf-8"))["volumes"]


def _file(name: str) -> str:
    return (DEMO / name).read_text(encoding="utf-8")


async def _surfaces(client: AsyncClient, header: dict, project_id: str) -> tuple[dict, dict]:
    r = await client.put(f"{CORE}/projects/{project_id}/crs", json={"horizontal_epsg": 32633}, headers=header)
    assert r.status_code == 200, r.text
    r = await client.post(
        f"{CORE}/projects/{project_id}/import",
        json={
            "text": _file("existing_ground.csv"),
            "filename": "existing_ground.csv",
            "column_preset": "PNEZD",
            "delimiter": ",",
            "name": "Existing ground",
        },
        headers=header,
    )
    assert r.status_code == 201, r.text
    set_id = r.json()["point_set"]["id"]
    eg = await client.post(
        f"{BASE}/projects/{project_id}/surfaces/from-points",
        json={"name": "Existing ground", "point_set_ids": [set_id]},
        headers=header,
    )
    assert eg.status_code == 201, eg.text
    pad = await client.post(
        f"{BASE}/projects/{project_id}/surfaces/landxml",
        json={"text": _file("design_pad.xml"), "filename": "design_pad.xml", "name": "Pad"},
        headers=header,
    )
    assert pad.status_code == 201, pad.text
    return eg.json(), pad.json()["surfaces"][0]


async def test_lessons_1_to_3_surfaces_and_the_volume(client: AsyncClient, header: dict, project_id: str) -> None:
    eg, pad = await _surfaces(client, header, project_id)
    assert eg["point_count"] == EXPECTED["lesson_1"]["points"]
    assert eg["area_m2"] == EXPECTED["lesson_1"]["area_m2"]
    assert pad["area_m2"] == EXPECTED["lesson_2"]["area_m2"]
    assert pad["z_min"] == pad["z_max"] == EXPECTED["lesson_2"]["z"]

    lesson = EXPECTED["lesson_3"]
    r = await client.post(
        f"{BASE}/projects/{project_id}/volumes",
        json={"name": lesson["name"], "base_surface_id": eg["id"], "compare_surface_id": pad["id"]},
        headers=header,
    )
    assert r.status_code == 201, r.text
    v = r.json()
    assert v["code"] == lesson["code"]
    assert v["method"] == lesson["method"]
    assert v["cell_size_m"] == lesson["cell_size_m"]
    assert (v["cut_m3"], v["fill_m3"], v["net_m3"]) == (lesson["cut_m3"], lesson["fill_m3"], lesson["net_m3"])
    assert v["coverage_pct"] == lesson["coverage_pct"]
    assert v["status"] == "draft"
    assert v["confidence"] == 1.0
    assert {f["rule_id"] for f in v["findings"]} == {"VOL-004"}

    plan = await client.get(f"{BASE}/projects/{project_id}/plan", params={"volume_id": v["id"]}, headers=header)
    layers = {f["properties"]["layer"] for f in plan.json()["features"]}
    assert layers == {"points", "surfaces", "heat"}
    assert plan.json()["properties"]["epsg"] == 32633

    # The TIN method has no cell grid, so it carries no heat layer.
    tin = await client.patch(f"{BASE}/volumes/{v['id']}", json={"method": "tin"}, headers=header)
    assert tin.status_code == 200, tin.text
    assert (tin.json()["cut_m3"], tin.json()["fill_m3"]) == (lesson["cut_m3"], lesson["fill_m3"])

    summary = await client.get(f"{BASE}/projects/{project_id}/summary", headers=header)
    assert summary.json()["calculations"] == 1
    assert summary.json()["surfaces"] == 2


async def test_confirm_needs_the_permission_and_locks_the_result(
    client: AsyncClient, header: dict, project_id: str, viewer: dict
) -> None:
    eg, pad = await _surfaces(client, header, project_id)
    v = (
        await client.post(
            f"{BASE}/projects/{project_id}/volumes",
            json={"name": "Check", "base_surface_id": eg["id"], "compare_surface_id": pad["id"]},
            headers=header,
        )
    ).json()
    denied = await client.post(f"{BASE}/volumes/{v['id']}/confirm", json={}, headers=viewer)
    assert denied.status_code == 403
    early = await client.post(f"{BASE}/volumes/{v['id']}/send-to-boq", json={"position_id": v["id"]}, headers=header)
    assert early.status_code == 409
    ok = await client.post(f"{BASE}/volumes/{v['id']}/confirm", json={}, headers=header)
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "confirmed"
    assert ok.json()["confirmed_by_name"]
    locked = await client.patch(f"{BASE}/volumes/{v['id']}", json={"method": "tin"}, headers=header)
    assert locked.status_code == 409
    gone = await client.delete(f"{BASE}/surfaces/{eg['id']}", headers=header)
    assert gone.status_code == 409


async def test_low_coverage_must_be_acknowledged(client: AsyncClient, header: dict, project_id: str) -> None:
    eg, pad = await _surfaces(client, header, project_id)
    # A boundary twice the pad: half the area has no data.
    ring = [[389000.0, 5819000.0], [389200.0, 5819000.0], [389200.0, 5819060.0], [389000.0, 5819060.0]]
    v = (
        await client.post(
            f"{BASE}/projects/{project_id}/volumes",
            json={"name": "Wide", "base_surface_id": eg["id"], "compare_surface_id": pad["id"], "boundary": ring},
            headers=header,
        )
    ).json()
    assert v["coverage_pct"] == 50.0
    assert "VOL-002" in {f["rule_id"] for f in v["findings"]}
    blocked = await client.post(f"{BASE}/volumes/{v['id']}/confirm", json={}, headers=header)
    assert blocked.status_code == 409
    assert "VOL-002" in blocked.text
    ok = await client.post(f"{BASE}/volumes/{v['id']}/confirm", json={"acknowledge": ["VOL-002"]}, headers=header)
    assert ok.status_code == 200, ok.text


async def test_lessons_4_to_6_on_the_demo(client: AsyncClient, header: dict) -> None:
    installed = await client.post("/api/demo/install/survey-riverside-yard", headers=header)
    assert installed.status_code in (200, 201), installed.text
    pid = installed.json()["project_id"]
    [v] = (await client.get(f"{BASE}/projects/{pid}/volumes", headers=header)).json()["items"]
    assert v["code"] == "V-001"
    assert v["cut_m3"] == EXPECTED["lesson_3"]["cut_m3"]
    profile = (await client.get(f"{CORE}/projects/{pid}/profile", headers=header)).json()
    assert profile["label"] == "Demo values, not a standard"
    [trav] = (await client.get(f"{CORE}/projects/{pid}/traverses", headers=header)).json()["items"]
    assert trav["ratio"] == 11731
    assert trav["verdict"] == "pass"

    lesson = EXPECTED["lesson_4"]
    confirmed = await client.post(f"{BASE}/volumes/{v['id']}/confirm", json={}, headers=header)
    assert confirmed.status_code == 200, confirmed.text
    [pos] = (
        await client.get(f"{BASE}/projects/{pid}/boq-positions", params={"q": lesson["boq_position"]}, headers=header)
    ).json()["items"]
    sent = await client.post(
        f"{BASE}/volumes/{v['id']}/send-to-boq", json={"position_id": pos["id"], "quantity": "cut"}, headers=header
    )
    assert sent.status_code == 200, sent.text
    assert sent.json()["quantity"] == lesson["quantity"]
    assert sent.json()["formula"] == lesson["formula"]
    assert sent.json()["source"]["confirmed_by"]
    assert lesson["finding"] in {f["rule_id"] for f in sent.json()["findings"]}

    progress = await client.post(f"{BASE}/volumes/{v['id']}/record-progress", json={}, headers=header)
    assert progress.status_code == 200, progress.text
    assert progress.json()["quantity_m3"] == EXPECTED["lesson_5"]["progress_m3"]
    entries = await client.get("/api/v1/progress/entries/", params={"project_id": pid}, headers=header)
    assert any(e["id"] == progress.json()["entry_id"] for e in entries.json())

    dup = await client.post(f"{BASE}/volumes/{v['id']}/duplicate", json={"swell_factor": 1.25}, headers=header)
    assert dup.status_code == 201, dup.text
    assert dup.json()["loose_cut_m3"] == EXPECTED["lesson_6"]["loose_cut_m3"]

    history = (await client.get(f"{BASE}/volumes/{v['id']}/history", headers=header)).json()["items"]
    assert [h["action"] for h in history] == ["computed", "confirmed", "sent_boq", "progress", "duplicated"]
    pdf = await client.get(f"{BASE}/volumes/{v['id']}/report.pdf", headers=header)
    assert pdf.status_code == 200
    assert pdf.content[:5] == b"%PDF-"
