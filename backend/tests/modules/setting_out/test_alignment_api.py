# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Alignment by IP end to end: the Riverside access road, SRV-072 and SRV-073, and the stake list pick-up."""

from __future__ import annotations

from httpx import AsyncClient

BASE = "/api/v1/setting-out"

L_TURN = {
    "ips": [{"e": 0, "n": 0}, {"e": 100, "n": 0, "radius": 50}, {"e": 100, "n": 100}],
    "design_speed_kmh": 50,
}


async def test_preview_hand_calc_and_ticks(client: AsyncClient, header: dict) -> None:
    response = await client.post(f"{BASE}/alignment/preview", json=L_TURN, headers=header)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["length"] == 178.5398
    [curve] = body["curves"]
    assert curve["tc"] == [50.0, 0.0]
    assert curve["ct"] == [100.0, 50.0]
    assert [t["chainage"] for t in body["ticks"]][:3] == [0.0, 20.0, 40.0]
    # 50 m is below the demo 60 m at 50 km/h.
    assert curve["below_min"] is True
    assert [f["rule_id"] for f in body["findings"]] == ["SRV-072"]
    assert body["min_radius"]["source"] == "demo"


async def test_overlap_is_an_error_and_is_not_saved(client: AsyncClient, header: dict, project_id: str) -> None:
    created = await client.post(f"{BASE}/projects/{project_id}/requests", json={"name": "Road B"}, headers=header)
    assert created.status_code == 201, created.text
    ips = [{"e": 0, "n": 0}, {"e": 100, "n": 0, "radius": 60}, {"e": 100, "n": 100, "radius": 60}, {"e": 200, "n": 100}]
    preview = await client.post(f"{BASE}/alignment/preview", json={"ips": ips}, headers=header)
    assert preview.json()["fits"] is False
    assert "SRV-073" in [f["rule_id"] for f in preview.json()["findings"]]
    put = await client.put(f"{BASE}/requests/{created.json()['id']}/alignment", json={"ips": ips}, headers=header)
    assert put.status_code == 422


async def test_riverside_road_saves_and_feeds_the_chainage_calculator(
    client: AsyncClient, header: dict, project_id: str
) -> None:
    response = await client.post(f"{BASE}/projects/{project_id}/demo/riverside/road", headers=header)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["saved"] is True
    assert [c["radius"] for c in body["curves"]] == [120.0, 60.0, 45.0]
    warn = [f for f in body["findings"] if f["rule_id"] == "SRV-072"]
    assert len(warn) == 1
    assert "45" in warn[0]["message"]
    assert warn[0]["severity"] == "warning"
    again = await client.post(f"{BASE}/projects/{project_id}/demo/riverside/road", headers=header)
    assert again.status_code == 200
    reqs = (await client.get(f"{BASE}/projects/{project_id}/requests", headers=header)).json()
    road = next(r for r in reqs["items"] if r["name"] == "Access road A")
    detail = (await client.get(f"{BASE}/requests/{road['id']}", headers=header)).json()
    assert detail["alignment"]["ips"][3]["radius"] == 45
    start = body["alignment"]["elements"][0]["start"]
    calc = await client.post(
        f"{BASE}/requests/{road['id']}/chainage", json={"e": start[0], "n": start[1]}, headers=header
    )
    assert calc.status_code == 200, calc.text
    assert abs(calc.json()["chainage"]) < 1e-6
