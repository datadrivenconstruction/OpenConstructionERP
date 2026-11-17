# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Setting-out end to end on the Riverside Yard lessons, against a real database.

Lesson numbers come from ``demo/riverside/expected.json``: the course reads
the same file, so a change here that breaks a lesson fails this suite.
"""

from __future__ import annotations

import json
from pathlib import Path

from httpx import AsyncClient

BASE = "/api/v1/setting-out"
DEMO = Path(__file__).resolve().parents[3] / "app" / "modules" / "setting_out" / "demo" / "riverside"
EXPECTED = json.loads((DEMO / "expected.json").read_text(encoding="utf-8"))["setting_out"]


async def _demo(client: AsyncClient, header: dict, project_id: str) -> dict:
    response = await client.post(f"{BASE}/projects/{project_id}/demo/riverside", headers=header)
    assert response.status_code == 200, response.text
    return response.json()


def _stake(detail: dict, pid: str) -> dict:
    return next(s for s in detail["stakes"] if s["point_id"] == pid)


async def _measure(client: AsyncClient, header: dict, stake_id: str, lesson: dict) -> dict:
    m = lesson["measured"]
    response = await client.post(
        f"{BASE}/stakes/{stake_id}/records",
        json={"measured_e": m["e"], "measured_n": m["n"], "measured_z": m["z"]},
        headers=header,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_lesson_1_open_request(client: AsyncClient, header: dict, project_id: str) -> None:
    lesson = EXPECTED["lesson_1"]
    detail = await _demo(client, header, project_id)
    assert detail["name"] == lesson["request"]
    assert detail["point_count"] == lesson["points"]
    assert detail["tolerance_label"] == lesson["tolerance_label"]
    assert detail["tol_h_mm"] == lesson["tolerance_mm"]
    assert detail["alignment"]["name"] == lesson["alignment"]
    for pid, ch in lesson["chainage"].items():
        assert _stake(detail, pid)["chainage"] == ch
    again = await _demo(client, header, project_id)
    assert again["id"] == detail["id"]
    assert again["point_count"] == lesson["points"]


async def test_lessons_2_to_4_pass_fail_ncr_sheet(client: AsyncClient, header: dict, project_id: str) -> None:
    detail = await _demo(client, header, project_id)
    l2, l3 = EXPECTED["lesson_2"], EXPECTED["lesson_3"]

    rec = await _measure(client, header, _stake(detail, l2["point"])["id"], l2)
    assert (rec["d_mm"], rec["dz_mm"], rec["verdict"]) == (l2["d_mm"], l2["dz_mm"], l2["verdict"])
    assert rec["instrument"] and rec["control_ref"]

    rec = await _measure(client, header, _stake(detail, l3["point"])["id"], l3)
    assert (rec["d_mm"], rec["dz_mm"], rec["verdict"]) == (l3["d_mm"], l3["dz_mm"], l3["verdict"])

    report = (await client.post(f"{BASE}/projects/{project_id}/validate", headers=header)).json()
    assert [f["rule_id"] for f in report["findings"]] == [l3["rule"]]
    assert report["findings"][0]["message"] == l3["finding"]

    ncr = await client.post(f"{BASE}/records/{rec['id']}/ncr", headers=header)
    assert ncr.status_code == 201, ncr.text
    again = await client.post(f"{BASE}/records/{rec['id']}/ncr", headers=header)
    assert again.status_code == 409
    quality = await client.get(f"/api/v1/ncr/?project_id={project_id}", headers=header)
    if quality.status_code == 200:
        body = quality.json()
        items = body if isinstance(body, list) else body.get("items", [])
        hit = next(i for i in items if i["id"] == ncr.json()["ncr_id"])
        assert hit["ncr_type"] == l3["ncr_type"]
        assert hit["title"] == l3["finding"]

    kpi = (await client.get(f"{BASE}/projects/{project_id}/summary", headers=header)).json()
    assert {k: kpi[k] for k in ("open", "passed", "failed", "ncr_drafts")} == EXPECTED["kpi_after_lessons"]

    sheet = await client.get(f"{BASE}/requests/{detail['id']}/sheet.pdf", headers=header)
    assert sheet.status_code == 200
    assert sheet.headers["content-type"] == "application/pdf"
    assert sheet.content.startswith(b"%PDF")


async def test_passed_record_cannot_open_ncr(client: AsyncClient, header: dict, project_id: str) -> None:
    detail = await _demo(client, header, project_id)
    rec = await _measure(client, header, _stake(detail, "C-04")["id"], EXPECTED["lesson_2"])
    response = await client.post(f"{BASE}/records/{rec['id']}/ncr", headers=header)
    assert response.status_code == 409


async def test_measured_csv_import_and_history(client: AsyncClient, header: dict, project_id: str) -> None:
    detail = await _demo(client, header, project_id)
    text = (DEMO / "stakeout_measured.csv").read_text(encoding="utf-8")
    result = await client.post(f"{BASE}/requests/{detail['id']}/measured", json={"text": text}, headers=header)
    assert result.status_code == 200, result.text
    assert (result.json()["recorded"], result.json()["passed"], result.json()["failed"]) == (2, 1, 1)
    c03 = _stake(detail, "C-03")["id"]
    await _measure(
        client, header, c03, EXPECTED["lesson_2"] | {"measured": {"e": 389060.001, "n": 5819030.0, "z": 34.3}}
    )
    history = (await client.get(f"{BASE}/stakes/{c03}/records", headers=header)).json()
    assert [r["verdict"] for r in history] == ["pass", "fail"]
    assert history[1]["measured_by"] == "Demo surveyor"


async def test_new_request_with_chainage_stake(client: AsyncClient, header: dict, project_id: str) -> None:
    created = await client.post(
        f"{BASE}/projects/{project_id}/requests",
        json={"name": "Kerb line", "item_type": "kerb", "tolerance_key": "demo", "tol_h_mm": 20},
        headers=header,
    )
    assert created.status_code == 201, created.text
    req = created.json()
    assert req["code"] == "SO-001"
    assert req["tol_h_mm"] == 20.0
    xml = (DEMO / "axis_c.xml").read_text(encoding="utf-8")
    preview = await client.post(
        f"{BASE}/requests/{req['id']}/design/preview", json={"text": xml, "file_format": "landxml"}, headers=header
    )
    assert preview.json()["alignment"]["length"] == 100.0
    await client.post(
        f"{BASE}/requests/{req['id']}/design", json={"text": xml, "file_format": "landxml"}, headers=header
    )
    stake = await client.post(
        f"{BASE}/requests/{req['id']}/stakes", json={"point_id": "K1", "chainage": 25, "offset_m": 2}, headers=header
    )
    assert stake.status_code == 201, stake.text
    assert (stake.json()["design_e"], stake.json()["design_n"]) == (389025.0, 5819028.0)
    calc = await client.post(
        f"{BASE}/requests/{req['id']}/chainage", json={"e": 389025.0, "n": 5819028.0}, headers=header
    )
    assert (calc.json()["chainage"], calc.json()["offset_m"]) == (25.0, 2.0)


async def test_unknown_profile_is_refused(client: AsyncClient, header: dict, project_id: str) -> None:
    response = await client.post(
        f"{BASE}/projects/{project_id}/requests", json={"name": "X", "tolerance_key": "pack:nowhere"}, headers=header
    )
    assert response.status_code == 422


async def test_profiles_show_demo_and_project_only(client: AsyncClient, header: dict, project_id: str) -> None:
    made = await client.post(
        f"{BASE}/projects/{project_id}/profiles",
        json={"name": "Site 15", "items": {"default": {"h_mm": 15}}},
        headers=header,
    )
    assert made.status_code == 201, made.text
    keys = [p["key"] for p in (await client.get(f"{BASE}/projects/{project_id}/profiles", headers=header)).json()]
    assert keys[0] == "demo"
    assert made.json()["key"] in keys
    assert not any(k.startswith("pack:") for k in keys)


async def test_stranger_cannot_read_or_write(
    client: AsyncClient, header: dict, stranger: dict, viewer: dict, project_id: str
) -> None:
    detail = await _demo(client, header, project_id)
    assert (await client.get(f"{BASE}/requests/{detail['id']}", headers=stranger)).status_code in (403, 404)
    assert (await client.get(f"{BASE}/projects/{project_id}/requests", headers=stranger)).status_code in (403, 404)
    stake = _stake(detail, "C-03")["id"]
    body = {"measured_e": 1, "measured_n": 2}
    assert (await client.post(f"{BASE}/stakes/{stake}/records", json=body, headers=stranger)).status_code in (403, 404)
    assert (await client.post(f"{BASE}/stakes/{stake}/records", json=body, headers=viewer)).status_code == 403
