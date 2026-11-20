"""The design and the other ERP modules, linked both ways: BOQ/viewer/4D link fields, the workspace lookup,
drawings in Documents, review tasks and notifications, the project overview."""

from __future__ import annotations

import uuid

import pytest

from .conftest import make_user
from .ddcrev import example_rows, package
from .test_design_revisions import BASE, DOOR, WALL, _linked_project, _upload
from .test_estimate_rules import SLAB
from .test_schedule import WALL_1OG, _rows_upper

pytestmark = pytest.mark.asyncio
PDF = b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"


async def _db(fn):
    from app.database import async_session_factory

    async with async_session_factory() as s:
        return await fn(s)


async def _all_linked(client):
    """R1 accepted with estimate, schedule and take-off set up; R2 (wall on 1.OG) accepted."""
    uid, h, pid, tok = await _linked_project(client)
    rows1 = example_rows()
    d1, m1 = package(pid, rows1)
    r1 = (await _upload(client, pid, tok, d1)).json()["revision_id"]
    assert (await client.post(f"{BASE}/revisions/{r1}/accept", headers=h)).status_code == 200
    est = f"{BASE}/projects/{pid}/estimate"
    assert (await client.post(f"{est}/rules/starter", json={"country": "DE"}, headers=h)).status_code == 201
    assert (await client.post(f"{est}/run", headers=h)).status_code == 200
    assert (
        await client.post(f"{BASE}/projects/{pid}/schedule/setup", json={"start_date": "2027-03-01"}, headers=h)
    ).status_code == 201
    assert (
        await client.post(f"{BASE}/projects/{pid}/procurement/setup", json={"group_by": "type_key"}, headers=h)
    ).status_code == 201
    d2, _ = package(pid, _rows_upper(), parent_id=m1["revision_id"], parent_rows=rows1)
    r2 = (await _upload(client, pid, tok, d2)).json()["revision_id"]
    assert (await client.post(f"{BASE}/revisions/{r2}/accept", headers=h)).status_code == 200
    return uid, h, pid, tok, r2, (await client.get(est, headers=h)).json()


async def test_accept_writes_the_design_links_into_the_erp_link_fields(client):
    from sqlalchemy import select

    from app.modules.bim_hub.models import BIMElement, BOQElementLink
    from app.modules.boq.models import Position
    from app.modules.design.models import DesignRevision
    from app.modules.schedule.models import Activity

    uid, h, pid, tok, r2, est = await _all_linked(client)
    wall_pos = next(p for p in est["positions"] if p["rule"] == "wall_ext")["position_id"]

    async def read(s):
        model = (await s.get(DesignRevision, uuid.UUID(r2))).bim_model_id
        ids = {
            k: i
            for k, i in (
                await s.execute(select(BIMElement.stable_id, BIMElement.id).where(BIMElement.model_id == model))
            ).all()
        }
        pos = await s.get(Position, uuid.UUID(wall_pos))
        lk = (await s.execute(select(BOQElementLink).where(BOQElementLink.boq_position_id == pos.id))).scalars().all()
        acts = (await s.execute(select(Activity).where(Activity.name.contains("1.OG")))).scalars().all()
        return model, ids, pos, lk, acts

    model, ids, pos, lk, acts = await _db(read)
    # BOQ row -> viewer highlight, on the accepted revision's model
    assert set(pos.cad_element_ids) == {WALL, WALL_1OG} and pos.cad_model_id == str(model)
    # viewer element -> BOQ position: the ERP's own link rows, marked as the design's
    assert {(link.bim_element_id, link.link_type, link.rule_id) for link in lk} == {
        (ids[WALL], "design", "wall_ext"),
        (ids[WALL_1OG], "design", "wall_ext"),
    }
    # 4D: the wall activity on 1.OG carries exactly the 1.OG wall
    wall_1og = [a for a in acts if any(str(x) == wall_pos for x in (a.boq_position_ids or []))]
    assert wall_1og and all(a.bim_element_ids == [str(ids[WALL_1OG])] for a in wall_1og)


async def test_sync_keeps_links_a_person_drew_and_is_idempotent(client):
    from sqlalchemy import func, select

    from app.modules.bim_hub.models import BIMElement, BOQElementLink
    from app.modules.design.models import DesignRevision

    uid, h, pid, tok, r2, est = await _all_linked(client)
    slab_pos = uuid.UUID(next(p for p in est["positions"] if p["rule"] == "slab")["position_id"])

    async def manual(s):
        model = (await s.get(DesignRevision, uuid.UUID(r2))).bim_model_id
        door = (
            await s.execute(select(BIMElement.id).where(BIMElement.model_id == model, BIMElement.stable_id == DOOR))
        ).scalar_one()
        s.add(BOQElementLink(boq_position_id=slab_pos, bim_element_id=door, link_type="manual"))
        await s.commit()

    await _db(manual)
    for _ in range(2):
        r = await client.post(f"{BASE}/projects/{pid}/links/sync", headers=h)
        assert r.status_code == 200 and r.json()["positions"] >= 2

    async def count(s):
        rows = (
            await s.execute(
                select(BOQElementLink.link_type, func.count())
                .where(BOQElementLink.boq_position_id == slab_pos)
                .group_by(BOQElementLink.link_type)
            )
        ).all()
        return dict(rows)

    assert await _db(count) == {"manual": 1, "design": 1}  # the hand-drawn link stays, the design's is not doubled
    other_uid, other_h = await make_user(client)
    assert (await client.post(f"{BASE}/projects/{pid}/links/sync", headers=other_h)).status_code in (403, 404)


async def test_lookup_answers_positions_activities_and_packages_for_an_element(client):
    uid, h, pid, tok, r2, est = await _all_linked(client)
    r = await client.get(f"{BASE}/projects/{pid}/links", params={"keys": [WALL_1OG]}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    sources = {(p["source"], p["elements"][0]) for p in body["positions"]}
    assert sources == {("estimate", WALL_1OG), ("takeoff", WALL_1OG)}
    est_pos = next(p for p in body["positions"] if p["source"] == "estimate")
    assert est_pos["boq_id"] and est_pos["ordinal"] and est_pos["unit"]
    assert [a["storey"] for a in body["activities"]] == ["1.OG"]  # only the storey the element is on
    assert [p["ifc_class"] for p in body["packages"]] == ["IfcWall"] and body["packages"][0]["status"] == "draft"
    nothing = (await client.get(f"{BASE}/projects/{pid}/links", params={"keys": ["no/such/key"]}, headers=h)).json()
    assert nothing["positions"] == nothing["activities"] == nothing["packages"] == []
    stranger_uid, stranger_h = await make_user(client)
    assert (
        await client.get(f"{BASE}/projects/{pid}/links", params={"keys": [WALL]}, headers=stranger_h)
    ).status_code in (403, 404)


async def test_position_elements_gives_the_viewer_its_isolate_list(client):
    uid, h, pid, tok, r2, est = await _all_linked(client)
    slab = next(p for p in est["positions"] if p["rule"] == "slab")["position_id"]
    r = await client.get(f"{BASE}/projects/{pid}/positions/{slab}/elements", headers=h)
    assert r.status_code == 200 and SLAB in r.json()["keys"]
    assert r.json()["isolate"] == r.json()["element_ids"] and r.json()["model_id"]
    assert (await client.get(f"{BASE}/projects/{pid}/positions/{uuid.uuid4()}/elements", headers=h)).status_code == 404


async def _documents(pid):
    from sqlalchemy import select

    from app.modules.documents.models import Document

    async def read(s):
        return (
            (
                await s.execute(
                    select(Document).where(Document.project_id == uuid.UUID(str(pid)), Document.category == "drawing")
                )
            )
            .scalars()
            .all()
        )

    return await _db(read)


async def test_every_revision_puts_its_sheets_into_documents_as_versions(client):
    uid, h, pid, tok = await _linked_project(client)
    rows1 = example_rows()
    d1, m1 = package(pid, rows1, files={"sheets/EG.pdf": PDF})
    r1 = (await _upload(client, pid, tok, d1)).json()["revision_id"]
    [doc] = await _documents(pid)
    assert doc.name == "Design_-_EG.pdf" or doc.name.endswith("EG.pdf")
    assert doc.metadata_["design"] == {
        "sheet": "sheets/EG.pdf",
        "revision_id": r1,
        "revision_number": 1,
        "status": "shared",
    }
    assert (await client.post(f"{BASE}/revisions/{r1}/accept", headers=h)).status_code == 200
    [doc] = await _documents(pid)
    assert doc.metadata_["design"]["status"] == "published"
    d2, _ = package(
        pid, _rows_upper(), parent_id=m1["revision_id"], parent_rows=rows1, files={"sheets/EG.pdf": PDF + b"% R2\n"}
    )
    r2 = (await _upload(client, pid, tok, d2)).json()["revision_id"]
    [doc2] = await _documents(pid)  # same drawing, a new version, not a second document
    assert doc2.id == doc.id and doc2.metadata_["design"]["revision_number"] == 2 and doc2.file_size == len(PDF) + 5
    assert doc2.metadata_["design"]["revision_id"] == r2


async def _owner_is(pid, user_id, keep_member=None):
    """Hand the project to another manager; the former owner stays on the team (as in a real office)."""
    from sqlalchemy import update

    from app.modules.projects.member_schemas import AddProjectMemberRequest
    from app.modules.projects.member_service import add_project_member
    from app.modules.projects.models import Project

    async def go(s):
        await s.execute(update(Project).where(Project.id == uuid.UUID(str(pid))).values(owner_id=user_id))
        if keep_member:
            await add_project_member(s, uuid.UUID(str(pid)), AddProjectMemberRequest(user_id=keep_member))
        await s.commit()

    await _db(go)


async def _notes(user_id):
    from sqlalchemy import select

    from app.modules.notifications.models import Notification

    async def read(s):
        # the ERP's own task-assigned notice is not ours to test
        return (
            (
                await s.execute(
                    select(Notification)
                    .where(Notification.user_id == user_id, Notification.title_key.like("design.notify.%"))
                    .order_by(Notification.created_at)
                )
            )
            .scalars()
            .all()
        )

    return await _db(read)


async def _tasks(pid):
    from sqlalchemy import select

    from app.modules.tasks.models import Task

    async def read(s):
        return (
            (
                await s.execute(
                    select(Task).where(Task.project_id == uuid.UUID(str(pid)), Task.task_type == "design_review")
                )
            )
            .scalars()
            .all()
        )

    return await _db(read)


async def test_shared_revision_raises_a_review_task_and_tells_the_manager(client):
    author, h, pid, tok = await _linked_project(client)
    manager, mh = await make_user(client)
    await _owner_is(pid, manager, keep_member=author)
    d1, _ = package(pid, example_rows())
    r1 = (await _upload(client, pid, tok, d1)).json()["revision_id"]
    [n] = await _notes(manager)
    assert (n.notification_type, n.title_key, n.entity_id) == (
        "design_revision_shared",
        "design.notify.revision_shared.title",
        r1,
    )
    assert n.body_context["number"] == 1 and n.action_url == f"/design/acceptance?project={pid}&revision={r1}"
    [task] = await _tasks(pid)
    assert task.status == "open" and str(task.responsible_id) == str(manager)
    assert task.metadata_["design_revision_id"] == r1 and "1" in task.title
    # the manager decides: the task closes, the author hears
    assert (await client.post(f"{BASE}/revisions/{r1}/accept", headers=mh)).status_code == 200
    [task] = await _tasks(pid)
    assert task.status == "completed" and task.result == "accepted"
    assert [x.title_key for x in await _notes(author)] == ["design.notify.revision_accepted.title"]


async def test_rejection_closes_the_task_and_no_one_is_told_about_their_own_upload(client):
    uid, h, pid, tok = await _linked_project(client)  # the author is the project manager here
    d1, _ = package(pid, example_rows())
    r1 = (await _upload(client, pid, tok, d1)).json()["revision_id"]
    assert await _notes(uid) == []
    [task] = await _tasks(pid)
    assert task.status == "open"
    assert (
        await client.post(f"{BASE}/revisions/{r1}/reject", json={"comment": "Too wide"}, headers=h)
    ).status_code == 200
    [task] = await _tasks(pid)
    assert task.status == "completed" and task.result == "rejected" and await _notes(uid) == []


async def test_overview_lists_each_module_with_its_state_and_where_to_open_it(client):
    uid, h, pid, tok = await _linked_project(client)
    empty = (await client.get(f"{BASE}/projects/{pid}/overview", headers=h)).json()
    assert [s["id"] for s in empty["steps"]] == [
        "brief",
        "model",
        "estimate",
        "schedule",
        "procurement",
        "documents",
        "bim",
        "change_orders",
        "tasks",
    ]
    assert not any(s["done"] for s in empty["steps"] if s["id"] != "tasks")
    uid, h, pid, tok, r2, est = await _all_linked(client)
    full = {s["id"]: s for s in (await client.get(f"{BASE}/projects/{pid}/overview", headers=h)).json()["steps"]}
    assert full["model"]["done"] and full["model"]["current"] == 2 and full["model"]["waiting"] == 0
    assert full["estimate"]["done"] and full["estimate"]["url"] == f"/boq/{est['boq_id']}"
    assert full["schedule"]["done"] and full["schedule"]["count"] >= 2
    assert full["procurement"]["done"] and full["procurement"]["count"] == 3
    assert full["bim"]["count"] >= 4 and full["bim"]["url"].startswith(f"/projects/{pid}/bim/")
    assert full["tasks"]["count"] == 0 and full["tasks"]["done"]
