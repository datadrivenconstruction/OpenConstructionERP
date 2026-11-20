# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Point register v2 through the API on PostgreSQL: detail, edit, bulk, export, control checks, lock."""

from __future__ import annotations

from httpx import AsyncClient

from tests.modules.survey_core.conftest import (  # noqa: F401
    app_instance,
    client,
    header,
    login,
    project_id,
    viewer,
)

CORE = "/api/v1/survey-core"
VOL = "/api/v1/surfaces-volumes"
TEXT = "CP1,5818990.000,388990.000,33.900,CP\n101,5819000.000,389000.000,34.100,TOE\n102,5819000.000,389010.000,34.300,TOE\n"


async def _import(client: AsyncClient, header: dict, pid: str, text: str = TEXT, name: str = "Morning") -> dict:
    r = await client.put(f"{CORE}/projects/{pid}/crs", json={"horizontal_epsg": 32633}, headers=header)
    assert r.status_code == 200, r.text
    r = await client.post(
        f"{CORE}/projects/{pid}/import",
        json={"text": text, "filename": f"{name}.csv", "column_preset": "PNEZD", "delimiter": ",", "name": name},
        headers=header,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _points(client: AsyncClient, header: dict, pid: str) -> dict[str, dict]:
    items = (await client.get(f"{CORE}/projects/{pid}/points", headers=header)).json()["items"]
    return {p["point_id"]: p for p in items}


async def test_point_detail_edit_and_delete(client: AsyncClient, header: dict, project_id: str) -> None:
    await _import(client, header, project_id)
    pts = await _points(client, header, project_id)
    r = await client.get(f"{CORE}/points/{pts['101']['id']}", headers=header)
    assert r.status_code == 200, r.text
    d = r.json()
    assert (d["set_name"], d["source_filename"], d["source_line"], d["stored_epsg"]) == (
        "Morning",
        "Morning.csv",
        2,
        32633,
    )
    assert d["locked"] is False

    r = await client.patch(f"{CORE}/points/{pts['101']['id']}", json={"code": "CREST", "z": 34.25}, headers=header)
    assert r.status_code == 200, r.text
    assert (r.json()["code"], r.json()["z"]) == ("CREST", 34.25)

    r = await client.delete(f"{CORE}/points/{pts['102']['id']}", headers=header)
    assert r.status_code == 204
    assert set(await _points(client, header, project_id)) == {"CP1", "101"}
    [s] = (await client.get(f"{CORE}/projects/{project_id}/point-sets", headers=header)).json()["items"]
    assert s["point_count"] == 2


async def test_bulk_code_kind_move_and_delete(client: AsyncClient, header: dict, project_id: str) -> None:
    await _import(client, header, project_id)
    other = await _import(client, header, project_id, "201,5819020.000,389020.000,35.0,X\n", "Afternoon")
    pts = await _points(client, header, project_id)
    ids = [pts["101"]["id"], pts["102"]["id"]]
    r = await client.post(
        f"{CORE}/projects/{project_id}/points/bulk",
        json={"ids": ids, "action": "set_code", "value": "KERB"},
        headers=header,
    )
    assert r.json() == {"action": "set_code", "affected": 2, "skipped_locked": 0}
    r = await client.post(
        f"{CORE}/projects/{project_id}/points/bulk",
        json={"ids": ids, "action": "set_kind", "value": "asbuilt"},
        headers=header,
    )
    assert r.status_code == 200, r.text
    r = await client.post(
        f"{CORE}/projects/{project_id}/points/bulk",
        json={"ids": ids, "action": "move_to_set", "target_set_id": other["point_set"]["id"]},
        headers=header,
    )
    assert r.status_code == 200, r.text
    pts = await _points(client, header, project_id)
    assert {pts[k]["point_set_id"] for k in ("101", "102", "201")} == {other["point_set"]["id"]}
    assert {pts[k]["code"] for k in ("101", "102")} == {"KERB"}
    assert {pts[k]["kind"] for k in ("101", "102")} == {"asbuilt"}
    r = await client.post(
        f"{CORE}/projects/{project_id}/points/bulk", json={"ids": ids, "action": "delete"}, headers=header
    )
    assert r.json()["affected"] == 2
    assert set(await _points(client, header, project_id)) == {"CP1", "201"}


async def test_export_selection_csv_dxf_landxml(client: AsyncClient, header: dict, project_id: str) -> None:
    await _import(client, header, project_id)
    pts = await _points(client, header, project_id)
    body = {"ids": [pts["CP1"]["id"]], "format": "csv", "preset": "PNEZD", "header": False}
    r = await client.post(f"{CORE}/projects/{project_id}/points/export", json=body, headers=header)
    assert r.status_code == 200, r.text
    assert r.text == "CP1,5818990.0000,388990.0000,33.9000,CP,\n"
    r = await client.post(f"{CORE}/projects/{project_id}/points/export", json={"format": "landxml"}, headers=header)
    assert '<CoordinateSystem epsgCode="32633"/>' in r.text
    assert r.text.count("<CgPoint ") == 3
    r = await client.post(f"{CORE}/projects/{project_id}/points/export", json={"format": "dxf"}, headers=header)
    assert r.status_code == 200
    assert b"PT_TOE" in r.content


async def test_control_checks_and_srv_012(client: AsyncClient, header: dict, project_id: str) -> None:
    await _import(client, header, project_id)
    r = await client.put(
        f"{CORE}/projects/{project_id}/profile", json={"label": "Site", "control_tol_mm": 20}, headers=header
    )
    assert r.status_code == 200, r.text
    pts = await _points(client, header, project_id)
    cp = pts["CP1"]["id"]
    r = await client.post(
        f"{CORE}/projects/{project_id}/control/checks",
        json={"control_point_id": cp, "e": 388990.027, "n": 5818990.012, "z": 33.892},
        headers=header,
    )
    assert r.status_code == 201, r.text
    assert (r.json()["d2d_mm"], r.json()["dz_mm"], r.json()["verdict"]) == (29.5, -8.0, "fail")
    bad = await client.post(
        f"{CORE}/projects/{project_id}/control/checks",
        json={"control_point_id": pts["101"]["id"], "e": 1, "n": 1},
        headers=header,
    )
    assert bad.status_code == 422
    listing = (await client.get(f"{CORE}/projects/{project_id}/control", headers=header)).json()
    assert (listing["total"], listing["failing"], listing["tolerance_mm"]) == (1, 1, 20.0)
    report = (await client.post(f"{CORE}/projects/{project_id}/validate", headers=header)).json()
    assert "SRV-012" in {f["rule_id"] for f in report["findings"]}

    r = await client.post(
        f"{CORE}/projects/{project_id}/control/checks",
        json={"control_point_id": cp, "measured_point_id": pts["101"]["id"]},
        headers=header,
    )
    assert r.status_code == 201, r.text
    assert r.json()["measured_point_id"] == pts["101"]["id"]


async def test_viewer_reads_but_cannot_edit(client: AsyncClient, header: dict, viewer: dict, project_id: str) -> None:
    await _import(client, header, project_id)
    pts = await _points(client, header, project_id)
    r = await client.patch(f"{CORE}/points/{pts['101']['id']}", json={"code": "X"}, headers=viewer)
    assert r.status_code in (403, 404)
    r = await client.post(
        f"{CORE}/projects/{project_id}/points/bulk",
        json={"ids": [pts["101"]["id"]], "action": "delete"},
        headers=viewer,
    )
    assert r.status_code in (403, 404)


async def test_a_point_behind_a_confirmed_volume_is_locked(client: AsyncClient, header: dict, project_id: str) -> None:
    from tests.modules.surfaces_volumes.test_api import _surfaces

    eg, pad = await _surfaces(client, header, project_id)
    r = await client.post(
        f"{VOL}/projects/{project_id}/volumes",
        json={"name": "Pad", "base_surface_id": eg["id"], "compare_surface_id": pad["id"]},
        headers=header,
    )
    assert r.status_code == 201, r.text
    v = r.json()
    r = await client.post(f"{VOL}/volumes/{v['id']}/confirm", json={}, headers=header)
    assert r.status_code == 200, r.text
    [ground] = (await client.get(f"{CORE}/projects/{project_id}/point-sets", headers=header)).json()["items"]
    listed = await client.get(
        f"{CORE}/projects/{project_id}/points", params={"set_id": ground["id"], "limit": 1}, headers=header
    )
    [p] = listed.json()["items"]
    d = (await client.get(f"{CORE}/points/{p['id']}", headers=header)).json()
    assert d["locked"] is True
    assert {u["code"] for u in d["used_by"]} >= {eg["code"], v["code"]}
    r = await client.patch(f"{CORE}/points/{p['id']}", json={"code": "X"}, headers=header)
    assert r.status_code == 409
    r = await client.post(
        f"{CORE}/projects/{project_id}/points/bulk", json={"ids": [p["id"]], "action": "delete"}, headers=header
    )
    assert r.json()["skipped_locked"] == 1


async def test_the_demo_shows_the_control_parcel_and_monitoring_rules(client: AsyncClient, header: dict) -> None:
    """Read only: the lessons suite confirms V-001 on the same demo project."""
    installed = await client.post("/api/demo/install/survey-riverside-yard", headers=header)
    assert installed.status_code in (200, 201), installed.text
    pid = installed.json()["project_id"]
    control = (await client.get(f"{CORE}/projects/{pid}/control", headers=header)).json()
    assert control["failing"] == 1
    parcels = (await client.get(f"/api/v1/land-parcels/projects/{pid}/parcels", headers=header)).json()["items"]
    p004 = next(x for x in parcels if x["parcel_ref"] == "P-004")
    assert (p004["legal_area"], p004["computed_area"]) == ("950", "900.00")
    mon = (await client.get(f"/api/v1/monitoring/projects/{pid}/points", headers=header)).json()["items"]
    levels = {x["code"]: x["level"] for x in mon}
    assert levels["MP-03"] == "alarm"
