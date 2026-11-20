"""Selection panel: documents linked to the selected elements and their open remarks (tasks, punch items)."""

from __future__ import annotations

import uuid

import pytest

from .conftest import make_user
from .test_design_revisions import BASE, WALL
from .test_integration import _all_linked, _db
from .test_schedule import WALL_1OG

pytestmark = pytest.mark.asyncio


async def _seed(pid):
    """A document linked to WALL_1OG, an open task on it, a closed task, an open punch item named by the key."""
    from sqlalchemy import select

    from app.modules.bim_hub.models import BIMElement
    from app.modules.design.field_links import published
    from app.modules.documents.models import Document, DocumentBIMLink
    from app.modules.qms.models import QMSPunchItem
    from app.modules.tasks.models import Task

    p = uuid.UUID(str(pid))

    async def make(s):
        rev = await published(s, p)
        eid = (
            await s.execute(
                select(BIMElement.id).where(BIMElement.model_id == rev.bim_model_id, BIMElement.stable_id == WALL_1OG)
            )
        ).scalar_one()
        doc = Document(project_id=p, name="Wall detail.pdf", category="drawing")
        s.add(doc)
        await s.flush()
        s.add(DocumentBIMLink(document_id=doc.id, bim_element_id=eid, link_type="manual"))
        open_t = Task(
            project_id=p,
            task_type="defect",
            title="Crack in wall",
            status="open",
            bim_element_ids=[str(eid)],
            due_date="2027-04-01",
        )
        done_t = Task(
            project_id=p, task_type="defect", title="Old remark", status="completed", bim_element_ids=[str(eid)]
        )
        other = Task(project_id=p, task_type="task", title="Elsewhere", status="open", bim_element_ids=[])
        punch = QMSPunchItem(project_id=p, title="Paint missing", status="open", bim_element_ref=WALL_1OG)
        s.add_all([open_t, done_t, other, punch])
        await s.flush()
        out = {"doc": str(doc.id), "task": str(open_t.id), "punch": str(punch.id)}
        await s.commit()
        return out

    return await _db(make)


async def test_documents_and_open_remarks_of_the_selection(client):
    uid, h, pid, tok, r2, est = await _all_linked(client)
    made = await _seed(pid)
    url = f"{BASE}/projects/{pid}/element-context"
    got = (await client.get(url, params={"keys": [WALL_1OG]}, headers=h)).json()
    assert got["found"] == 1 and got["quantities"] and all(float(q["value"]) > 0 for q in got["quantities"])
    docs = {d["document_id"]: d for d in got["documents"]}
    assert docs[made["doc"]]["elements"] == [WALL_1OG] and docs[made["doc"]]["url"] == f"/documents?id={made['doc']}"
    assert [(r["kind"], r["id"]) for r in got["remarks"]] == [("task", made["task"]), ("punch", made["punch"])]
    assert got["remarks"][0]["url"] == f"/tasks?id={made['task']}" and got["remarks"][1]["url"].endswith(made["punch"])
    # another element: none of it
    other = (await client.get(url, params={"keys": [WALL]}, headers=h)).json()
    assert made["doc"] not in {d["document_id"] for d in other["documents"]} and other["remarks"] == []
    assert (await client.get(url, headers=h)).json() == {
        "keys": [],
        "found": 0,
        "quantities": [],
        "documents": [],
        "remarks": [],
    }


async def test_element_context_needs_access(client):
    uid, h, pid, tok, r2, est = await _all_linked(client)
    url = f"{BASE}/projects/{pid}/element-context"
    assert (await client.get(url, params={"keys": [WALL_1OG]})).status_code == 401
    _, h2 = await make_user(client)
    assert (await client.get(url, params={"keys": [WALL_1OG]}, headers=h2)).status_code in (403, 404)
    assert (await client.get(url, params={"keys": [f"k{i}" for i in range(501)]}, headers=h)).status_code == 422
