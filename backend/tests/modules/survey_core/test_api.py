# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The survey register end to end on the Riverside Yard lessons, against a real database.

Lesson numbers come from ``demo/riverside/expected.json``: the course reads
the same file, so a change here that breaks a lesson fails this suite.
"""

from __future__ import annotations

import json
from pathlib import Path

from httpx import AsyncClient

from tests.modules.survey_core.conftest import login

BASE = "/api/v1/survey-core"
DEMO = Path(__file__).resolve().parents[3] / "app" / "modules" / "survey_core" / "demo" / "riverside"
EXPECTED = json.loads((DEMO / "expected.json").read_text(encoding="utf-8"))["survey_register"]


def _file(name: str) -> str:
    return (DEMO / name).read_text(encoding="utf-8")


async def _set_crs(client: AsyncClient, header: dict, project_id: str, epsg: int = 32633, **extra) -> dict:
    response = await client.put(
        f"{BASE}/projects/{project_id}/crs", json={"horizontal_epsg": epsg, **extra}, headers=header
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _import(client: AsyncClient, header: dict, project_id: str, name: str, **extra) -> dict:
    body = {"text": _file(name), "filename": name, "column_preset": "PNEZD", "delimiter": ",", **extra}
    response = await client.post(f"{BASE}/projects/{project_id}/import", json=body, headers=header)
    assert response.status_code == 201, response.text
    return response.json()


async def test_lesson_1_crs_search_and_chip(client: AsyncClient, header: dict, project_id: str) -> None:
    lesson = EXPECTED["lesson_1"]
    hits = await client.get(f"{BASE}/crs/search", params={"q": lesson["search"]}, headers=header)
    assert hits.status_code == 200, hits.text
    assert hits.json()["items"][0]["epsg"] == 32633
    state = await client.get(f"{BASE}/projects/{project_id}/crs", headers=header)
    assert state.json()["crs"] is None
    assert any(s["epsg"] == 4326 and s["reason"] == "geographic" for s in state.json()["suggestions"])
    crs = await _set_crs(client, header, project_id)
    assert f"EPSG {crs['horizontal_epsg']}" == lesson["chip"]
    assert crs["horizontal_name"] == "WGS 84 / UTM zone 33N"
    assert crs["confirmed_at"] is not None


async def test_lesson_2_control_points(client: AsyncClient, header: dict, project_id: str) -> None:
    lesson = EXPECTED["lesson_2"]
    await _set_crs(client, header, project_id)
    result = await _import(client, header, project_id, lesson["file"])
    assert result["imported"] == lesson["points"]
    points = await client.get(f"{BASE}/projects/{project_id}/points", params={"kind": "control"}, headers=header)
    assert points.json()["total"] == lesson["points"]
    cp2 = next(p for p in points.json()["items"] if p["point_id"] == EXPECTED["lesson_5"]["point"])
    assert (cp2["e"], cp2["n"]) == (EXPECTED["lesson_5"]["e"], EXPECTED["lesson_5"]["n"])


async def test_lesson_3_preview_then_keep_first(client: AsyncClient, header: dict, project_id: str) -> None:
    lesson = EXPECTED["lesson_3"]
    await _set_crs(client, header, project_id)
    preview = await client.post(
        f"{BASE}/projects/{project_id}/import/preview", json={"text": _file(lesson["file"])}, headers=header
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["rows_read"] == lesson["rows_read"]
    assert body["problem_count"] == lesson["problems"]
    assert body["problems"][0]["rule_id"] == lesson["problem_rule"]
    assert body["problems"][0]["point_id"] == lesson["problem_point"]
    assert body["preset"]["value"] == lesson["preset"]
    assert body["delimiter"]["value"] == ","
    assert len(body["rows"]) == 20
    assert body["will_transform"] is False
    # Preview saves nothing.
    empty = await client.get(f"{BASE}/projects/{project_id}/points", headers=header)
    assert empty.json()["total"] == 0

    result = await _import(client, header, project_id, lesson["file"], duplicate_policy=lesson["duplicate_policy"])
    assert result["imported"] == lesson["points_after_import"]
    report = await client.post(f"{BASE}/projects/{project_id}/validate", headers=header)
    assert report.json()["error_count"] == 0


async def test_srv003_against_points_already_in_the_register(
    client: AsyncClient, header: dict, project_id: str
) -> None:
    await _set_crs(client, header, project_id)
    await _import(client, header, project_id, "existing_ground.csv", duplicate_policy="keep_first")
    await _import(client, header, project_id, "existing_ground.csv", duplicate_policy="keep_last")
    report = (await client.post(f"{BASE}/projects/{project_id}/validate", headers=header)).json()
    # SRV-025 also speaks here: the fixture sits far from the zone meridian, so grid and ground differ.
    assert [f["rule_id"] for f in report["findings"] if f["rule_id"] != "SRV-025"] == ["SRV-003"]
    assert next(f for f in report["findings"] if f["rule_id"] == "SRV-003")["element_ref"] == "EG-045"
    summary = (await client.get(f"{BASE}/projects/{project_id}/summary", headers=header)).json()
    assert summary == {**summary, "points": 154, "point_sets": 2, "findings": 2}  # SRV-003 and SRV-025


async def test_srv001_import_without_crs_then_declare(client: AsyncClient, header: dict, project_id: str) -> None:
    result = await _import(client, header, project_id, "control.csv")
    assert result["point_set"]["stored_epsg"] is None
    report = (await client.post(f"{BASE}/projects/{project_id}/validate", headers=header)).json()
    assert [f["rule_id"] for f in report["findings"]] == ["SRV-001"]
    declared = await client.post(
        f"{BASE}/point-sets/{result['point_set']['id']}/declare-crs", json={"epsg": 32633}, headers=header
    )
    assert declared.status_code == 200, declared.text
    report = (await client.post(f"{BASE}/projects/{project_id}/validate", headers=header)).json()
    assert report["findings"] == []


async def test_preview_detects_crs_when_none_is_set(client: AsyncClient, header: dict, project_id: str) -> None:
    preview = await client.post(
        f"{BASE}/projects/{project_id}/import/preview", json={"text": _file("control.csv")}, headers=header
    )
    assert preview.status_code == 200, preview.text
    detected = preview.json()["detected_crs"]
    if detected is not None:
        assert detected["reason"] == "detected"
        assert 0 <= detected["confidence"] <= 1


async def test_srv002_editor_accepting_a_detected_crs_leaves_it_unconfirmed(
    client: AsyncClient, header: dict, project_id: str
) -> None:
    editor = await login(client, "editor")
    await _add_member(client, header, project_id, editor)
    crs = await _set_crs(client, editor, project_id, source="detected", detected_confidence=0.92)
    assert crs["confirmed_at"] is None
    report = (await client.post(f"{BASE}/projects/{project_id}/validate", headers=header)).json()
    assert [f["rule_id"] for f in report["findings"]] == ["SRV-002"]
    denied = await client.post(f"{BASE}/projects/{project_id}/crs/confirm", headers=editor)
    assert denied.status_code == 403
    confirmed = await client.post(f"{BASE}/projects/{project_id}/crs/confirm", headers=header)
    assert confirmed.status_code == 200, confirmed.text
    report = (await client.post(f"{BASE}/projects/{project_id}/validate", headers=header)).json()
    assert report["findings"] == []


async def test_surveyor_role_may_confirm(client: AsyncClient, header: dict, project_id: str) -> None:
    surveyor = await login(client, "surveyor")
    await _add_member(client, header, project_id, surveyor)
    crs = await _set_crs(client, surveyor, project_id, source="detected", detected_confidence=0.8)
    assert crs["confirmed_at"] is not None


async def test_changing_crs_with_points_needs_the_code_typed(
    client: AsyncClient, header: dict, project_id: str
) -> None:
    await _set_crs(client, header, project_id)
    await _import(client, header, project_id, "control.csv")
    refused = await client.put(f"{BASE}/projects/{project_id}/crs", json={"horizontal_epsg": 25833}, headers=header)
    assert refused.status_code == 409
    changed = await _set_crs(client, header, project_id, 25833, confirm_text="25833")
    assert changed["horizontal_epsg"] == 25833
    from sqlalchemy import select

    from app.core.audit import AuditEntry
    from app.database import async_session_factory

    async with async_session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(AuditEntry.action).where(
                        AuditEntry.entity_type == "survey_project_crs", AuditEntry.entity_id == project_id
                    )
                )
            )
            .scalars()
            .all()
        )
    assert sorted(rows) == ["create", "update"]


async def test_geojson_in_wgs84_is_transformed_only_with_the_preview_saying_so(
    client: AsyncClient, header: dict, project_id: str
) -> None:
    await _set_crs(client, header, project_id)
    doc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [15.0, 0.0, 1.0]},
                "properties": {"name": "EQ"},
            }
        ],
    }
    body = {"text": json.dumps(doc), "file_format": "geojson", "filename": "eq.geojson"}
    preview = (await client.post(f"{BASE}/projects/{project_id}/import/preview", json=body, headers=header)).json()
    assert (preview["source_epsg"], preview["target_epsg"], preview["will_transform"]) == (4326, 32633, True)
    assert abs(preview["rows"][0]["e"] - 500000.0) < 1e-3
    result = (await client.post(f"{BASE}/projects/{project_id}/import", json=body, headers=header)).json()
    assert result["point_set"]["transformed"] is True
    assert result["point_set"]["source_epsg"] == 4326


async def test_transform_endpoint(client: AsyncClient, header: dict) -> None:
    response = await client.post(
        f"{BASE}/transform", json={"source_epsg": 4326, "target_epsg": 32633, "points": [[15.0, 0.0]]}, headers=header
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["target"]["name"] == "WGS 84 / UTM zone 33N"
    assert abs(body["points"][0][0] - 500000.0) < 1e-6
    bad = await client.post(
        f"{BASE}/transform", json={"source_epsg": 4326, "target_epsg": 999999, "points": [[15.0, 0.0]]}, headers=header
    )
    assert bad.status_code == 422


async def test_viewer_reads_but_cannot_import(client: AsyncClient, header: dict, project_id: str, viewer: dict) -> None:
    await _add_member(client, header, project_id, viewer)
    body = {"text": _file("control.csv"), "column_preset": "PNEZD"}
    denied = await client.post(f"{BASE}/projects/{project_id}/import", json=body, headers=viewer)
    assert denied.status_code == 403


async def test_stranger_cannot_read_another_project(
    client: AsyncClient, header: dict, project_id: str, stranger: dict
) -> None:
    response = await client.get(f"{BASE}/projects/{project_id}/points", headers=stranger)
    assert response.status_code in (403, 404)


async def test_delete_point_set_removes_its_points(client: AsyncClient, header: dict, project_id: str) -> None:
    await _set_crs(client, header, project_id)
    result = await _import(client, header, project_id, "control.csv")
    deleted = await client.delete(f"{BASE}/point-sets/{result['point_set']['id']}", headers=header)
    assert deleted.status_code == 204
    points = await client.get(f"{BASE}/projects/{project_id}/points", headers=header)
    assert points.json()["total"] == 0


async def _add_member(client: AsyncClient, owner: dict, project_id: str, member: dict) -> None:
    """Add ``member`` to the owner's project team."""
    me = await client.get("/api/v1/users/me", headers=member)
    assert me.status_code == 200, me.text
    response = await client.post(
        f"/api/v1/projects/{project_id}/members", json={"user_id": me.json()["id"], "role": "member"}, headers=owner
    )
    assert response.status_code in (200, 201), response.text
