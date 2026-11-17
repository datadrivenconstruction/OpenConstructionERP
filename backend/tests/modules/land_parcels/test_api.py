# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Land and parcels end to end on the Riverside Yard lessons, against a real database.

Lesson numbers come from ``demo/riverside/expected.json``; the course reads the
same file, so a change that breaks a lesson fails here.
"""

from __future__ import annotations

import base64
import io
import json
import zipfile
from pathlib import Path

from httpx import AsyncClient

from app.modules.land_parcels.parcel_io import parse_shapefile_zip

BASE = "/api/v1/land-parcels"
SURVEY = "/api/v1/survey-core"
DEMO = Path(__file__).resolve().parents[3] / "app" / "modules" / "land_parcels" / "demo" / "riverside"
EXPECTED = json.loads((DEMO / "expected.json").read_text(encoding="utf-8"))["land_parcels"]


def _file(name: str) -> str:
    return (DEMO / name).read_text(encoding="utf-8")


async def _crs(client: AsyncClient, header: dict, project_id: str) -> None:
    r = await client.put(f"{SURVEY}/projects/{project_id}/crs", json={"horizontal_epsg": 32633}, headers=header)
    assert r.status_code == 200, r.text


async def _import(client: AsyncClient, header: dict, project_id: str, name: str, target: str = "parcels") -> dict:
    body = {"format": "geojson", "target": target, "filename": name, "text": _file(name)}
    r = await client.post(f"{BASE}/projects/{project_id}/import", json=body, headers=header)
    assert r.status_code == 201, r.text
    return r.json()


async def _parcels(client: AsyncClient, header: dict, project_id: str) -> dict[str, dict]:
    r = await client.get(f"{BASE}/projects/{project_id}/parcels", headers=header)
    assert r.status_code == 200, r.text
    return {p["parcel_ref"]: p for p in r.json()}


async def _summary(client: AsyncClient, header: dict, project_id: str) -> dict:
    r = await client.get(f"{BASE}/projects/{project_id}/summary", headers=header)
    assert r.status_code == 200, r.text
    return r.json()


async def test_lesson_1_import_parcels(client: AsyncClient, header: dict, project_id: str) -> None:
    lesson = EXPECTED["lesson_1"]
    await _crs(client, header, project_id)
    preview = await client.post(
        f"{BASE}/projects/{project_id}/import/preview", json={"text": _file(lesson["file"])}, headers=header
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["features_read"] == lesson["parcels"]
    assert body["problem_count"] == 0
    assert body["file_epsg"] == 32633 and body["transform"] is None
    assert body["total_area"] == lesson["total_area_m2"]
    assert (await _parcels(client, header, project_id)) == {}
    result = await _import(client, header, project_id, lesson["file"])
    assert result["created"] == lesson["parcels"]
    assert result["total_area"] == lesson["total_area_m2"]
    summary = await _summary(client, header, project_id)
    assert summary["parcels"] == lesson["parcels"]
    assert summary["total_area"] == lesson["total_area_m2"]
    assert summary["acquired"] == 2
    assert summary["cost_to_acquire"] == EXPECTED["cost_to_acquire"]


async def test_lesson_2_open_p001(client: AsyncClient, header: dict, project_id: str) -> None:
    lesson = EXPECTED["lesson_2"]
    await _crs(client, header, project_id)
    await _import(client, header, project_id, "parcels.geojson")
    p1 = (await _parcels(client, header, project_id))[lesson["parcel"]]
    assert p1["computed_area"] == lesson["computed_area_m2"]
    assert p1["legal_area"] == lesson["legal_area_m2"]
    assert p1["area_diff"] == lesson["diff_m2"]
    assert len(p1["findings"]) == lesson["findings"]
    detail = await client.get(f"{BASE}/parcels/{p1['id']}", headers=header)
    assert detail.status_code == 200, detail.text
    assert len(detail.json()["points"]) == 4
    settings = await client.get(f"{BASE}/projects/{project_id}/settings", headers=header)
    assert settings.json()["area_tolerance_pct"] == lesson["area_tolerance_pct"]


async def test_lesson_3_and_4_work_zone_blocks_until_acquired(
    client: AsyncClient, header: dict, project_id: str
) -> None:
    lesson3, lesson4 = EXPECTED["lesson_3"], EXPECTED["lesson_4"]
    await _crs(client, header, project_id)
    await _import(client, header, project_id, "parcels.geojson")
    zones = await _import(client, header, project_id, lesson3["file"], target="work_zone")
    assert zones["work_zones"] == 1
    parcels = await _parcels(client, header, project_id)
    p3 = parcels[lesson3["parcel"]]
    assert [f["rule_id"] for f in p3["findings"]] == [lesson3["finding"]]
    assert lesson3["overlap_m2"] in p3["findings"][0]["message"]
    assert all(not p["findings"] for ref, p in parcels.items() if ref != lesson3["parcel"])
    assert (await _summary(client, header, project_id))["blocking_works"] == lesson3["blocking_works"]

    plan = await client.get(f"{BASE}/projects/{project_id}/plan", headers=header)
    assert plan.status_code == 200, plan.text
    kinds = [f["properties"]["kind"] for f in plan.json()["features"]]
    assert kinds.count("parcel") == 3 and kinds.count("work_zone") == 1
    lon, lat = plan.json()["features"][0]["geometry"]["coordinates"][0][0]
    assert 13 < lon < 14 and 52 < lat < 53

    r = await client.patch(f"{BASE}/parcels/{p3['id']}", json={"status": lesson4["status"]}, headers=header)
    assert r.status_code == 200, r.text
    assert r.json()["findings"] == []
    assert r.json()["acquired_on"] is not None
    summary = await _summary(client, header, project_id)
    assert summary["blocking_works"] == lesson4["blocking_works"]
    assert (summary["acquired"], summary["parcels"]) == (lesson4["acquired"], lesson4["parcels"])


async def test_lesson_5_export_shapefile_and_print_schedule(client: AsyncClient, header: dict, project_id: str) -> None:
    lesson = EXPECTED["lesson_5"]
    await _crs(client, header, project_id)
    await _import(client, header, project_id, "parcels.geojson")
    r = await client.get(f"{BASE}/projects/{project_id}/export", params={"format": lesson["export"]}, headers=header)
    assert r.status_code == 200, r.text
    assert "parcels_shp.zip" in r.headers["content-disposition"]
    assert "parcels.prj" in zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert len(parse_shapefile_zip(r.content).features) == lesson["zip_features"]
    pdf = await client.get(f"{BASE}/projects/{project_id}/schedule.pdf", headers=header)
    assert pdf.status_code == 200, pdf.text
    assert pdf.content.startswith(b"%PDF")
    dxf = await client.get(f"{BASE}/projects/{project_id}/export", params={"format": "dxf"}, headers=header)
    assert dxf.status_code == 200 and b"LWPOLYLINE" in dxf.content
    unknown = await client.get(f"{BASE}/projects/{project_id}/export", params={"format": "nas"}, headers=header)
    assert unknown.status_code == 422


async def test_shapefile_import_matches_geojson(client: AsyncClient, header: dict, project_id: str) -> None:
    await _crs(client, header, project_id)
    body = {
        "format": "shapefile",
        "filename": "parcels_shp.zip",
        "content_base64": base64.b64encode((DEMO / "parcels_shp.zip").read_bytes()).decode("ascii"),
    }
    r = await client.post(f"{BASE}/projects/{project_id}/import", json=body, headers=header)
    assert r.status_code == 201, r.text
    assert r.json()["total_area"] == EXPECTED["lesson_1"]["total_area_m2"]


async def test_import_needs_project_crs(client: AsyncClient, header: dict, project_id: str) -> None:
    r = await client.post(
        f"{BASE}/projects/{project_id}/import", json={"text": _file("parcels.geojson")}, headers=header
    )
    assert r.status_code == 409


async def test_wgs84_file_is_transformed_only_with_both_codes_named(
    client: AsyncClient, header: dict, project_id: str
) -> None:
    await _crs(client, header, project_id)
    ring = [[13.3, 52.5], [13.3003, 52.5], [13.3003, 52.5002], [13.3, 52.5002], [13.3, 52.5]]
    doc = {
        "type": "Feature",
        "properties": {"parcel_id": "G-1"},
        "geometry": {"type": "Polygon", "coordinates": [ring]},
    }
    r = await client.post(
        f"{BASE}/projects/{project_id}/import/preview", json={"text": json.dumps(doc)}, headers=header
    )
    assert r.status_code == 200, r.text
    assert r.json()["transform"] == "EPSG 4326 -> EPSG 32633"
    assert 400 < float(r.json()["total_area"]) < 500


async def test_manual_parcel_points_and_bow_tie(client: AsyncClient, header: dict, project_id: str) -> None:
    await _crs(client, header, project_id)
    pts = [{"e": 389000 + x, "n": 5819000 + y, "mark": "pin"} for x, y in [(0, 0), (10, 0), (10, 10), (0, 10)]]
    r = await client.post(
        f"{BASE}/projects/{project_id}/parcels",
        json={"parcel_ref": "M-1", "legal_area": "100", "points": pts},
        headers=header,
    )
    assert r.status_code == 201, r.text
    assert r.json()["computed_area"] == "100.00"
    assert r.json()["points"][0]["label"] == "M-1-1"
    bow = [pts[0], pts[2], pts[1], pts[3]]
    r = await client.put(f"{BASE}/parcels/{r.json()['id']}/points", json={"points": bow}, headers=header)
    assert r.status_code == 200, r.text
    assert "PAR-002" in [f["rule_id"] for f in r.json()["findings"]]


async def test_parties_and_rights_are_data(client: AsyncClient, header: dict, project_id: str) -> None:
    await _crs(client, header, project_id)
    await _import(client, header, project_id, "parcels.geojson")
    p3 = (await _parcels(client, header, project_id))["P-003"]
    party = await client.post(
        f"{BASE}/projects/{project_id}/parties",
        json={"name": "Utility company", "kind": "organisation"},
        headers=header,
    )
    assert party.status_code == 201, party.text
    right = await client.post(
        f"{BASE}/parcels/{p3['id']}/rights",
        json={"party_id": party.json()["id"], "kind": "easement", "description": "Water main, 4 m strip"},
        headers=header,
    )
    assert right.status_code == 201, right.text
    assert right.json()["party_name"] == "Utility company"
    assert (await _parcels(client, header, project_id))["P-003"]["rights_kinds"] == ["easement"]
    bad = await client.post(
        f"{BASE}/parcels/{p3['id']}/rights",
        json={"kind": "lease", "valid_from": "2027-01-01", "valid_to": "2026-01-01"},
        headers=header,
    )
    assert bad.status_code == 422


async def test_send_compensation_to_boq_writes_position_and_back_link(
    client: AsyncClient, header: dict, project_id: str
) -> None:
    await _crs(client, header, project_id)
    await _import(client, header, project_id, "parcels.geojson")
    p3 = (await _parcels(client, header, project_id))["P-003"]
    boq = await client.post("/api/v1/boq/boqs/", json={"project_id": project_id, "name": "Land"}, headers=header)
    assert boq.status_code in (200, 201), boq.text
    r = await client.post(
        f"{BASE}/parcels/{p3['id']}/send-to-boq",
        json={"boq_id": boq.json()["id"], "description": "Land acquisition P-003"},
        headers=header,
    )
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "added" and r.json()["total"] == "40000.00"
    assert (await _parcels(client, header, project_id))["P-003"]["boq_position_id"] == r.json()["position_id"]


async def test_access_rules(client: AsyncClient, header: dict, stranger: dict, viewer: dict, project_id: str) -> None:
    await _crs(client, header, project_id)
    r = await client.get(f"{BASE}/projects/{project_id}/parcels", headers=stranger)
    assert r.status_code in (403, 404)
    r = await client.post(
        f"{BASE}/projects/{project_id}/import", json={"text": _file("parcels.geojson")}, headers=viewer
    )
    assert r.status_code == 403
