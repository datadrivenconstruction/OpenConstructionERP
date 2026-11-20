# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Plan editor routes against a real database: transform, settings, codes, edits with history and conflicts."""

from __future__ import annotations

from pathlib import Path

from httpx import AsyncClient

BASE = "/api/v1/survey-core"
DEMO = Path(__file__).resolve().parents[3] / "app" / "modules" / "survey_core" / "demo" / "riverside"


async def _setup(client: AsyncClient, header: dict, project_id: str, local: bool = False) -> None:
    body = {"is_local_grid": True, "local_origin_e": 0, "local_origin_n": 0} if local else {"horizontal_epsg": 32633}
    r = await client.put(f"{BASE}/projects/{project_id}/crs", json=body, headers=header)
    assert r.status_code == 200, r.text
    text = (DEMO / "existing_ground.csv").read_text(encoding="utf-8")
    r = await client.post(
        f"{BASE}/projects/{project_id}/import",
        json={
            "text": text,
            "filename": "eg.csv",
            "column_preset": "PNEZD",
            "delimiter": ",",
            "duplicate_policy": "keep_first",
        },
        headers=header,
    )
    assert r.status_code == 201, r.text


async def test_view_transform_fits_the_work_extent(client: AsyncClient, header: dict, project_id: str) -> None:
    await _setup(client, header, project_id)
    r = await client.get(f"{BASE}/projects/{project_id}/view-transform", headers=header)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "polynomial" and body["epsg"] == 32633
    assert body["residual_mm"] < 1.0
    assert body["extent"] == [389000.0, 5819000.0, 389100.0, 5819060.0]


async def test_local_grid_gets_a_local_view(client: AsyncClient, header: dict, project_id: str) -> None:
    await _setup(client, header, project_id, local=True)
    body = (await client.get(f"{BASE}/projects/{project_id}/view-transform", headers=header)).json()
    assert body["kind"] == "local" and body["epsg"] is None
    assert (body["e0"], body["n0"]) == (389050.0, 5819030.0)


async def test_settings_default_then_project_override(client: AsyncClient, header: dict, project_id: str) -> None:
    await _setup(client, header, project_id)
    first = (await client.get(f"{BASE}/projects/{project_id}/plan-settings", headers=header)).json()
    assert first["source"] in ("neutral", "country")
    assert 0.999 < first["csf"] < 1.0
    r = await client.put(
        f"{BASE}/projects/{project_id}/plan-settings",
        json={"conventions": {"angleUnit": "gon", "x": 1}},
        headers=header,
    )
    assert r.status_code == 200, r.text
    assert r.json()["source"] == "project" and r.json()["conventions"]["angleUnit"] == "gon"
    reset = await client.put(f"{BASE}/projects/{project_id}/plan-settings", json={"conventions": None}, headers=header)
    assert reset.json()["source"] != "project"


async def test_code_library_put_reset_and_duplicates(client: AsyncClient, header: dict, project_id: str) -> None:
    neutral = (await client.get(f"{BASE}/projects/{project_id}/codes", headers=header)).json()
    assert neutral["source"] == "neutral" and any(c["code"] == "EP" for c in neutral["items"])
    own = [{"code": "ep", "label": "Edge", "line": "open", "colour": "kerb"}]
    r = await client.put(f"{BASE}/projects/{project_id}/codes", json={"items": own}, headers=header)
    assert r.status_code == 200, r.text
    assert r.json()["source"] == "project" and r.json()["items"][0]["code"] == "EP"
    dup = await client.put(f"{BASE}/projects/{project_id}/codes", json={"items": own + own}, headers=header)
    assert dup.status_code == 422
    back = await client.put(f"{BASE}/projects/{project_id}/codes", json={"items": None}, headers=header)
    assert back.json()["source"] == "neutral"


async def test_point_move_records_history_and_refuses_a_stale_revision(
    client: AsyncClient, header: dict, project_id: str
) -> None:
    await _setup(client, header, project_id)
    points = (await client.get(f"{BASE}/projects/{project_id}/plan-points", headers=header)).json()["items"]
    mh = next(p for p in points if p["code"] == "MH")
    assert mh["rev"] == 0 and mh["source_line"] is not None
    moved = {
        "layer": "points",
        "geometry": {"type": "Point", "coordinates": [mh["e"] + 0.25, mh["n"], mh["z"]]},
        "properties": {"label": mh["point_id"], "code": "MH"},
    }
    op = {
        "entity_type": "point",
        "entity_id": mh["id"],
        "op": "update",
        "base_rev": 0,
        "after": moved,
        "client_id": "c1",
    }
    r = await client.post(f"{BASE}/projects/{project_id}/edits", json={"ops": [op]}, headers=header)
    assert r.status_code == 200, r.text
    assert r.json()["items"][0]["rev"] == 1
    again = await client.post(f"{BASE}/projects/{project_id}/edits", json={"ops": [op]}, headers=header)
    assert again.status_code == 409
    detail = again.json()["detail"]
    assert detail["code"] == "stale_rev" and detail["current_rev"] == 1 and detail["author_name"]

    history = (
        await client.get(
            f"{BASE}/projects/{project_id}/edits",
            params={"entity_type": "point", "entity_id": mh["id"]},
            headers=header,
        )
    ).json()["items"]
    assert [h["rev"] for h in history] == [1]
    assert history[0]["summary"] == "+0.250 / +0.000"
    assert history[0]["before"]["geometry"]["coordinates"][0] == mh["e"]

    after = (await client.get(f"{BASE}/projects/{project_id}/plan-points", headers=header)).json()["items"]
    assert next(p for p in after if p["id"] == mh["id"])["e"] == mh["e"] + 0.25


async def test_sketch_create_update_delete_and_restore(client: AsyncClient, header: dict, project_id: str) -> None:
    line = {"layer": "sketch", "geometry": {"type": "LineString", "coordinates": [[0, 0], [10, 0]]}, "properties": {}}
    r = await client.post(
        f"{BASE}/projects/{project_id}/edits",
        json={"ops": [{"entity_type": "sketch", "op": "create", "after": line, "client_id": "tmp-1"}]},
        headers=header,
    )
    assert r.status_code == 200, r.text
    created = r.json()["items"][0]
    assert created["client_id"] == "tmp-1" and created["rev"] == 1
    sid = created["entity_id"]
    longer = {**line, "geometry": {"type": "LineString", "coordinates": [[0, 0], [10, 0], [10, 5]]}}
    ops = [
        {"entity_type": "sketch", "entity_id": sid, "op": "update", "base_rev": 1, "after": longer, "client_id": sid},
    ]
    assert (
        await client.post(f"{BASE}/projects/{project_id}/edits", json={"ops": ops}, headers=header)
    ).status_code == 200
    gone = [{"entity_type": "sketch", "entity_id": sid, "op": "delete", "base_rev": 2, "after": None, "client_id": sid}]
    assert (
        await client.post(f"{BASE}/projects/{project_id}/edits", json={"ops": gone}, headers=header)
    ).status_code == 200
    assert (await client.get(f"{BASE}/projects/{project_id}/sketch", headers=header)).json()["features"] == []

    history = (
        await client.get(f"{BASE}/projects/{project_id}/edits", params={"entity_id": sid}, headers=header)
    ).json()
    rev2 = next(h for h in history["items"] if h["rev"] == 2)
    restored = await client.post(f"{BASE}/edits/{rev2['id']}/restore", json={}, headers=header)
    assert restored.status_code == 200, restored.text
    assert restored.json()["rev"] == 4
    features = (await client.get(f"{BASE}/projects/{project_id}/sketch", headers=header)).json()["features"]
    assert len(features) == 1 and len(features[0]["geometry"]["coordinates"]) == 3 and features[0]["rev"] == 4


async def test_unknown_entity_type_is_refused(client: AsyncClient, header: dict, project_id: str) -> None:
    op = {"entity_type": "spaceship", "op": "create", "after": {"geometry": {"type": "Point", "coordinates": [0, 0]}}}
    r = await client.post(f"{BASE}/projects/{project_id}/edits", json={"ops": [op]}, headers=header)
    assert r.status_code == 422


async def test_viewer_cannot_save(client: AsyncClient, viewer: dict, project_id: str) -> None:
    op = {"entity_type": "sketch", "op": "create", "after": {"geometry": {"type": "Point", "coordinates": [0, 0]}}}
    r = await client.post(f"{BASE}/projects/{project_id}/edits", json={"ops": [op]}, headers=viewer)
    assert r.status_code in (403, 404)


async def test_stranger_cannot_read_edits(client: AsyncClient, stranger: dict, project_id: str) -> None:
    r = await client.get(f"{BASE}/projects/{project_id}/edits", headers=stranger)
    assert r.status_code in (403, 404)
