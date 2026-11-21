# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Scan against design, cut and fill to a draft volume, and the exports, through the API on PostgreSQL."""

from __future__ import annotations

import io
import uuid

import numpy as np
import pytest
from httpx import AsyncClient

from app.modules.pointcloud.survey_demo import expected
from tests.modules.survey_core.conftest import (  # noqa: F401
    app_instance,
    client,
    header,
    login,
    project_id,
    stranger,
    viewer,
)

PC = "/api/v1/pointcloud"
CORE = "/api/v1/survey-core"
EXP = expected()


def _flat_pad_las(z: float) -> bytes:
    import laspy

    # Gridded at 2 m the surface keeps cell centres, which sit 1 m inside the cloud's edge. The cloud is one
    # cell wider than the pad on every side so the design surface still covers every scan point.
    gx, gy = np.meshgrid(np.arange(388998.0, 389102.5, 2.0), np.arange(5818998.0, 5819062.5, 2.0))
    head = laspy.LasHeader(point_format=1, version="1.4")
    head.offsets = [388998.0, 5818998.0, 0.0]
    head.scales = [0.001, 0.001, 0.001]
    las = laspy.LasData(head)
    las.x, las.y, las.z = gx.ravel(), gy.ravel(), np.full(gx.size, z)
    las.classification = np.full(gx.size, 2, dtype=np.uint8)
    buf = io.BytesIO()
    las.write(buf)
    return buf.getvalue()


async def _riverside(client: AsyncClient, header: dict, pid: str) -> tuple[str, str]:
    """The design pad uploaded as a flat cloud, then the demo scan seeded the way the demo installer does."""
    r = await client.put(f"{CORE}/projects/{pid}/crs", json={"horizontal_epsg": 32633}, headers=header)
    assert r.status_code == 200, r.text
    r = await client.post(
        f"{PC}/projects/{pid}/surfaces/cloud",
        files={"file": ("pad.las", _flat_pad_las(EXP["scan"]["design_z"]), "application/octet-stream")},
        data={"name": EXP["scan"]["design_surface"], "cell_size_m": "2"},
        headers=header,
    )
    assert r.status_code == 201, r.text
    surface_id = r.json()["surface"]["id"]

    me = await client.get("/api/v1/users/me", headers=header)
    assert me.status_code == 200, me.text
    from app.database import async_session_factory
    from app.modules.pointcloud.survey_demo import seed_riverside_scan

    async with async_session_factory() as session:
        seeded = await seed_riverside_scan(session, uuid.UUID(pid), uuid.UUID(me.json()["id"]))
        await session.commit()
    assert seeded["pointcloud_scans"] == 1
    assert seeded["scan_within_pct"] == EXP["deviation"]["within_pct"]
    scan_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"oe:riverside-scan:{pid}"))
    return scan_id, surface_id


async def test_seeded_report_carries_the_expected_numbers(client: AsyncClient, header: dict, project_id: str) -> None:
    scan_id, surface_id = await _riverside(client, header, project_id)
    listed = await client.get(f"{PC}/scans/{scan_id}/deviation-reports", headers=header)
    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] == 1
    report = listed.json()["items"][0]
    exp = EXP["deviation"]
    assert report["surface_id"] == surface_id
    assert report["tolerance"]["v_mm"] == exp["tolerance_mm"]
    stats = report["stats"]
    for key in ("points_compared", "mean_mm", "rms_mm", "p95_mm", "within_pct", "high_pct", "out_count"):
        assert stats[key] == exp[key], key
    assert report["severity"] == exp["severity"]
    assert [f["rule_id"] for f in report["findings"]] == exp["findings"]
    assert report["heat"] is None  # the list leaves the heat grid out

    one = await client.get(f"{PC}/deviation-reports/{report['id']}", headers=header)
    assert one.json()["heat"]["nx"] > 0
    again = await client.get(f"{PC}/deviation-reports/{report['id']}", headers=header, params={"locale": "de"})
    assert again.status_code == 200
    assert "Scanpunkte" in again.json()["findings"][0]["message"]


async def test_compare_points_and_exports(client: AsyncClient, header: dict, project_id: str) -> None:
    scan_id, surface_id = await _riverside(client, header, project_id)
    r = await client.post(
        f"{PC}/scans/{scan_id}/deviation-reports",
        json={"surface_id": surface_id, "tolerance_key": "demo", "ground_only": False, "threshold_pct": 10.0},
        headers=header,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["stats"]["points_compared"] == EXP["deviation_all_classes"]["points_compared"]
    assert body["findings"] == []  # 7.75 % out is under a 10 % threshold

    pts = await client.get(f"{PC}/deviation-reports/{body['id']}/points", headers=header)
    assert pts.status_code == 200
    assert pts.headers["X-Point-Count-Total"] == str(EXP["scan"]["points"])
    assert pts.content[:4] == b"OEPC"

    csv = await client.get(f"{PC}/deviation-reports/{body['id']}/export", params={"format": "csv"}, headers=header)
    assert csv.status_code == 200
    assert "rms_mm" in csv.text
    pdf = await client.get(f"{PC}/deviation-reports/{body['id']}/export", params={"format": "pdf"}, headers=header)
    assert pdf.status_code == 200
    assert pdf.content[:4] == b"%PDF"

    bad = await client.post(
        f"{PC}/scans/{scan_id}/deviation-reports",
        json={"surface_id": surface_id, "tolerance_key": "no-such-profile"},
        headers=header,
    )
    assert bad.status_code == 422


async def test_cut_fill_preview_then_draft_volume(client: AsyncClient, header: dict, project_id: str) -> None:
    scan_id, surface_id = await _riverside(client, header, project_id)
    exp = EXP["cutfill"]
    req = {"surface_id": surface_id, "cell_size_m": exp["cell_size_m"], "stat": exp["stat"], "method": exp["method"]}
    preview = await client.post(f"{PC}/scans/{scan_id}/cutfill/preview", json=req, headers=header)
    assert preview.status_code == 200, preview.text
    p = preview.json()
    assert p["cut_m3"] == pytest.approx(exp["cut_m3"], abs=0.01)
    assert p["fill_m3"] == pytest.approx(exp["fill_m3"], abs=0.01)

    made = await client.post(f"{PC}/scans/{scan_id}/cutfill", json={**req, "name": "Pad as built"}, headers=header)
    assert made.status_code == 201, made.text
    m = made.json()
    assert m["status"] == "draft"  # a person confirms before anything reaches the BOQ
    assert m["net_m3"] == pytest.approx(p["net_m3"], abs=1e-6)
    vols = await client.get(f"/api/v1/surfaces-volumes/projects/{project_id}/volumes", headers=header)
    assert vols.status_code == 200, vols.text
    assert m["volume_id"] in vols.text


async def test_access(client: AsyncClient, header: dict, viewer: dict, stranger: dict, project_id: str) -> None:
    scan_id, surface_id = await _riverside(client, header, project_id)
    listed = await client.get(f"{PC}/scans/{scan_id}/deviation-reports", headers=header)
    rid = listed.json()["items"][0]["id"]
    denied = await client.post(
        f"{PC}/scans/{scan_id}/deviation-reports", json={"surface_id": surface_id}, headers=viewer
    )
    assert denied.status_code == 403
    for path in (f"{PC}/deviation-reports/{rid}", f"{PC}/scans/{scan_id}/deviation-reports"):
        assert (await client.get(path, headers=stranger)).status_code in (403, 404)
    made = await client.post(f"{PC}/scans/{scan_id}/cutfill", json={"surface_id": surface_id}, headers=viewer)
    assert made.status_code == 403
