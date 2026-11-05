"""Survey captures end to end through the API against PostgreSQL.

Covers: create from upload / from scan, observation upsert, planned progress
(before / inside / after the activity, baseline vs current), tolerance status,
delete keeping the linked scan, and tenant isolation.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
import pytest_asyncio

from app.modules.geo_hub import survey_service

from .test_geotiff_sniff import make_geotiff

BASE = "/api/v1/geo-hub/surveys"
RASTER = "/api/v1/geo-hub/raster-overlays"


def _upload(client, headers, project_id, *, content=None, captured_on="2026-03-11", filename="site.tif", **extra):
    data = {"project_id": project_id, "captured_on": captured_on, "platform": "drone", **extra}
    files = {
        "file": (
            filename,
            content if content is not None else make_geotiff(origin=(13.40, 52.52), scale=(0.0001, 0.0001)),
            "image/tiff",
        )
    }
    return client.post(f"{BASE}/orthophoto", data=data, files=files, headers=headers)


async def _seed_schedule(project_id: str, rows: list[tuple[str, str, str, str]]) -> dict[str, str]:
    """Insert a schedule with activities ``(code, name, start, end)``; return ``{code: activity_id}``."""
    from app.database import async_session_factory
    from app.modules.schedule.models import Activity, Schedule

    out: dict[str, str] = {}
    async with async_session_factory() as s:
        sched = Schedule(project_id=uuid.UUID(project_id), name="Master")
        s.add(sched)
        await s.flush()
        for code, name, start, end in rows:
            act = Activity(schedule_id=sched.id, name=name, wbs_code=code, start_date=start, end_date=end)
            s.add(act)
            await s.flush()
            out[code] = str(act.id)
        out["_schedule"] = str(sched.id)
        await s.commit()
    return out


async def _seed_baseline(project_id: str, schedule_id: str, activity_id: str, start: str, end: str) -> None:
    from app.database import async_session_factory
    from app.modules.schedule.models import ScheduleBaseline

    async with async_session_factory() as s:
        s.add(
            ScheduleBaseline(
                schedule_id=uuid.UUID(schedule_id),
                project_id=uuid.UUID(project_id),
                name="Baseline 1",
                baseline_date="2026-01-01",
                snapshot_data={"activities": [{"id": activity_id, "start_date": start, "end_date": end}]},
                is_active=True,
            )
        )
        await s.commit()


async def _seed_scan(project_id: str, captured_on: str | None) -> str:
    from app.database import async_session_factory
    from app.modules.pointcloud.models import ScanDataset

    async with async_session_factory() as s:
        scan = ScanDataset(
            project_id=uuid.UUID(project_id),
            tenant_id=uuid.uuid4(),
            source_type="photogrammetry",
            original_format="las",
            crs_epsg=4326,
            scan_metadata={"captured_on": captured_on} if captured_on else {},
        )
        s.add(scan)
        await s.commit()
        return str(scan.id)


async def _scan_exists(scan_id: str) -> bool:
    from app.database import async_session_factory
    from app.modules.pointcloud.models import ScanDataset

    async with async_session_factory() as s:
        return await s.get(ScanDataset, uuid.UUID(scan_id)) is not None


@pytest_asyncio.fixture
async def survey(http_client, tenant_a):
    res = await _upload(http_client, tenant_a["headers"], tenant_a["project_id"])
    assert res.status_code == 201, res.text
    return res.json()


@pytest.mark.asyncio
async def test_orthophoto_upload_returns_the_sniffed_header(http_client, tenant_a) -> None:
    res = await _upload(http_client, tenant_a["headers"], tenant_a["project_id"], name="Flight 1")
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["kind"] == "orthophoto" and body["name"] == "Flight 1"
    assert body["crs_epsg"] == 4326
    assert body["captured_on"] == "2026-03-11"
    assert float(body["gsd_cm"]) > 0
    assert body["overlay_id"] and body["scan_id"] is None
    assert body["warnings"] == []
    png = await http_client.get(f"{RASTER}/{body['overlay_id']}/raster.png", headers=tenant_a["headers"])
    assert png.status_code == 200 and png.content.startswith(b"\x89PNG")

    listed = await http_client.get(f"{BASE}/?project_id={tenant_a['project_id']}", headers=tenant_a["headers"])
    assert listed.status_code == 200 and body["id"] in [r["id"] for r in listed.json()["items"]]
    assert listed.json()["total"] == 1


@pytest.mark.asyncio
async def test_ungeoreferenced_tiff_is_accepted_with_a_warning(http_client, tenant_a) -> None:
    res = await _upload(http_client, tenant_a["headers"], tenant_a["project_id"], content=make_geotiff(epsg=None))
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["crs_epsg"] is None and body["bbox_min_lat"] is None
    assert "not_georeferenced" in body["warnings"]
    assert "geo_hub.survey.georeferenced" in [f["rule_id"] for f in body["findings"]]


@pytest.mark.asyncio
async def test_bad_uploads_are_refused(http_client, tenant_a) -> None:
    h, pid = tenant_a["headers"], tenant_a["project_id"]
    assert (await _upload(http_client, h, pid, captured_on="2999-01-01")).status_code == 422
    assert (await _upload(http_client, h, pid, filename="site.png")).status_code == 415
    assert (await _upload(http_client, h, pid, content=b"hello world, not a tiff")).status_code == 415
    assert (await _upload(http_client, h, pid, content=b"II*\x00" + b"\xff" * 16)).status_code == 422


@pytest.mark.asyncio
async def test_far_away_footprint_warns_about_the_anchor(http_client, tenant_a) -> None:
    far = make_geotiff(origin=(2.30, 48.86), scale=(0.0001, 0.0001))
    res = await _upload(http_client, tenant_a["headers"], tenant_a["project_id"], content=far)
    assert res.status_code == 201, res.text
    assert "geo_hub.survey.bbox_intersects_anchor" in [f["rule_id"] for f in res.json()["findings"]]


@pytest.mark.asyncio
async def test_survey_from_scan_defaults_the_date_from_scan_metadata(http_client, tenant_a) -> None:
    scan_id = await _seed_scan(tenant_a["project_id"], "2026-02-02")
    res = await http_client.post(f"{BASE}/from-scan", json={"scan_id": scan_id}, headers=tenant_a["headers"])
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["kind"] == "point_cloud" and body["scan_id"] == scan_id and body["overlay_id"] is None
    assert body["captured_on"] == "2026-02-02"

    explicit = await http_client.post(
        f"{BASE}/from-scan",
        json={"scan_id": scan_id, "captured_on": "2026-02-10", "platform": "ground"},
        headers=tenant_a["headers"],
    )
    assert explicit.json()["captured_on"] == "2026-02-10" and explicit.json()["platform"] == "ground"


@pytest.mark.asyncio
async def test_observation_upsert_replaces_and_stamps(http_client, tenant_a, survey) -> None:
    acts = await _seed_schedule(tenant_a["project_id"], [("A1", "Excavation", "2026-03-01", "2026-03-21")])
    url = f"{BASE}/{survey['id']}/observations/{acts['A1']}"
    first = await http_client.put(url, json={"observed_pct": "40", "note": "north half"}, headers=tenant_a["headers"])
    assert first.status_code == 200, first.text
    assert first.json()["confirmed_by"] and first.json()["confirmed_at"]
    second = await http_client.put(url, json={"observed_pct": "65.5", "note": "all"}, headers=tenant_a["headers"])
    assert second.json()["id"] == first.json()["id"]
    assert float(second.json()["observed_pct"]) == 65.5 and second.json()["note"] == "all"

    assert (await http_client.put(url, json={"observed_pct": "101"}, headers=tenant_a["headers"])).status_code == 422
    assert (await http_client.put(url, json={"observed_pct": "-1"}, headers=tenant_a["headers"])).status_code == 422
    stranger = f"{BASE}/{survey['id']}/observations/{uuid.uuid4()}"
    assert (
        await http_client.put(stranger, json={"observed_pct": "10"}, headers=tenant_a["headers"])
    ).status_code == 404


@pytest.mark.asyncio
async def test_progress_interpolates_and_classifies(http_client, tenant_a, survey) -> None:
    # Survey is dated 2026-03-11.
    acts = await _seed_schedule(
        tenant_a["project_id"],
        [
            ("INSIDE", "Halfway", "2026-03-01", "2026-03-21"),
            ("LATER", "Not started", "2026-04-01", "2026-04-30"),
            ("DONE", "Finished", "2026-02-01", "2026-02-20"),
            ("OPEN", "No observation", "2026-03-01", "2026-03-21"),
        ],
    )
    h = tenant_a["headers"]
    for code, pct in (("INSIDE", "70"), ("LATER", "0"), ("DONE", "60")):
        res = await http_client.put(
            f"{BASE}/{survey['id']}/observations/{acts[code]}", json={"observed_pct": pct}, headers=h
        )
        assert res.status_code == 200, res.text

    rows = {r["code"]: r for r in (await http_client.get(f"{BASE}/{survey['id']}/progress", headers=h)).json()["items"]}
    cut = (await http_client.get(f"{BASE}/{survey['id']}/progress?limit=1", headers=h)).json()
    assert len(cut["items"]) == 1 and cut["total"] == 4
    assert rows["INSIDE"]["planned_pct_on_date"] == 50.0 and rows["INSIDE"]["variance_pct"] == 20.0
    assert rows["INSIDE"]["status"] == "ahead"
    assert rows["LATER"]["planned_pct_on_date"] == 0.0 and rows["LATER"]["status"] == "on_track"
    assert rows["DONE"]["planned_pct_on_date"] == 100.0 and rows["DONE"]["variance_pct"] == -40.0
    assert rows["DONE"]["status"] == "behind"
    assert rows["OPEN"]["observed_pct"] is None and rows["OPEN"]["status"] == "unobserved"


@pytest.mark.asyncio
async def test_progress_prefers_the_baseline_dates(http_client, tenant_b) -> None:
    pid, h = tenant_b["project_id"], tenant_b["headers"]
    res = await _upload(http_client, h, pid)
    assert res.status_code == 201, res.text
    acts = await _seed_schedule(pid, [("B1", "Slab", "2026-03-01", "2026-03-31")])
    before = {
        r["code"]: r for r in (await http_client.get(f"{BASE}/{res.json()['id']}/progress", headers=h)).json()["items"]
    }
    assert 30 < before["B1"]["planned_pct_on_date"] < 35  # current plan: 10 of 30 days

    await _seed_baseline(pid, acts["_schedule"], acts["B1"], "2026-03-01", "2026-03-21")
    after = {
        r["code"]: r for r in (await http_client.get(f"{BASE}/{res.json()['id']}/progress", headers=h)).json()["items"]
    }
    assert after["B1"]["planned_pct_on_date"] == 50.0  # baseline: 10 of 20 days


@pytest.mark.asyncio
async def test_deleting_removes_the_overlay_but_never_the_scan(http_client, tenant_a, survey) -> None:
    h = tenant_a["headers"]
    assert (await http_client.delete(f"{BASE}/{survey['id']}", headers=h)).status_code == 204
    assert (await http_client.get(f"{BASE}/{survey['id']}", headers=h)).status_code == 404
    assert (await http_client.get(f"{RASTER}/{survey['overlay_id']}", headers=h)).status_code == 404

    scan_id = await _seed_scan(tenant_a["project_id"], None)
    cap = (await http_client.post(f"{BASE}/from-scan", json={"scan_id": scan_id}, headers=h)).json()
    assert (await http_client.delete(f"{BASE}/{cap['id']}", headers=h)).status_code == 204
    assert await _scan_exists(scan_id)


@pytest.mark.asyncio
async def test_patch_revalidates_the_date(http_client, tenant_a, survey) -> None:
    h = tenant_a["headers"]
    ok = await http_client.patch(f"{BASE}/{survey['id']}", json={"name": "Renamed", "platform": "aircraft"}, headers=h)
    assert ok.status_code == 200 and ok.json()["name"] == "Renamed" and ok.json()["platform"] == "aircraft"
    bad = await http_client.patch(f"{BASE}/{survey['id']}", json={"captured_on": "2999-01-01"}, headers=h)
    assert bad.status_code == 422


@pytest.mark.asyncio
async def test_other_tenants_get_404_everywhere(http_client, tenant_a, tenant_b, tenant_manager, survey) -> None:
    hb = tenant_b["headers"]
    sid = survey["id"]
    assert (await http_client.get(f"{BASE}/{sid}", headers=hb)).status_code == 404
    assert (await http_client.get(f"{BASE}/{sid}/progress", headers=hb)).status_code == 404
    assert (await http_client.get(f"{BASE}/?project_id={tenant_a['project_id']}", headers=hb)).status_code == 404
    assert (await http_client.patch(f"{BASE}/{sid}", json={"name": "x"}, headers=hb)).status_code == 404
    assert (
        await http_client.put(f"{BASE}/{sid}/observations/{uuid.uuid4()}", json={"observed_pct": "1"}, headers=hb)
    ).status_code == 404
    # Delete is a manager permission: the editor is stopped at the gate, a manager of another tenant at ownership.
    assert (await http_client.delete(f"{BASE}/{sid}", headers=hb)).status_code == 403
    assert (await http_client.delete(f"{BASE}/{sid}", headers=tenant_manager["headers"])).status_code == 404
    assert (await _upload(http_client, hb, tenant_a["project_id"])).status_code == 404
    scan_id = await _seed_scan(tenant_a["project_id"], None)
    assert (await http_client.post(f"{BASE}/from-scan", json={"scan_id": scan_id}, headers=hb)).status_code == 404


@pytest.mark.asyncio
async def test_upload_over_the_size_limit_is_413(http_client, tenant_a, monkeypatch) -> None:
    monkeypatch.setattr(survey_service, "MAX_SURVEY_UPLOAD_BYTES", 512)
    res = await _upload(http_client, tenant_a["headers"], tenant_a["project_id"], content=make_geotiff(size=(200, 200)))
    assert res.status_code == 413


def test_the_fixture_date_is_in_the_past() -> None:
    assert date(2026, 3, 11) < date.today()
