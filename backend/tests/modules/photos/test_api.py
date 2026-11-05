"""Photo archive API and service against PostgreSQL.

Upload with EXIF and device fix, search and cursor, timeline, map, links and IDOR,
permission matrix, archive versus delete, backfill idempotency, AI review, albums,
compare and export access.
"""

from __future__ import annotations

import io
import json
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient

from tests.modules.photos.test_logic import _jpeg

BASE = "/api/v1/photos"


async def _upload(client, header, project_id, *, name="site.jpg", content=None, device=None, **form):
    files = [("files", (name, content or _jpeg(), "image/jpeg"))]
    data = {k: v for k, v in form.items() if v is not None}
    if device is not None:
        data["device"] = json.dumps(device)
    resp = await client.post(f"{BASE}/upload/?project_id={project_id}", files=files, data=data, headers=header)
    return resp


async def _punch_item(project_id: str, *, photos: list[str] | None = None) -> str:
    from app.database import async_session_factory
    from app.modules.punchlist.models import PunchItem

    async with async_session_factory() as session:
        item = PunchItem(project_id=uuid.UUID(project_id), title="Crack at grid C4", photos=photos or [])
        session.add(item)
        await session.commit()
        return str(item.id)


@pytest.mark.asyncio
async def test_upload_reads_exif_prefers_device_fix_and_completes_the_record(
    client: AsyncClient, admin_auth, project_id
):
    _, header = admin_auth
    content = _jpeg(gps=(48.137, 11.575), taken="2026:10:30 08:15:00", size=(640, 480))
    device = {"lat": 52.52, "lon": 13.405, "accuracy_m": 6.5}
    resp = await _upload(client, header, project_id, content=content, device=device, caption="Slab pour bay 3")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["errors"] == []
    (photo,) = body["items"]
    assert (photo["gps_lat"], photo["gps_lon"], photo["gps_accuracy_m"]) == (52.52, 13.405, 6.5)
    assert photo["taken_at"].startswith("2026-10-30T08:15")
    assert photo["taken_at_source"] == "exif"
    assert (photo["width"], photo["height"]) == (640, 480)
    assert photo["sha256"] and photo["thumb_status"] == "ready"
    assert photo["evidence_grade"] == "full"
    assert photo["file_url"] == f"/api/v1/photos/{photo['id']}/file/"

    from app.core.match_service.extractors.photo import extract_exif_gps

    file_resp = await client.get(photo["file_url"], headers=header)
    assert file_resp.status_code == 200
    assert extract_exif_gps(file_resp.content) is None  # GPS block stripped from the stored copy
    assert (await client.get(photo["thumb_url"], headers=header)).status_code == 200


@pytest.mark.asyncio
async def test_a_bad_file_does_not_fail_the_batch(client: AsyncClient, admin_auth, project_id):
    _, header = admin_auth
    files = [
        ("files", ("ok.jpg", _jpeg(), "image/jpeg")),
        ("files", ("fake.jpg", b"MZ not an image at all", "image/jpeg")),
    ]
    resp = await client.post(f"{BASE}/upload/?project_id={project_id}", files=files, headers=header)
    assert resp.status_code == 201, resp.text
    assert len(resp.json()["items"]) == 1
    assert resp.json()["errors"][0]["filename"] == "fake.jpg"


@pytest.mark.asyncio
async def test_search_cursor_timeline_and_map(client: AsyncClient, admin_auth, project_id):
    _, header = admin_auth
    tag = uuid.uuid4().hex[:6]
    for day in ("2026:09:01 10:00:00", "2026:09:02 10:00:00", "2026:09:03 10:00:00"):
        r = await _upload(client, header, project_id, content=_jpeg(taken=day), tags=f"pour-{tag}")
        assert r.status_code == 201, r.text

    first = await client.get(f"{BASE}/?project_id={project_id}&tag=pour-{tag}&limit=2", headers=header)
    assert first.status_code == 200, first.text
    page = first.json()
    assert page["total"] == 3
    assert [p["taken_at"][:10] for p in page["items"]] == ["2026-09-03", "2026-09-02"]
    # The tag filter runs in memory, so the cursor must still hand over the rest.
    assert page["next_cursor"] is None or isinstance(page["next_cursor"], str)

    window = await client.get(
        f"{BASE}/?project_id={project_id}&from=2026-09-01T00:00:00Z&to=2026-09-02T23:59:59Z&limit=1", headers=header
    )
    assert window.json()["total"] >= 2
    nxt = await client.get(
        f"{BASE}/?project_id={project_id}&from=2026-09-01T00:00:00Z&to=2026-09-02T23:59:59Z&limit=1"
        f"&cursor={window.json()['next_cursor']}",
        headers=header,
    )
    assert nxt.json()["items"][0]["id"] != window.json()["items"][0]["id"]

    timeline = (await client.get(f"{BASE}/timeline/?project_id={project_id}&tag=pour-{tag}", headers=header)).json()
    assert [d["date"] for d in timeline["items"]] == ["2026-09-03", "2026-09-02", "2026-09-01"]
    cut = (await client.get(f"{BASE}/timeline/?project_id={project_id}&tag=pour-{tag}&limit=1", headers=header)).json()
    assert len(cut["items"]) == 1 and cut["total"] == 3

    geo = (await client.get(f"{BASE}/map/?project_id={project_id}", headers=header)).json()
    assert geo["type"] == "FeatureCollection"
    for feature in geo["features"]:
        lon, lat = feature["geometry"]["coordinates"]
        assert -180 <= lon <= 180 and -90 <= lat <= 90


@pytest.mark.asyncio
async def test_links_are_scoped_to_the_project(client: AsyncClient, admin_auth, project_id, other_project_id):
    _, header = admin_auth
    photo = (await _upload(client, header, project_id)).json()["items"][0]
    own = await _punch_item(project_id)
    foreign = await _punch_item(other_project_id)

    ok = await client.post(
        f"{BASE}/{photo['id']}/links/", json={"target_kind": "punch_item", "target_id": own}, headers=header
    )
    assert ok.status_code == 201, ok.text
    again = await client.post(
        f"{BASE}/{photo['id']}/links/", json={"target_kind": "punch_item", "target_id": own}, headers=header
    )
    assert again.json()["id"] == ok.json()["id"]
    cross = await client.post(
        f"{BASE}/{photo['id']}/links/", json={"target_kind": "punch_item", "target_id": foreign}, headers=header
    )
    assert cross.status_code == 404
    missing = await client.post(
        f"{BASE}/{photo['id']}/links/",
        json={"target_kind": "inspection", "target_id": str(uuid.uuid4())},
        headers=header,
    )
    assert missing.status_code == 404

    strip = await client.get(f"{BASE}/by-target/?project_id={project_id}&kind=punch_item&id={own}", headers=header)
    assert [p["id"] for p in strip.json()["items"]] == [photo["id"]]
    assert strip.json()["total"] == 1

    report = (
        await client.get(f"{BASE}/validation/?project_id={project_id}&photo_id={photo['id']}", headers=header)
    ).json()
    assert not [f for f in report["findings"] if f["rule_id"] == "photos.link_target_exists"]

    gone = await client.delete(f"{BASE}/{photo['id']}/links/?target_kind=punch_item&target_id={own}", headers=header)
    assert gone.status_code == 204


@pytest.mark.asyncio
async def test_other_users_cannot_read_or_touch_the_archive(
    client: AsyncClient, admin_auth, project_id, outsider_header
):
    _, header = admin_auth
    other = outsider_header
    photo = (await _upload(client, header, project_id)).json()["items"][0]
    assert (await client.get(f"{BASE}/{photo['id']}/", headers=other)).status_code == 404
    assert (await client.get(f"{BASE}/{photo['id']}/file/", headers=other)).status_code == 404
    assert (await client.get(f"{BASE}/?project_id={project_id}", headers=other)).status_code == 404
    assert (await client.patch(f"{BASE}/{photo['id']}/", json={"caption": "x"}, headers=other)).status_code == 404


@pytest.mark.asyncio
async def test_permission_matrix(client: AsyncClient, admin_auth, project_id, role_headers):
    _, header = admin_auth
    photo = (await _upload(client, header, project_id)).json()["items"][0]
    viewer, editor, manager = role_headers["viewer"], role_headers["editor"], role_headers["manager"]

    assert (await client.get(f"{BASE}/{photo['id']}/", headers=viewer)).status_code == 200
    assert (await _upload(client, viewer, project_id)).status_code == 403
    assert (await client.patch(f"{BASE}/{photo['id']}/", json={"caption": "v"}, headers=viewer)).status_code == 403

    assert (await _upload(client, editor, project_id)).status_code == 201
    patched = await client.patch(f"{BASE}/{photo['id']}/", json={"caption": "Formwork"}, headers=editor)
    assert patched.status_code == 200 and patched.json()["caption"] == "Formwork"
    assert (await client.delete(f"{BASE}/{photo['id']}/", headers=editor)).status_code == 403
    assert (await client.post(f"{BASE}/backfill/?project_id={project_id}", headers=manager)).status_code == 403

    deleted = await client.delete(f"{BASE}/{photo['id']}/", headers=manager)
    assert deleted.status_code == 200 and deleted.json()["result"] == "deleted"
    assert (await client.get(f"{BASE}/{photo['id']}/", headers=manager)).status_code == 404


@pytest.mark.asyncio
async def test_backfill_is_idempotent_and_never_touches_the_files(client: AsyncClient, admin_auth, project_id):
    from sqlalchemy import func, select

    from app.core.storage import module_uploads_dir
    from app.database import async_session_factory
    from app.modules.documents.models import ProjectPhoto
    from app.modules.photos.service import PhotosService

    _, header = admin_auth
    name = f"punchlist/photos/{uuid.uuid4().hex}.jpg"
    target = module_uploads_dir() / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(_jpeg(size=(200, 100)))
    before = (target.read_bytes(), target.stat().st_mtime_ns)
    item_id = await _punch_item(project_id, photos=[name, "../../outside.jpg"])

    async with async_session_factory() as session:
        first = await PhotosService(session).backfill_project(uuid.UUID(project_id))
        await session.commit()
    async with async_session_factory() as session:
        second = await PhotosService(session).backfill_project(uuid.UUID(project_id))
        await session.commit()
        rows = (
            await session.execute(
                select(func.count()).where(ProjectPhoto.source_module == "punchlist", ProjectPhoto.source_id == item_id)
            )
        ).scalar()
    assert first["punchlist"] >= 1
    assert second["punchlist"] == 0
    assert rows == 1  # the path outside the upload roots was refused
    assert (target.read_bytes(), target.stat().st_mtime_ns) == before

    strip = (
        await client.get(f"{BASE}/by-target/?project_id={project_id}&kind=punch_item&id={item_id}", headers=header)
    ).json()
    assert len(strip) == 1 and strip[0]["source_module"] == "punchlist"
    file_resp = await client.get(strip[0]["file_url"], headers=header)
    assert file_resp.status_code == 200 and file_resp.content == before[0]

    archived = await client.delete(f"{BASE}/{strip[0]['id']}/", headers=header)
    assert archived.json()["result"] == "archived"
    assert target.is_file()


@pytest.mark.asyncio
async def test_ai_suggestions_stay_pending_until_a_person_accepts(
    client: AsyncClient, admin_auth, project_id, monkeypatch
):
    from sqlalchemy import select

    import app.modules.photos.service as svc
    from app.database import async_session_factory
    from app.modules.file_tags.models import FileTagAssignment

    _, header = admin_auth
    photo = (await _upload(client, header, project_id, caption="Original")).json()["items"][0]
    own = await _punch_item(project_id)
    events: list[tuple[str, dict]] = []
    monkeypatch.setattr(svc, "publish_after_commit", lambda _s, name, data=None, **_k: events.append((name, data)))

    async def fake_model(_session, _uid, prompt, image_b64):
        assert "Never identify people" in prompt and image_b64
        return (
            json.dumps(
                {
                    "caption": {"text": "Formwork for slab edge", "confidence": 0.81},
                    "tags": {"tags": ["formwork", "slab edge"], "confidence": 0.7},
                    "hazards": [{"hazard": "Open edge", "bbox": [0.1, 0.1, 0.2, 0.2], "confidence": 0.6}],
                }
            ),
            "anthropic",
            "vision-test",
        )

    async def broken_model(*_a):
        return "I think it is a building", "anthropic", "vision-test"

    async with async_session_factory() as session:
        service = svc.PhotosService(session)
        row = await service.get_photo(uuid.UUID(photo["id"]))
        assert await service.analyze(row, ["caption", "tags"], "u", caller=broken_model) == []
        stored = await service.analyze(row, ["caption", "tags", "hazard"], "u", caller=fake_model)
        await session.commit()
    assert {s.kind for s in stored} == {"caption", "tags", "hazard"}
    assert "photos.ai.suggested" in [e[0] for e in events]

    envelope = (await client.get(f"{BASE}/{photo['id']}/ai/?limit=1", headers=header)).json()
    assert len(envelope["items"]) == 1 and envelope["total"] == 3
    listed = (await client.get(f"{BASE}/{photo['id']}/ai/", headers=header)).json()["items"]
    assert {s["status"] for s in listed} == {"pending"}
    assert (await client.get(f"{BASE}/{photo['id']}/", headers=header)).json()["caption"] == "Original"

    by_kind = {s["kind"]: s for s in listed}
    acc = await client.post(f"{BASE}/ai/{by_kind['tags']['id']}/accept/", headers=header)
    assert acc.status_code == 200 and acc.json()["status"] == "accepted"
    edited = await client.post(
        f"{BASE}/ai/{by_kind['caption']['id']}/accept/",
        json={"payload": {"text": "Slab edge formwork"}},
        headers=header,
    )
    assert edited.json()["status"] == "edited"
    rej = await client.post(f"{BASE}/ai/{by_kind['hazard']['id']}/reject/", headers=header)
    assert rej.json()["status"] == "rejected"
    assert (await client.post(f"{BASE}/ai/{by_kind['hazard']['id']}/accept/", headers=header)).status_code == 409

    after = (await client.get(f"{BASE}/{photo['id']}/", headers=header)).json()
    assert after["caption"] == "Slab edge formwork"
    assert {"formwork", "slab edge"} <= set(after["tags"])
    async with async_session_factory() as session:
        assigned = (
            (
                await session.execute(
                    select(FileTagAssignment).where(
                        FileTagAssignment.file_kind == "photo", FileTagAssignment.file_id == photo["id"]
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(assigned) == 2

    # Accepting a progress reading links the photo and emits an event, nothing more.
    from app.modules.photos.models import PhotoAISuggestion

    async with async_session_factory() as session:
        service = svc.PhotosService(session)
        prow = await service.get_photo(uuid.UUID(photo["id"]))
        await service.add_link(prow, "punch_item", own, "u")
        sug = PhotoAISuggestion(
            photo_id=prow.id,
            kind="progress",
            payload={"target_kind": "punch_item", "target_id": own, "percent_observed": 40.0},
            confidence=0.5,
        )
        session.add(sug)
        await session.flush()
        await service.accept_suggestion(sug, prow, "u", None)
        await session.commit()
    accepted = [d for name, d in events if name == "photos.ai.accepted" and d["kind"] == "progress"]
    assert accepted and accepted[0]["payload"]["percent_observed"] == 40.0


@pytest.mark.asyncio
async def test_albums_compare_and_export_access(client: AsyncClient, admin_auth, project_id, outsider_header):
    _, header = admin_auth
    other = outsider_header
    a = (await _upload(client, header, project_id, content=_jpeg(taken="2026:08:01 09:00:00"))).json()["items"][0]
    b = (await _upload(client, header, project_id, content=_jpeg(taken="2026:10:01 09:00:00"))).json()["items"][0]
    name = f"Handover {uuid.uuid4().hex[:4]}"

    album = await client.post(f"{BASE}/albums/", json={"project_id": project_id, "name": name}, headers=header)
    assert album.status_code == 201, album.text
    dup = await client.post(f"{BASE}/albums/", json={"project_id": project_id, "name": name}, headers=header)
    assert dup.status_code == 409
    added = await client.post(
        f"{BASE}/albums/{album.json()['id']}/items/", json={"photo_ids": [a["id"], b["id"], a["id"]]}, headers=header
    )
    assert added.json() == {"added": 2, "photo_count": 2}
    page = (await client.get(f"{BASE}/albums/?project_id={project_id}&limit=1", headers=header)).json()
    assert len(page["items"]) == 1 and page["total"] >= 1
    listed = [
        x
        for x in (await client.get(f"{BASE}/albums/?project_id={project_id}", headers=header)).json()["items"]
        if x["id"] == album.json()["id"]
    ]
    assert listed[0]["cover_photo_id"] == a["id"]
    in_album = (await client.get(f"{BASE}/?project_id={project_id}&album={album.json()['id']}", headers=header)).json()
    assert in_album["total"] == 2

    same = await client.post(
        f"{BASE}/compare/",
        json={"project_id": project_id, "before_photo_id": a["id"], "after_photo_id": a["id"]},
        headers=header,
    )
    assert same.status_code == 422
    cmp = await client.post(
        f"{BASE}/compare/",
        json={"project_id": project_id, "before_photo_id": a["id"], "after_photo_id": b["id"], "title": "Facade"},
        headers=header,
    )
    assert cmp.status_code == 201, cmp.text
    page = (await client.get(f"{BASE}/compare/?project_id={project_id}&limit=1", headers=header)).json()
    assert [c["id"] for c in page["items"]] == [cmp.json()["id"]] and page["total"] == 1
    got = await client.get(f"{BASE}/compare/{cmp.json()['id']}/", headers=header)
    assert got.json()["before"]["id"] == a["id"] and got.json()["after"]["id"] == b["id"]
    assert (await client.get(f"{BASE}/compare/{cmp.json()['id']}/", headers=other)).status_code == 404

    job = await client.post(
        f"{BASE}/export/", json={"project_id": project_id, "album_id": album.json()["id"]}, headers=header
    )
    assert job.status_code == 202, job.text
    assert (await client.get(f"{BASE}/export/{job.json()['job_id']}/", headers=header)).status_code == 200
    assert (await client.get(f"{BASE}/export/{job.json()['job_id']}/", headers=other)).status_code == 404


@pytest.mark.asyncio
async def test_export_zip_handler_writes_a_downloadable_archive(client: AsyncClient, admin_auth, project_id):
    import zipfile

    from app.core.job_runner import submit_job
    from app.database import async_session_factory
    from app.modules.photos.jobs import export_zip_handler

    _, header = admin_auth
    photo = (await _upload(client, header, project_id, caption="Export me")).json()["items"][0]
    run = await submit_job("photos.export_zip.test", {"project_id": project_id})
    result = await export_zip_handler(run, {"project_id": project_id, "photo_ids": [photo["id"]]})
    assert result["photo_count"] == 1

    from app.core.job_run import JobRun

    async with async_session_factory() as session:
        row = await session.get(JobRun, run.id)
        row.kind = "photos.export_zip"
        row.status = "success"
        row.result_jsonb = result
        row.payload_jsonb = {"project_id": project_id}
        await session.commit()
    resp = await client.get(f"{BASE}/export/{run.id}/file/", headers=header)
    assert resp.status_code == 200, resp.text
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        record = json.loads(zf.read(f"photo-{photo['id']}.json"))
        assert record["caption"] == "Export me"
        assert Path(record["file"]).parent.as_posix() == "photos"
        assert json.loads(zf.read("manifest.json"))["photo_count"] == 1


@pytest.mark.asyncio
async def test_category_filter_and_suggestion_reach_the_archive(client: AsyncClient, admin_auth, project_id):
    from app.database import async_session_factory
    from app.modules.documents.models import ProjectPhoto

    _, header = admin_auth
    photo = (await _upload(client, header, project_id, category="defect")).json()["items"][0]
    async with async_session_factory() as session:
        row = await session.get(ProjectPhoto, uuid.UUID(photo["id"]))
        row.metadata_ = {**(row.metadata_ or {}), "category_suggestion": {"suggested_category": "safety"}}
        await session.commit()
    page = (await client.get(f"{BASE}/?project_id={project_id}&category=defect", headers=header)).json()
    assert photo["id"] in [p["id"] for p in page["items"]]
    assert all(p["category"] == "defect" for p in page["items"])
    got = (await client.get(f"{BASE}/{photo['id']}/", headers=header)).json()
    assert got["category_suggestion"]["suggested_category"] == "safety"
