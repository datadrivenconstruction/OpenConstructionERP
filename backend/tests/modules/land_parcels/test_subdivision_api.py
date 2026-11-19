# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Split, merge, corners and setback through the API, against a real database."""

from __future__ import annotations

from httpx import AsyncClient

BASE = "/api/v1/land-parcels"
SURVEY = "/api/v1/survey-core"
E0, N0 = 389000.0, 5819000.0
TRAPEZOID = [(0.0, 0.0), (50.0, 0.0), (50.0, 32.0), (0.0, 28.0)]


async def _trapezoid(client: AsyncClient, header: dict, project_id: str) -> str:
    r = await client.put(f"{SURVEY}/projects/{project_id}/crs", json={"horizontal_epsg": 32633}, headers=header)
    assert r.status_code == 200, r.text
    points = [{"label": f"T{i + 1}", "e": E0 + x, "n": N0 + y} for i, (x, y) in enumerate(TRAPEZOID)]
    r = await client.post(
        f"{BASE}/projects/{project_id}/parcels", json={"parcel_ref": "T-1", "points": points}, headers=header
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_split_to_area_then_merge_back(client: AsyncClient, header: dict, project_id: str) -> None:
    pid = await _trapezoid(client, header, project_id)
    body = {"mode": "parallel", "side": 3, "target_area": 600.0}
    r = await client.post(f"{BASE}/parcels/{pid}/split", json=body, headers=header)
    assert r.status_code == 200, r.text
    preview = r.json()
    assert preview["saved"] is False
    assert abs(preview["cut_length"] - 29.665) < 1e-3
    assert [round(p["area"], 2) for p in preview["parts"]] == [600.0, 900.0]
    assert preview["findings"] == []

    r = await client.post(f"{BASE}/parcels/{pid}/split", json={**body, "preview": False}, headers=header)
    assert r.status_code == 200, r.text
    saved = r.json()
    assert saved["saved"] is True
    children = [p["parcel_id"] for p in saved["parts"]]

    r = await client.get(f"{BASE}/projects/{project_id}/parcels", headers=header)
    live = {p["parcel_ref"]: p for p in r.json()["items"]}
    assert set(live) == {"T-1/1", "T-1/2"}
    assert live["T-1/1"]["parent_ids"] == [pid]
    r = await client.get(f"{BASE}/projects/{project_id}/parcels?include_superseded=true", headers=header)
    assert {p["parcel_ref"]: p["superseded"] for p in r.json()["items"]}["T-1"] is True

    r = await client.post(
        f"{BASE}/projects/{project_id}/parcels/merge",
        json={"parcel_ids": children, "ref": "T-2", "preview": False},
        headers=header,
    )
    assert r.status_code == 200, r.text
    assert round(r.json()["parent_area"], 2) == 1500.0


async def test_corner_register_and_setback(client: AsyncClient, header: dict, project_id: str) -> None:
    pid = await _trapezoid(client, header, project_id)
    r = await client.patch(
        f"{BASE}/parcels/{pid}/corners/1", json={"corner_status": "found", "accuracy_m": 0.02}, headers=header
    )
    assert r.status_code == 200, r.text
    first = r.json()["corners"][0]
    assert first["corner_status"] == "found" and first["accuracy_m"] == 0.02

    footprint = [[E0 + 2.65, N0 + 5.0], [E0 + 20.0, N0 + 5.0], [E0 + 20.0, N0 + 20.0], [E0 + 2.65, N0 + 20.0]]
    r = await client.post(
        f"{BASE}/parcels/{pid}/setback", json={"footprint": footprint, "name": "B1", "setback_m": 3.0}, headers=header
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert abs(out["min_distance"] - 2.65) < 1e-3
    assert [f["rule_id"] for f in out["findings"]] == ["SRV-102"]
