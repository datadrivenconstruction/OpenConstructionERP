# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Drawing revision compare - API contract end to end.

1. A PDF compare computed in the browser is stored against two takeoff
   documents of the project; regions off the sheet, a self-compare and a
   foreign revision are refused.
2. Triage (status, comment) and the validation rule set.
3. Re-measure: the dry run lists the measurement inside the region (drawn on
   the new sheet, and one drawn on the old sheet that the alignment maps into
   it) and its BOQ position; the real run flags both; clearing lifts the flags.
4. RFI and markup raised from a change link back to it.
5. The change report PDF.
6. DWG: two parsed versions diffed entity by entity on the server.
7. Another tenant can neither read nor change any of it; a viewer cannot write.
"""

from __future__ import annotations

import json
import os
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

_BASE = "/api/v1/drawing-compare"


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        from app.database import Base, engine
        from app.modules.drawing_compare import models as _dc  # noqa: F401
        from app.modules.projects import models as _proj  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://test") as ac:
        yield ac


async def _set_role(email: str, role: str) -> None:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(role=role, is_active=True))
        await s.commit()


async def _user(client: AsyncClient, tag: str, role: str) -> tuple[str, dict[str, str]]:
    email = f"{tag}-{uuid.uuid4().hex[:8]}@dwgcmp.io"
    password = f"Cmp{uuid.uuid4().hex[:6]}9"
    reg = await client.post(
        "/api/v1/users/auth/register", json={"email": email, "password": password, "full_name": f"User {tag}"}
    )
    assert reg.status_code in (200, 201), reg.text
    await _set_role(email, role)
    login = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return reg.json()["id"], {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _seed_project(owner_id: str) -> dict[str, str]:
    """A project with two takeoff revisions, a measurement on each and a BOQ position."""
    from app.database import async_session_factory
    from app.modules.boq.models import BOQ, Position
    from app.modules.projects.models import Project
    from app.modules.takeoff.models import TakeoffDocument, TakeoffMeasurement

    async with async_session_factory() as s:
        project = Project(id=uuid.uuid4(), name="Tower", description="", owner_id=uuid.UUID(owner_id))
        s.add(project)
        await s.flush()
        docs = []
        for name in ("A-101 rev B.pdf", "A-101 rev C.pdf"):
            d = TakeoffDocument(
                filename=name,
                pages=1,
                size_bytes=10,
                content_type="application/pdf",
                status="ready",
                project_id=project.id,
                owner_id=uuid.UUID(owner_id),
            )
            s.add(d)
            docs.append(d)
        boq = BOQ(project_id=project.id, name="Main")
        s.add(boq)
        await s.flush()
        pos = Position(boq_id=boq.id, ordinal="01.001", description="Partition wall", unit="m2", quantity="12")
        far_pos = Position(boq_id=boq.id, ordinal="01.002", description="Facade", unit="m2", quantity="40")
        s.add_all([pos, far_pos])
        await s.flush()
        # On the new sheet, inside the changed region at (100..200, 100..150).
        m_new = TakeoffMeasurement(
            project_id=project.id,
            document_id=str(docs[1].id),
            page=1,
            type="distance",
            points=[{"x": 120, "y": 120}, {"x": 180, "y": 120}],
            linked_boq_position_id=str(pos.id),
        )
        # On the old sheet, which the alignment shifts by (+50, +50): lands inside.
        m_old = TakeoffMeasurement(
            project_id=project.id,
            document_id=str(docs[0].id),
            page=1,
            type="area",
            points=[{"x": 60, "y": 60}, {"x": 90, "y": 60}, {"x": 90, "y": 80}],
        )
        # Far away on the new sheet: untouched.
        m_far = TakeoffMeasurement(
            project_id=project.id,
            document_id=str(docs[1].id),
            page=1,
            type="distance",
            points=[{"x": 700, "y": 500}, {"x": 800, "y": 500}],
            linked_boq_position_id=str(far_pos.id),
        )
        s.add_all([m_new, m_old, m_far])
        await s.commit()
        return {
            "project_id": str(project.id),
            "old_doc": str(docs[0].id),
            "new_doc": str(docs[1].id),
            "m_new": str(m_new.id),
            "m_old": str(m_old.id),
            "m_far": str(m_far.id),
            "pos": str(pos.id),
            "far_pos": str(far_pos.id),
        }


@pytest_asyncio.fixture(scope="module")
async def world(http_client):
    a_uid, a_hdr = await _user(http_client, "a", "manager")
    b_uid, b_hdr = await _user(http_client, "b", "manager")
    _v_uid, v_hdr = await _user(http_client, "v", "viewer")
    a = await _seed_project(a_uid)
    b = await _seed_project(b_uid)
    return {"a": {**a, "headers": a_hdr}, "b": {**b, "headers": b_hdr}, "viewer": v_hdr}


def _pdf_payload(a: dict, **kw: object) -> dict:
    body = {
        "project_id": a["project_id"],
        "old_ref_id": a["old_doc"],
        "new_ref_id": a["new_doc"],
        "old_page": 1,
        "new_page": 1,
        "page_width": 1000,
        "page_height": 700,
        "alignment": {"method": "auto", "matrix": [1, 0, 0, 1, 50, 50], "confidence": 0.93},
        "settings": {"tolerance": 2, "dpi": 96},
        "changes": [
            {"kind": "modified", "x": 100, "y": 100, "w": 100, "h": 50, "score": 820, "thumbnail": None},
            {"kind": "text", "x": 850, "y": 640, "w": 60, "h": 12, "old_text": "REV B", "new_text": "REV C"},
        ],
    }
    body.update(kw)
    return body


async def _create(http_client, a: dict) -> dict:
    r = await http_client.post(f"{_BASE}/comparisons/", json=_pdf_payload(a), headers=a["headers"])
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.asyncio
async def test_pdf_compare_is_stored_with_both_revisions(http_client, world):
    a = world["a"]
    cmp = await _create(http_client, a)
    assert cmp["source_kind"] == "pdf"
    assert cmp["old_label"] == "A-101 rev B.pdf" and cmp["new_label"] == "A-101 rev C.pdf"
    assert cmp["summary"] == {"added": 0, "removed": 0, "modified": 1, "text": 1, "total": 2}
    assert [c["seq"] for c in cmp["changes"]] == [1, 2]
    assert cmp["changes"][1]["old_text"] == "REV B"
    assert all(c["status"] == "open" for c in cmp["changes"])

    listed = await http_client.get(
        f"{_BASE}/comparisons/", params={"project_id": a["project_id"], "ref_id": a["new_doc"]}, headers=a["headers"]
    )
    assert listed.status_code == 200
    assert cmp["id"] in [row["id"] for row in listed.json()["items"]]


@pytest.mark.asyncio
async def test_pdf_compare_refusals(http_client, world):
    a, b = world["a"], world["b"]
    same = await http_client.post(
        f"{_BASE}/comparisons/", json=_pdf_payload(a, new_ref_id=a["old_doc"]), headers=a["headers"]
    )
    assert same.status_code == 422
    off = _pdf_payload(a, changes=[{"kind": "added", "x": 5000, "y": 5000, "w": 10, "h": 10}])
    assert (await http_client.post(f"{_BASE}/comparisons/", json=off, headers=a["headers"])).status_code == 422
    foreign = _pdf_payload(a, new_ref_id=b["new_doc"])
    assert (await http_client.post(f"{_BASE}/comparisons/", json=foreign, headers=a["headers"])).status_code == 404
    bad_thumb = _pdf_payload(
        a, changes=[{"kind": "added", "x": 1, "y": 1, "w": 1, "h": 1, "thumbnail": "javascript:x"}]
    )
    assert (await http_client.post(f"{_BASE}/comparisons/", json=bad_thumb, headers=a["headers"])).status_code == 422
    singular = _pdf_payload(a, alignment={"method": "auto", "matrix": [0, 0, 0, 0, 0, 0]})
    assert (await http_client.post(f"{_BASE}/comparisons/", json=singular, headers=a["headers"])).status_code == 422


@pytest.mark.asyncio
async def test_manual_alignment_is_computed_from_two_points(http_client, world):
    a = world["a"]
    body = _pdf_payload(
        a,
        alignment={"method": "manual", "points_old": [[0, 0], [100, 0]], "points_new": [[50, 50], [150, 50]]},
    )
    r = await http_client.post(f"{_BASE}/comparisons/", json=body, headers=a["headers"])
    assert r.status_code == 201, r.text
    assert r.json()["alignment"]["matrix"] == pytest.approx([1, 0, 0, 1, 50, 50])


@pytest.mark.asyncio
async def test_triage_and_validation(http_client, world):
    a = world["a"]
    cmp = await _create(http_client, a)
    report = await http_client.get(f"{_BASE}/comparisons/{cmp['id']}/validation/", headers=a["headers"])
    assert report.status_code == 200, report.text
    failing = {r["rule_id"] for r in report.json()["results"] if not r["passed"]}
    assert failing == {"drawing_compare.changes_triaged"}

    first, second = cmp["changes"]
    r = await http_client.patch(f"{_BASE}/changes/{first['id']}", json={"status": "relevant"}, headers=a["headers"])
    assert r.status_code == 200 and r.json()["status"] == "relevant"
    r = await http_client.patch(
        f"{_BASE}/changes/{second['id']}",
        json={"status": "not_relevant", "comment": "Title block"},
        headers=a["headers"],
    )
    assert r.json()["comment"] == "Title block"
    bad = await http_client.patch(f"{_BASE}/changes/{second['id']}", json={"status": "maybe"}, headers=a["headers"])
    assert bad.status_code == 422

    report = await http_client.get(f"{_BASE}/comparisons/{cmp['id']}/validation/", headers=a["headers"])
    failing = {r["rule_id"] for r in report.json()["results"] if not r["passed"]}
    assert failing == {"drawing_compare.relevant_changes_followed_up"}


@pytest.mark.asyncio
async def test_remeasure_dry_run_flag_and_clear(http_client, world):
    from app.database import async_session_factory
    from app.modules.boq.models import Position
    from app.modules.takeoff.models import TakeoffMeasurement

    a = world["a"]
    cmp = await _create(http_client, a)
    change = cmp["changes"][0]

    dry = await http_client.post(f"{_BASE}/changes/{change['id']}/remeasure/", headers=a["headers"])
    assert dry.status_code == 200, dry.text
    body = dry.json()
    assert body["dry_run"] is True
    found = {(i["id"], i["revision"]) for i in body["items"]}
    assert found == {(a["m_new"], "new"), (a["m_old"], "old")}
    assert [p["id"] for p in body["positions"]] == [a["pos"]]
    async with async_session_factory() as s:
        assert "needs_remeasure" not in (await s.get(TakeoffMeasurement, uuid.UUID(a["m_new"]))).metadata_

    flag = await http_client.post(
        f"{_BASE}/changes/{change['id']}/remeasure/", params={"dry_run": "false"}, headers=a["headers"]
    )
    assert flag.status_code == 200, flag.text
    assert flag.json()["flagged_at"]
    async with async_session_factory() as s:
        m_new = await s.get(TakeoffMeasurement, uuid.UUID(a["m_new"]))
        m_far = await s.get(TakeoffMeasurement, uuid.UUID(a["m_far"]))
        pos = await s.get(Position, uuid.UUID(a["pos"]))
        far_pos = await s.get(Position, uuid.UUID(a["far_pos"]))
        assert m_new.metadata_["needs_remeasure"]["change_id"] == change["id"]
        assert m_new.metadata_["needs_remeasure"]["comparison_id"] == cmp["id"]
        assert pos.metadata_["needs_remeasure"]["change_seq"] == 1
        assert "needs_remeasure" not in (m_far.metadata_ or {})
        assert "needs_remeasure" not in (far_pos.metadata_ or {})

    got = await http_client.get(f"{_BASE}/comparisons/{cmp['id']}", headers=a["headers"])
    stored = got.json()["changes"][0]
    assert stored["status"] == "relevant"
    assert sorted(stored["flagged_measurement_ids"]) == sorted([a["m_new"], a["m_old"]])
    assert stored["flagged_position_ids"] == [a["pos"]]

    cleared = await http_client.delete(f"{_BASE}/changes/{change['id']}/remeasure/", headers=a["headers"])
    assert cleared.status_code == 200
    assert cleared.json()["flagged_at"] is None
    async with async_session_factory() as s:
        assert "needs_remeasure" not in (await s.get(TakeoffMeasurement, uuid.UUID(a["m_new"]))).metadata_
        assert "needs_remeasure" not in (await s.get(Position, uuid.UUID(a["pos"]))).metadata_


@pytest.mark.asyncio
async def test_remeasure_leaves_a_locked_bill_alone(http_client, world):
    from app.database import async_session_factory
    from app.modules.boq.models import BOQ, Position

    a = world["a"]
    cmp = await _create(http_client, a)
    change = cmp["changes"][0]
    async with async_session_factory() as s:
        pos = await s.get(Position, uuid.UUID(a["pos"]))
        boq = await s.get(BOQ, pos.boq_id)
        boq.is_locked = True
        await s.commit()
    try:
        flag = await http_client.post(
            f"{_BASE}/changes/{change['id']}/remeasure/", params={"dry_run": "false"}, headers=a["headers"]
        )
        assert flag.status_code == 409, flag.text
        async with async_session_factory() as s:
            assert "needs_remeasure" not in ((await s.get(Position, uuid.UUID(a["pos"]))).metadata_ or {})
    finally:
        async with async_session_factory() as s:
            boq = await s.get(BOQ, (await s.get(Position, uuid.UUID(a["pos"]))).boq_id)
            boq.is_locked = False
            await s.commit()


@pytest.mark.asyncio
async def test_rfi_and_markup_from_change(http_client, world):
    a = world["a"]
    cmp = await _create(http_client, a)
    change = cmp["changes"][1]
    rfi = await http_client.post(f"{_BASE}/changes/{change['id']}/rfi/", json={}, headers=a["headers"])
    assert rfi.status_code == 201, rfi.text
    out = rfi.json()
    assert out["change"]["rfi_id"] == out["target_id"]
    assert out["change"]["status"] == "relevant"
    got = await http_client.get(f"/api/v1/rfi/{out['target_id']}", headers=a["headers"])
    assert got.status_code == 200, got.text
    assert "REV C" in got.json()["question"]
    assert got.json()["status"] == "draft"

    mk = await http_client.post(f"{_BASE}/changes/{change['id']}/markup/", json={}, headers=a["headers"])
    assert mk.status_code == 201, mk.text
    from app.database import async_session_factory
    from app.modules.markups.models import Markup

    async with async_session_factory() as s:
        markup = await s.get(Markup, uuid.UUID(mk.json()["target_id"]))
        assert markup.type == "cloud"
        assert markup.document_id == a["new_doc"]
        assert markup.geometry["points"][0] == [850, 640]
        assert markup.metadata_["drawing_compare"]["change_id"] == change["id"]

    pdf = await http_client.get(f"{_BASE}/comparisons/{cmp['id']}/report.pdf", headers=a["headers"])
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")


@pytest.mark.asyncio
async def test_other_tenant_and_viewer_are_kept_out(http_client, world):
    a, b = world["a"], world["b"]
    cmp = await _create(http_client, a)
    change_id = cmp["changes"][0]["id"]
    assert (await http_client.get(f"{_BASE}/comparisons/{cmp['id']}", headers=b["headers"])).status_code == 404
    assert (
        await http_client.get(f"{_BASE}/comparisons/", params={"project_id": a["project_id"]}, headers=b["headers"])
    ).status_code == 404
    r = await http_client.patch(f"{_BASE}/changes/{change_id}", json={"status": "relevant"}, headers=b["headers"])
    assert r.status_code == 404
    r = await http_client.post(
        f"{_BASE}/changes/{change_id}/remeasure/", params={"dry_run": "false"}, headers=b["headers"]
    )
    assert r.status_code == 404
    assert (await http_client.delete(f"{_BASE}/comparisons/{cmp['id']}", headers=b["headers"])).status_code == 404
    viewer = world["viewer"]
    r = await http_client.patch(f"{_BASE}/changes/{change_id}", json={"status": "relevant"}, headers=viewer)
    assert r.status_code == 403
    assert (await http_client.post(f"{_BASE}/comparisons/", json=_pdf_payload(a), headers=viewer)).status_code == 403
    # The owner can delete it.
    assert (await http_client.delete(f"{_BASE}/comparisons/{cmp['id']}", headers=a["headers"])).status_code == 204
    assert (await http_client.get(f"{_BASE}/comparisons/{cmp['id']}", headers=a["headers"])).status_code == 404


def _wall(x1: float, y1: float, x2: float, y2: float) -> dict:
    return {
        "entity_type": "LINE",
        "layer": "A-WALL",
        "geometry_data": {"start": {"x": x1, "y": y1}, "end": {"x": x2, "y": y2}},
    }


@pytest.mark.asyncio
async def test_dwg_compare_diffs_entities_on_the_server(http_client, world):
    from app.database import async_session_factory
    from app.modules.dwg_takeoff.models import DwgAnnotation, DwgDrawing, DwgDrawingVersion
    from app.modules.dwg_takeoff.service import _get_entities_dir

    a = world["a"]
    old_entities = [_wall(0, 0, 10000, 0), _wall(10000, 0, 10000, 10000), _wall(-50000, -50000, 50000, 50000)]
    new_entities = [_wall(0, 0, 10000, 0), _wall(4000, 0, 4000, 10000), _wall(-50000, -50000, 50000, 50000)]
    project_id = uuid.UUID(a["project_id"])
    async with async_session_factory() as s:
        drawing = DwgDrawing(
            project_id=project_id, name="A-101", filename="a101.dxf", file_format="dxf", file_path="x", status="ready"
        )
        s.add(drawing)
        await s.flush()
        versions = []
        for n, ents in ((1, old_entities), (2, new_entities)):
            key = f"dwgcmp-test/{drawing.id}/v{n}.json"
            path = os.path.join(_get_entities_dir(), key)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(ents, fh)
            v = DwgDrawingVersion(
                drawing_id=drawing.id, version_number=n, entities_key=key, entity_count=len(ents), status="ready"
            )
            s.add(v)
            versions.append(v)
        await s.flush()
        ann = DwgAnnotation(
            project_id=project_id,
            drawing_id=drawing.id,
            drawing_version_id=versions[1].id,
            annotation_type="distance",
            geometry={"points": [{"x": 3900, "y": 100}, {"x": 4100, "y": 100}]},
        )
        s.add(ann)
        await s.commit()
        drawing_id, v1, v2, ann_id = str(drawing.id), str(versions[0].id), str(versions[1].id), str(ann.id)

    r = await http_client.post(
        f"{_BASE}/comparisons/dwg/",
        json={
            "project_id": a["project_id"],
            "old_drawing_id": drawing_id,
            "new_drawing_id": drawing_id,
            "old_version_id": v1,
            "new_version_id": v2,
        },
        headers=a["headers"],
    )
    assert r.status_code == 201, r.text
    cmp = r.json()
    assert cmp["source_kind"] == "dwg"
    assert cmp["old_revision"] == "v1" and cmp["new_revision"] == "v2"
    assert cmp["summary"]["entities"] == {"added": 1, "removed": 1, "modified": 0, "unchanged": 2}
    assert cmp["summary"]["by_layer"] == [
        {"layer": "A-WALL", "entity_type": "LINE", "added": 1, "removed": 1, "modified": 0}
    ]
    kinds = sorted(c["kind"] for c in cmp["changes"])
    assert kinds == ["added", "removed"]
    added = next(c for c in cmp["changes"] if c["kind"] == "added")
    assert added["layer"] == "A-WALL"
    assert added["thumbnail"].startswith("data:image/svg+xml;base64,")

    dry = await http_client.post(f"{_BASE}/changes/{added['id']}/remeasure/", headers=a["headers"])
    assert [i["id"] for i in dry.json()["items"]] == [ann_id]

    mk = await http_client.post(f"{_BASE}/changes/{added['id']}/markup/", json={}, headers=a["headers"])
    assert mk.status_code == 201, mk.text
    async with async_session_factory() as s:
        rect = await s.get(DwgAnnotation, uuid.UUID(mk.json()["target_id"]))
        assert rect.annotation_type == "rectangle"
        assert str(rect.drawing_version_id) == v2

    same = await http_client.post(
        f"{_BASE}/comparisons/dwg/",
        json={"project_id": a["project_id"], "old_drawing_id": drawing_id, "new_drawing_id": drawing_id},
        headers=a["headers"],
    )
    assert same.status_code == 422
