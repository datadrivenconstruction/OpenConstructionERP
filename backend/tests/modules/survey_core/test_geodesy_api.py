"""Geodesy end to end: local grid, grid/ground, instrument imports and exports against a real database."""

from __future__ import annotations

from httpx import AsyncClient

BASE = "/api/v1/survey-core"
LOCAL = [
    {"point_id": "A", "x": 1000, "y": 1000, "e": 389012.345, "n": 5819020.111},
    {"point_id": "B", "x": 1100, "y": 1000, "e": 389111.966, "n": 5819028.827},
]


def _w16(wi: str, unit: str, value: int) -> str:
    return f"{wi}..4{unit}{'-' if value < 0 else '+'}{abs(value):016d}"


def _gsi16(pid: str, unit: str, e: int, n: int, z: int) -> str:
    return "*" + " ".join(
        ["110001+" + pid.rjust(16, "0"), _w16("81", unit, e), _w16("82", unit, n), _w16("83", unit, z)]
    )


async def _crs(client: AsyncClient, header: dict, project_id: str, epsg: int = 32633) -> None:
    r = await client.put(f"{BASE}/projects/{project_id}/crs", json={"horizontal_epsg": epsg}, headers=header)
    assert r.status_code == 200, r.text


async def test_solve_is_stateless_and_refuses_one_point(client: AsyncClient, header: dict) -> None:
    r = await client.post(f"{BASE}/local-grid/solve", json={"points": LOCAL}, headers=header)
    assert r.status_code == 200, r.text
    body = r.json()
    assert abs(body["rotation_deg"] - 5.0) < 0.001
    assert body["fitted"] == 2 and body["rms_mm"] == 0
    r = await client.post(f"{BASE}/local-grid/solve", json={"points": LOCAL[:1]}, headers=header)
    assert r.status_code == 422
    assert "SRV-022" in r.text


async def test_geodesy_saves_the_tie_and_imports_site_coordinates(
    client: AsyncClient, header: dict, project_id: str
) -> None:
    await _crs(client, header, project_id)
    r = await client.get(f"{BASE}/projects/{project_id}/geodesy", headers=header)
    assert r.status_code == 200 and r.json()["solution"] is None
    r = await client.put(
        f"{BASE}/projects/{project_id}/geodesy",
        json={"local_points": LOCAL, "apply_local_grid": True, "residual_tol_mm": 3},
        headers=header,
    )
    assert r.status_code == 200, r.text
    assert r.json()["solution"]["fitted"] == 2
    text = "C,1080,1050,0,STAKE\n"
    r = await client.post(
        f"{BASE}/projects/{project_id}/import",
        json={"text": text, "column_preset": "PNEZD", "delimiter": ",", "coords": "local"},
        headers=header,
    )
    assert r.status_code == 201, r.text
    pts = (await client.get(f"{BASE}/projects/{project_id}/points", headers=header)).json()["items"]
    [c] = [p for p in pts if p["point_id"] == "C"]
    assert abs(float(c["e"]) - 389055.183) < 0.002
    assert abs(float(c["n"]) - 5819104.166) < 0.002
    # Export back to the site grid returns what came in.
    r = await client.get(
        f"{BASE}/projects/{project_id}/export", params={"format": "csv", "local": "true"}, headers=header
    )
    assert r.status_code == 200, r.text
    line = r.text.splitlines()[1].split(",")
    assert line[0] == "C" and abs(float(line[1]) - 1080) < 0.001 and abs(float(line[2]) - 1050) < 0.001


async def test_scale_factor_worked_example(client: AsyncClient, header: dict, project_id: str) -> None:
    await _crs(client, header, project_id)
    r = await client.get(
        f"{BASE}/projects/{project_id}/scale-factor",
        params={"e": 389000, "n": 5819000, "h": 120, "d": 250},
        headers=header,
    )
    assert r.status_code == 200, r.text
    sf = r.json()
    assert abs(sf["csf"] - 0.99973288) < 2e-6
    assert abs(sf["grid_m"] - 249.933) < 0.001
    assert abs(sf["diff_mm"] - 67) < 1
    r = await client.post(f"{BASE}/projects/{project_id}/validate", headers=header)
    assert r.status_code == 200


async def test_scale_factor_is_empty_without_a_projected_crs(
    client: AsyncClient, header: dict, project_id: str
) -> None:
    r = await client.get(f"{BASE}/projects/{project_id}/scale-factor", params={"e": 1, "n": 2, "h": 0}, headers=header)
    assert r.status_code == 200 and r.json() is None


async def test_gsi_in_feet_needs_the_foot_for_a_metre_project(
    client: AsyncClient, header: dict, project_id: str
) -> None:
    await _crs(client, header, project_id)
    text = _gsi16("101", "7", 12762839800, 190912000000, 3937000) + "\n"
    body = {"text": text, "file_format": "gsi", "filename": "job.gsi"}
    r = await client.post(f"{BASE}/projects/{project_id}/import/preview", json=body, headers=header)
    assert r.status_code == 200, r.text
    preview = r.json()
    assert preview["file_unit"] == "feet"
    assert any(p["rule_id"] == "SRV-031" and p["message"] for p in preview["problems"])
    r = await client.post(f"{BASE}/projects/{project_id}/import", json=body, headers=header)
    assert r.status_code == 422
    r = await client.post(
        f"{BASE}/projects/{project_id}/import", json={**body, "foot_definition": "ftUS"}, headers=header
    )
    assert r.status_code == 201, r.text
    [p] = (await client.get(f"{BASE}/projects/{project_id}/points", headers=header)).json()["items"]
    assert abs(float(p["z"]) - 120.0) < 0.001  # 393.7 US survey feet


async def test_export_formats_and_a_crs_warning(client: AsyncClient, header: dict, project_id: str) -> None:
    await _crs(client, header, project_id)
    r = await client.post(
        f"{BASE}/projects/{project_id}/import",
        json={"text": "P1,5819020.111,389012.345,120.5,CTRL\n", "column_preset": "PNEZD", "delimiter": ","},
        headers=header,
    )
    assert r.status_code == 201, r.text
    for fmt, needle in (("geojson", "FeatureCollection"), ("gsi", "*11"), ("landxml", "<CgPoint"), ("dxf", "POINT")):
        r = await client.get(f"{BASE}/projects/{project_id}/export", params={"format": fmt}, headers=header)
        assert r.status_code == 200, (fmt, r.text)
        assert needle in r.text, fmt
        assert "attachment" in r.headers["content-disposition"]
        assert "x-survey-warnings" not in r.headers
    r = await client.get(
        f"{BASE}/projects/{project_id}/export", params={"format": "csv", "target_epsg": 25833}, headers=header
    )
    assert r.status_code == 200
    assert r.headers["x-survey-warnings"] == "SRV-110"
    r = await client.get(f"{BASE}/projects/{project_id}/export", params={"format": "xls"}, headers=header)
    assert r.status_code == 422


async def test_stake_export_and_sheet_carry_grid_and_ground(client: AsyncClient, header: dict, project_id: str) -> None:
    await _crs(client, header, project_id)
    r = await client.post(f"/api/v1/setting-out/projects/{project_id}/demo/riverside", headers=header)
    assert r.status_code in (200, 201), r.text
    req = r.json()
    r = await client.get(
        f"/api/v1/setting-out/requests/{req['id']}/export", params={"format": "landxml"}, headers=header
    )
    assert r.status_code == 200, r.text
    assert r.text.count("<CgPoint ") == len(req["stakes"])
    r = await client.get(f"/api/v1/setting-out/requests/{req['id']}/sheet.pdf", headers=header)
    assert r.status_code == 200
    assert r.content[:4] == b"%PDF"
