# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Point cloud upload, breaklines from point codes, and staged volumes through the API on PostgreSQL."""

from __future__ import annotations

import io

import numpy as np
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


def _las_bytes(cls: int) -> bytes:
    import laspy

    g = np.arange(0.25, 20.0, 0.5)
    gx, gy = np.meshgrid(389000.0 + g, 5819000.0 + g)
    header = laspy.LasHeader(point_format=1, version="1.4")
    header.offsets = [389000.0, 5819000.0, 0.0]
    header.scales = [0.001, 0.001, 0.001]
    las = laspy.LasData(header)
    las.x, las.y, las.z = gx.ravel(), gy.ravel(), np.full(gx.size, 10.0)
    las.classification = np.full(gx.size, cls, dtype=np.uint8)
    buf = io.BytesIO()
    las.write(buf)
    return buf.getvalue()


async def _crs(client: AsyncClient, header: dict, pid: str) -> None:
    r = await client.put(f"{CORE}/projects/{pid}/crs", json={"horizontal_epsg": 32633}, headers=header)
    assert r.status_code == 200, r.text


async def test_point_cloud_upload_and_staged_volumes(client: AsyncClient, header: dict, project_id: str) -> None:
    await _crs(client, header, project_id)
    r = await client.post(
        f"{BASE}/projects/{project_id}/surfaces/point-cloud",
        files={"file": ("drone.las", _las_bytes(2), "application/octet-stream")},
        data={"name": "Drone 01 Oct", "cell_size_m": "1", "stat": "min"},
        headers=header,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert (body["points_read"], body["cells"], body["used_all_classes"]) == (1600, 400, False)
    assert body["surface"]["source"] == "pointcloud"
    assert body["surface"]["findings"] == []
    ground = body["surface"]

    raw = await client.post(
        f"{BASE}/projects/{project_id}/surfaces/point-cloud",
        files={"file": ("raw.las", _las_bytes(1), "application/octet-stream")},
        data={"cell_size_m": "1"},
        headers=header,
    )
    assert raw.status_code == 201, raw.text
    assert raw.json()["used_all_classes"] is True
    assert [f["rule_id"] for f in raw.json()["surface"]["findings"]] == ["SRV-080"]

    bad = await client.post(
        f"{BASE}/projects/{project_id}/surfaces/point-cloud",
        files={"file": ("notes.txt", b"x", "text/plain")},
        headers=header,
    )
    assert bad.status_code == 422

    staged = await client.post(
        f"{BASE}/projects/{project_id}/staged-volumes",
        json={
            "stages": [
                {"surface_id": ground["id"], "label": "Ground"},
                {"strip_depth_m": 0.3, "label": "Stripped", "material": "topsoil"},
                {"strip_depth_m": 1.0, "label": "Bulk", "material": "clay"},
            ],
            "cell_size_m": 1,
            "factors": {"topsoil": {"loose": 1.25}},
        },
        headers=header,
    )
    assert staged.status_code == 200, staged.text
    s = staged.json()
    # Cell centres run 0.75 .. 19.75 m, so the surface is 19 x 19 = 361 m2.
    assert [st["cut_m3"] for st in s["steps"]] == [108.3, 361.0]
    assert s["steps"][0]["cut_loose_m3"] == 135.375
    assert s["steps"][1]["cut_loose_m3"] is None
    assert s["total_cut_m3"] == 469.3
    assert [f["rule_id"] for f in s["findings"]] == ["SRV-082"]


async def test_breaklines_strung_from_point_codes(client: AsyncClient, header: dict, project_id: str) -> None:
    await _crs(client, header, project_id)
    rows = ["1,5819000,389000,0", "2,5819000,389010,0", "3,5819010,389010,0", "4,5819010,389000,0"]
    rows += ["5,5819004.9,389005,0", "6,5819005.1,389005,0"]
    rows += ["7,5819005,389001,2,RIDGE", "8,5819005,389009,2,RIDGE"]
    r = await client.post(
        f"{CORE}/projects/{project_id}/import",
        json={"text": "\n".join(rows) + "\n", "filename": "ridge.csv", "column_preset": "PNEZD", "name": "Ridge"},
        headers=header,
    )
    assert r.status_code == 201, r.text
    set_id = r.json()["point_set"]["id"]
    s = await client.post(
        f"{BASE}/projects/{project_id}/surfaces/from-points",
        json={"name": "Ridge", "point_set_ids": [set_id], "breakline_codes": ["RIDGE"]},
        headers=header,
    )
    assert s.status_code == 201, s.text
    assert s.json()["breakline_count"] == 1
    assert s.json()["findings"] == []
    plan = (await client.get(f"{BASE}/projects/{project_id}/plan", headers=header)).json()
    assert any(f["properties"]["layer"] == "breaklines" for f in plan["features"])


async def test_a_viewer_cannot_upload_a_cloud(client: AsyncClient, viewer: dict, project_id: str) -> None:
    r = await client.post(
        f"{BASE}/projects/{project_id}/surfaces/point-cloud",
        files={"file": ("drone.las", _las_bytes(2), "application/octet-stream")},
        headers=viewer,
    )
    assert r.status_code in (403, 404)
