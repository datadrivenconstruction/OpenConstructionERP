# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Parcels on the plan: the six-parcel riverside demo, work zones drawn and edited, the boundary point register."""

from __future__ import annotations

from httpx import AsyncClient

BASE = "/api/v1/land-parcels"
SURVEY = "/api/v1/survey-core"


async def _demo(client: AsyncClient, header: dict, project_id: str) -> dict:
    r = await client.put(f"{SURVEY}/projects/{project_id}/crs", json={"horizontal_epsg": 32633}, headers=header)
    assert r.status_code == 200, r.text
    r = await client.post(f"{BASE}/projects/{project_id}/demo/riverside", headers=header)
    assert r.status_code == 200, r.text
    return r.json()


async def _zones(client: AsyncClient, header: dict, project_id: str) -> list[dict]:
    r = await client.get(f"{BASE}/projects/{project_id}/work-zones", headers=header)
    assert r.status_code == 200, r.text
    return r.json()["items"]


async def test_demo_loads_six_parcels_with_their_deliberate_errors(
    client: AsyncClient, header: dict, project_id: str
) -> None:
    assert await _demo(client, header, project_id) == {"parcels": 6, "work_zones": 1, "skipped": False}
    again = await client.post(f"{BASE}/projects/{project_id}/demo/riverside", headers=header)
    assert again.json()["skipped"] is True
    r = await client.post(f"{BASE}/projects/{project_id}/validate", headers=header)
    assert r.status_code == 200, r.text
    by_rule: dict[str, list[str]] = {}
    for f in r.json()["findings"]:
        by_rule.setdefault(f["rule_id"], []).append(f["message"])
    assert any("R-02" in m for m in by_rule["PAR-001"]), by_rule
    assert any("R-05" in m and "R-06" in m for m in by_rule["PAR-004"]), by_rule
    assert any("R-04" in m and "0.300" in m for m in by_rule["PAR-005"]), by_rule
    assert any("R-03" in m for m in by_rule["PAR-003"]), by_rule
    assert "PAR-002" not in by_rule


async def test_work_zone_drawn_then_edited_reports_touched_parcels(
    client: AsyncClient, header: dict, project_id: str
) -> None:
    await _demo(client, header, project_id)
    zone = (await _zones(client, header, project_id))[0]
    r = await client.get(f"{BASE}/work-zones/{zone['id']}", headers=header)
    detail = r.json()
    assert {t["parcel_ref"] for t in detail["touched"]} == {"R-01", "R-02", "R-03"}
    assert [t["parcel_ref"] for t in detail["touched"] if t["blocking"]] == ["R-03"]
    assert [f["rule_id"] for f in detail["findings"]] == ["PAR-003"]
    # Pull the zone back west of R-03: no land left to acquire.
    ring = [[389030.0, 5819080.0], [389075.0, 5819080.0], [389075.0, 5819095.0], [389030.0, 5819095.0]]
    r = await client.put(f"{BASE}/work-zones/{zone['id']}", json={"name": "Haul road v2", "ring": ring}, headers=header)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "Haul road v2" and body["vertex_count"] == 4
    assert {t["parcel_ref"] for t in body["touched"]} == {"R-01", "R-02"}
    assert body["findings"] == []


async def test_work_zone_created_on_the_plan(client: AsyncClient, header: dict, project_id: str) -> None:
    await _demo(client, header, project_id)
    ring = [[389085.0, 5819110.0], [389110.0, 5819110.0], [389110.0, 5819130.0], [389085.0, 5819130.0]]
    r = await client.post(
        f"{BASE}/projects/{project_id}/work-zones", json={"name": "Crane base", "ring": ring}, headers=header
    )
    assert r.status_code == 201, r.text
    assert [t["parcel_ref"] for t in r.json()["touched"]] == ["R-06"]
    assert len(await _zones(client, header, project_id)) == 2


async def test_work_zone_needs_three_corners(client: AsyncClient, header: dict, project_id: str) -> None:
    await _demo(client, header, project_id)
    ring = [[389085.0, 5819110.0], [389110.0, 5819110.0], [389085.0, 5819110.0]]
    r = await client.post(f"{BASE}/projects/{project_id}/work-zones", json={"name": "x", "ring": ring}, headers=header)
    assert r.status_code == 422


async def test_viewer_cannot_draw_a_zone(client: AsyncClient, viewer: dict, header: dict, project_id: str) -> None:
    await _demo(client, header, project_id)
    ring = [[0, 0], [10, 0], [10, 10]]
    r = await client.post(f"{BASE}/projects/{project_id}/work-zones", json={"name": "x", "ring": ring}, headers=viewer)
    assert r.status_code == 403


async def test_boundary_point_register_shares_corners_between_parcels(
    client: AsyncClient, header: dict, project_id: str
) -> None:
    await _demo(client, header, project_id)
    r = await client.get(f"{BASE}/projects/{project_id}/boundary-points", headers=header)
    assert r.status_code == 200, r.text
    body = r.json()
    rows = {p["point_no"]: p for p in body["items"]}
    assert body["total"] == 16
    assert sorted(rows["B07"]["parcels"]) == ["R-02", "R-03", "R-05"]
    assert rows["B01"]["mark"] == "monument" and rows["B01"]["monumented"] is True
    assert rows["B09"]["monumented"] is False
    assert body["unmarked"] == 4 and body["conflicts"] == 0


async def test_profile_offers_the_neutral_mark_list(client: AsyncClient, header: dict, project_id: str) -> None:
    r = await client.get(f"{BASE}/projects/{project_id}/profile", headers=header)
    body = r.json()
    assert body["id_pattern"] == ""
    assert {m["key"] for m in body["marks"]} >= {"monument", "pin", "unmarked"}
    assert next(m for m in body["marks"] if m["key"] == "unmarked")["monumented"] is False


async def test_vertex_corner_status_and_mark_are_saved(client: AsyncClient, header: dict, project_id: str) -> None:
    await _demo(client, header, project_id)
    r = await client.get(f"{BASE}/projects/{project_id}/parcels", headers=header)
    parcel = next(p for p in r.json()["items"] if p["parcel_ref"] == "R-01")
    pts = (await client.get(f"{BASE}/parcels/{parcel['id']}", headers=header)).json()["points"]
    body = [
        {"label": p["label"], "e": p["e"], "n": p["n"], "mark": "stone" if i == 0 else p["mark"],
         "corner_status": "found" if i == 0 else ""}
        for i, p in enumerate(pts)
    ]  # fmt: skip
    r = await client.put(f"{BASE}/parcels/{parcel['id']}/points", json={"points": body}, headers=header)
    assert r.status_code == 200, r.text
    first = r.json()["points"][0]
    assert first["mark"] == "stone" and first["corner_status"] == "found"
