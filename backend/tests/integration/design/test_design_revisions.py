"""R2: .ddcrev intake, storage, BIM hub registration without a converter, decisions."""

from __future__ import annotations

import asyncio
import io
import uuid

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from .conftest import LINK, make_project, make_user
from .ddcrev import example_rows, package, sha

pytestmark = pytest.mark.asyncio

BASE = "/api/v1/design"
BIM = "/api/v1/bim_hub"
WALL = "b1/s00/wall-ext-N/0"
DOOR = "b1/s01/u2A/door-entry/0"


async def _token(client, headers, project_id) -> dict[str, str]:
    r = await client.post(
        f"{BASE}/link/code", json={"project_id": str(project_id), "action": "new"}, headers={**headers, **LINK}
    )
    x = await client.post(f"{BASE}/link/exchange", json={"code": r.json()["code"]}, headers=LINK)
    assert x.status_code == 200, x.text
    return {"Authorization": f"Bearer {x.json()['token']}", **LINK}


async def _linked_project(client):
    uid, h = await make_user(client)
    pid = await make_project(uid)
    tok = await _token(client, h, pid)
    lock = await client.post(f"{BASE}/projects/{pid}/lock", headers=tok)
    assert lock.status_code == 200, lock.text
    return uid, h, pid, tok


async def _upload(client, pid, tok, data: bytes):
    return await client.post(
        f"{BASE}/projects/{pid}/revisions", headers=tok, files={"package": ("model.ddcrev", data, "application/zip")}
    )


async def _latest_model(model_id: str) -> str:
    from app.database import async_session_factory
    from app.modules.boq.service import BOQService

    async with async_session_factory() as s:
        latest, _ = await BOQService(s)._resolve_latest_model_id(uuid.UUID(model_id))
    return str(latest)


def _rev2_rows() -> list[dict]:
    rows = [r for r in example_rows() if r["element_key"] != DOOR]
    wall = next(r for r in rows if r["element_key"] == WALL)
    wall.update(length_m=36.0, area_m2=88.1, geometry_hash="9f2c4a1e0b7d3c66", bbox_max_x=36.0)
    new = dict(next(r for r in example_rows() if r["element_key"] == DOOR))
    key = "b1/s01/u2A/door-entry/1"
    new.update(
        id=key, stable_id=key, element_key=key, geometry_hash="c3d4e5f60718293b", bbox_min_x=12.0, bbox_max_x=13.01
    )
    rows.append(new)
    return rows


async def test_upload_is_visible_through_the_bim_hub(client):
    uid, h, pid, tok = await _linked_project(client)
    rows = example_rows()
    data, manifest = package(pid, rows)
    r = await _upload(client, pid, tok, data)
    assert r.status_code == 201, r.text
    rev = r.json()
    assert rev["status"] == "shared" and rev["number"] == 1 and rev["parent_revision_id"] is None
    assert rev["revision_id"] == manifest["revision_id"] and rev["package_sha256"] == sha(data)
    mid = rev["bim_model_id"]
    assert mid
    model = (await client.get(f"{BIM}/{mid}", headers=h)).json()
    assert model["status"] == "ready", "the viewer renders only ready models"

    els = await client.get(f"{BIM}/models/{mid}/elements/", headers=h)
    assert els.status_code == 200, els.text
    items = {e["stable_id"]: e for e in els.json()["items"]}
    assert set(items) == {r["element_key"] for r in rows}
    wall = items[WALL]
    assert wall["mesh_ref"] == WALL and wall["geometry_hash"] == "9f2c4a1e0b7d3c55"
    assert wall["quantities"] == {
        "length_m": 34.0,
        "area_m2": 82.5,
        "volume_m3": 30.11,
        "count": 1,
        "area_gross_m2": 102.0,
        "volume_gross_m3": 37.23,
    }
    assert wall["properties"]["fire_rating"] == "REI 90" and wall["properties"]["ifc_class"] == "IfcWall"
    assert wall["element_type"] == "Wall" and wall["storey"] == "EG"

    q = await client.post(
        f"{BIM}/models/{mid}/dataframe/query/",
        headers=h,
        json={"columns": ["id", "area_m2", "fire_rating"], "limit": 100},
    )
    assert q.status_code == 200, q.text
    by_id = {row["id"]: row for row in q.json()}
    assert set(by_id) == set(items)
    assert float(by_id[WALL]["area_m2"]) == 82.5 and by_id[WALL]["fire_rating"] == "REI 90"

    geo = await client.get(f"{BIM}/models/{mid}/geometry/", headers=h)
    assert geo.status_code == 200, geo.text[:200]
    assert geo.content[:4] == b"glTF"

    model = await client.get(f"{BIM}/{mid}", headers=h)
    assert model.status_code == 200, model.text
    assert model.json()["model_format"] == "ddc" and model.json()["parent_model_id"] is None

    f = await client.get(f"{BASE}/revisions/{rev['revision_id']}/files/elements.parquet", headers=tok)
    assert f.status_code == 200 and sha(f.content) == next(
        x["sha256"] for x in manifest["files"] if x["path"] == "elements.parquet"
    )
    for path in ("manifest.json", "other.bin", "../manifest.json"):
        assert (await client.get(f"{BASE}/revisions/{rev['revision_id']}/files/{path}", headers=tok)).status_code == 404

    listed = await client.get(f"{BASE}/projects/{pid}/revisions", headers=tok)
    assert [x["revision_id"] for x in listed.json()] == [rev["revision_id"]]
    one = await client.get(f"{BASE}/revisions/{rev['revision_id']}", headers=h)
    assert one.status_code == 200 and one.json()["manifest"]["files"] == manifest["files"]
    ctx = (await client.get(f"{BASE}/projects/{pid}/context", headers=tok)).json()
    assert ctx["latest_revision"]["number"] == 1


async def test_versions_diff_and_decisions(client):
    uid, h, pid, tok = await _linked_project(client)
    rows1 = example_rows()
    d1, m1 = package(pid, rows1)
    rev1 = (await _upload(client, pid, tok, d1)).json()
    # The editor publishes; only an ERP session of a manager decides.
    by_editor = await client.post(f"{BASE}/revisions/{rev1['revision_id']}/accept", headers=tok)
    assert by_editor.status_code == 403
    acc = await client.post(f"{BASE}/revisions/{rev1['revision_id']}/accept", headers=h, json={"comment": "ok"})
    assert acc.status_code == 200, acc.text
    assert acc.json()["status"] == "published" and acc.json()["decision_comment"] == "ok"

    rows2 = _rev2_rows()
    d2, m2 = package(pid, rows2, parent_id=m1["revision_id"], parent_rows=rows1)
    r2 = await _upload(client, pid, tok, d2)
    assert r2.status_code == 201, r2.text
    rev2 = r2.json()
    assert rev2["number"] == 2 and rev2["parent_revision_id"] == m1["revision_id"]
    model1, model2 = rev1["bim_model_id"], rev2["bim_model_id"]
    # Pending revisions are not chained: the BOQ still follows R1.
    assert await _latest_model(model1) == model1

    diff = await client.post(f"{BIM}/models/{model2}/diff/{model1}", headers=h)
    assert diff.status_code == 201, diff.text
    details = diff.json()["diff_details"]
    assert [m["stable_id"] for m in details["modified"]] == [WALL]
    assert [a["stable_id"] for a in details["added"]] == ["b1/s01/u2A/door-entry/1"]
    assert [d["stable_id"] for d in details["deleted"]] == [DOOR]
    assert diff.json()["diff_summary"]["unchanged"] == 2

    model = (await client.get(f"{BIM}/{model2}", headers=h)).json()
    assert model["metadata"]["design_status"] == "shared" and model["parent_model_id"] is None
    acc2 = await client.post(f"{BASE}/revisions/{rev2['revision_id']}/accept", headers=h)
    assert acc2.status_code == 200 and acc2.json()["status"] == "published"
    assert (await client.get(f"{BASE}/revisions/{rev1['revision_id']}", headers=tok)).json()["status"] == "archived"
    assert await _latest_model(model1) == model2
    model = (await client.get(f"{BIM}/{model2}", headers=h)).json()
    assert model["parent_model_id"] == model1 and model["metadata"]["design_status"] == "published"
    assert (await client.get(f"{BIM}/{model1}", headers=h)).json()["metadata"]["design_status"] == "archived"

    # R3 on top of R2, rejected: never becomes the latest model.
    d3, m3 = package(pid, rows1, parent_id=m2["revision_id"], parent_rows=rows2)
    rev3 = (await _upload(client, pid, tok, d3)).json()
    assert rev3["number"] == 3
    no_comment = await client.post(f"{BASE}/revisions/{rev3['revision_id']}/reject", headers=h, json={})
    assert no_comment.status_code == 422
    rej = await client.post(
        f"{BASE}/revisions/{rev3['revision_id']}/reject", headers=h, json={"comment": "keep the two flats"}
    )
    assert rej.status_code == 200 and rej.json()["status"] == "rejected"
    assert await _latest_model(model1) == model2 and await _latest_model(model2) == model2
    rejected_model = (await client.get(f"{BIM}/{rev3['bim_model_id']}", headers=h)).json()
    assert rejected_model["metadata"]["design_status"] == "rejected" and rejected_model["parent_model_id"] is None
    again = await client.post(f"{BASE}/revisions/{rev3['revision_id']}/accept", headers=h)
    assert again.status_code == 409

    # Parent must be the latest published revision.
    stale, _ = package(pid, rows1, parent_id=m1["revision_id"], parent_rows=rows1)
    assert (await _upload(client, pid, tok, stale)).status_code == 409
    first_again, _ = package(pid, rows1)
    assert (await _upload(client, pid, tok, first_again)).status_code == 409
    # The same revision cannot be uploaded twice.
    assert (await _upload(client, pid, tok, d2)).status_code == 409

    # A second child of R2 while the first still waits is refused (chain tip rule); a child of the waiting one is fine.
    d4, _ = package(pid, rows1, parent_id=m2["revision_id"], parent_rows=rows2)
    rev4 = (await _upload(client, pid, tok, d4)).json()
    sibling, _ = package(pid, rows2, parent_id=m2["revision_id"], parent_rows=rows2)
    assert (await _upload(client, pid, tok, sibling)).status_code == 409
    d5, _ = package(pid, rows2, parent_id=rev4["revision_id"], parent_rows=rows1)
    rev5 = (await _upload(client, pid, tok, d5)).json()
    # Accepting the same revision twice at once: exactly one wins.
    a4, a4b = await asyncio.gather(
        client.post(f"{BASE}/revisions/{rev4['revision_id']}/accept", headers=h),
        client.post(f"{BASE}/revisions/{rev4['revision_id']}/accept", headers=h),
    )
    assert sorted([a4.status_code, a4b.status_code]) == [200, 409], (a4.text, a4b.text)
    assert await _latest_model(model1) == rev4["bim_model_id"]
    # Reject and accept racing on the same pending revision: exactly one of them wins.
    rj, ac = await asyncio.gather(
        client.post(f"{BASE}/revisions/{rev5['revision_id']}/reject", headers=h, json={"comment": "late"}),
        client.post(f"{BASE}/revisions/{rev5['revision_id']}/accept", headers=h),
    )
    assert sorted([rj.status_code, ac.status_code]) == [200, 409], (rj.text, ac.text)

    listed = (await client.get(f"{BASE}/projects/{pid}/revisions", headers=tok)).json()
    assert sorted(x["status"] for x in listed) in (
        ["archived", "archived", "archived", "published", "rejected"],
        ["archived", "archived", "published", "rejected", "rejected"],
    )
    assert sum(x["status"] == "published" for x in listed) == 1


def _bad_parquet() -> bytes:
    rows = example_rows()
    table = pa.Table.from_pylist([{**r, "colour": "red"} for r in rows])
    buf = io.BytesIO()
    pq.write_table(table, buf)
    return buf.getvalue()


def _set_sha(path, value):
    def edit(m):
        next(f for f in m["files"] if f["path"] == path)["sha256"] = value

    return edit


def _add_entry(m):
    m["files"].append({"path": "sheets/EG.pdf", "role": "sheet", "sha256": "0" * 64, "bytes": 10})


@pytest.mark.parametrize(
    "case",
    [
        "bad hash",
        "path escape",
        "unlisted member",
        "missing member",
        "unknown column",
        "schema",
        "other project",
        "sheet path",
        "node without row",
        "not a zip",
    ],
)
async def test_bad_packages_are_rejected_whole(client, case):
    uid, h, pid, tok = await _linked_project(client)
    rows = example_rows()
    if case == "bad hash":
        data, _ = package(pid, rows, manifest_edit=_set_sha("model.ddc", "a" * 64))
    elif case == "path escape":
        data, _ = package(pid, rows, extra_members={"../evil.txt": b"x"})
    elif case == "unlisted member":
        data, _ = package(pid, rows, extra_members={"notes.txt": b"x"})
    elif case == "missing member":
        data, _ = package(pid, rows, manifest_edit=_add_entry)
    elif case == "unknown column":
        data, _ = package(pid, rows, files={"elements.parquet": _bad_parquet()})
    elif case == "schema":
        data, _ = package(pid, rows, manifest_edit=lambda m: m["units"].update(length="mm"))
    elif case == "other project":
        data, _ = package(uuid.uuid4(), rows)
    elif case == "sheet path":
        data, _ = package(
            pid,
            rows,
            files={"x.pdf": b"x"},
            manifest_edit=lambda m: next(f for f in m["files"] if f["path"] == "x.pdf").update(role="sheet"),
        )
    elif case == "node without row":
        from .ddcrev import glb

        data, _ = package(pid, rows[:2], files={"geometry.glb": glb(rows)})
    else:
        data = b"not a zip at all"
    r = await _upload(client, pid, tok, data)
    assert r.status_code == 422, (case, r.status_code, r.text)
    assert (await client.get(f"{BASE}/projects/{pid}/revisions", headers=tok)).json() == []
    models = await client.get(f"{BIM}/", headers=h, params={"project_id": str(pid)})
    assert models.status_code == 200 and models.json()["items"] == [], models.text


async def test_first_revision_cannot_name_a_parent(client):
    uid, h, pid, tok = await _linked_project(client)
    data, _ = package(pid, example_rows(), parent_id=str(uuid.uuid4()), parent_rows=[])
    assert (await _upload(client, pid, tok, data)).status_code == 409


async def test_upload_needs_the_lock_and_the_right_project(client):
    owner, h_owner = await make_user(client)
    other, h_other = await make_user(client, role="admin")
    pid = await make_project(owner)
    p2 = await make_project(owner, name="Other")
    tok = await _token(client, h_owner, pid)
    data, _ = package(pid, example_rows())
    no_lock = await _upload(client, pid, tok, data)
    assert no_lock.status_code == 409, no_lock.text
    assert (await client.post(f"{BASE}/projects/{pid}/lock", headers=tok)).status_code == 200
    # An admin with access to the project is still blocked by the owner's lock.
    blocked = await _upload(client, pid, {**h_other, **LINK}, data)
    assert blocked.status_code == 409
    # A token for one project cannot reach another one.
    foreign, _ = package(p2, example_rows())
    assert (await _upload(client, p2, tok, foreign)).status_code == 404
    assert (await _upload(client, pid, tok, data)).status_code == 201
    other_tok = await _token(client, h_owner, p2)
    revs = (await client.get(f"{BASE}/projects/{pid}/revisions", headers=tok)).json()
    assert (await client.get(f"{BASE}/revisions/{revs[0]['revision_id']}", headers=other_tok)).status_code == 404


async def test_size_limits(client, monkeypatch):
    from app.modules.design.settings import get_design_settings

    uid, h, pid, tok = await _linked_project(client)
    rows = example_rows()
    try:
        monkeypatch.setenv("OE_DESIGN_REVISION_MAX_BYTES", "1000")
        get_design_settings.cache_clear()
        data, _ = package(pid, rows)
        assert (await _upload(client, pid, tok, data)).status_code == 413
        monkeypatch.delenv("OE_DESIGN_REVISION_MAX_BYTES")
        monkeypatch.setenv("OE_DESIGN_REVISION_MAX_UNPACKED_BYTES", str(2_000_000))
        get_design_settings.cache_clear()
        bomb, _ = package(pid, rows, files={"thumb.png": b"\0" * 3_000_000})
        assert len(bomb) < 100_000
        assert (await _upload(client, pid, tok, bomb)).status_code == 413
    finally:
        monkeypatch.delenv("OE_DESIGN_REVISION_MAX_BYTES", raising=False)
        monkeypatch.delenv("OE_DESIGN_REVISION_MAX_UNPACKED_BYTES", raising=False)
        get_design_settings.cache_clear()
    assert (await _upload(client, pid, tok, data)).status_code == 201
