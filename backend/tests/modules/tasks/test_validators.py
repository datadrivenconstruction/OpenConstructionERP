# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Task rule set on real PostgreSQL through the API: each rule fires, a valid task passes, an error blocks."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from app.modules.tasks.permissions import register_tasks_permissions
from app.modules.tasks.router import router as tasks_router
from app.modules.tasks.validators import register_tasks_validation_rules
from tests._pg import transactional_session
from tests.modules._control_pg import build_app, http, make_project, rule_ids

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator:
    register_tasks_permissions()
    register_tasks_validation_rules()
    async with transactional_session() as s:
        yield s


async def _create(c, project_id, **kw):
    body = {"project_id": str(project_id), "task_type": "task", "title": "Pour slab", "status": "open", **kw}
    return await c.post("/v1/tasks/", json=body)


async def test_valid_task_passes_without_findings(db_session) -> None:
    uid, pid = await make_project(db_session)
    async with http(build_app(tasks_router, "/v1/tasks", db_session, uid)) as c:
        r = await _create(c, pid, responsible_id=str(uid), due_date="2026-12-31")
    assert r.status_code == 201, r.text
    assert r.json()["validation_warnings"] == []


async def test_draft_and_note_types_are_not_flagged_for_a_missing_owner(db_session) -> None:
    uid, pid = await make_project(db_session)
    async with http(build_app(tasks_router, "/v1/tasks", db_session, uid)) as c:
        draft = await _create(c, pid, status="draft")
        note = await _create(c, pid, task_type="information")
    assert draft.json()["validation_warnings"] == []
    assert note.json()["validation_warnings"] == []


async def test_open_task_without_owner_warns_and_is_saved(db_session) -> None:
    uid, pid = await make_project(db_session)
    async with http(build_app(tasks_router, "/v1/tasks", db_session, uid)) as c:
        r = await _create(c, pid)
    assert r.status_code == 201, r.text
    assert rule_ids(r.json()["validation_warnings"]) == {"tasks.owner_assigned"}


async def test_impossible_due_date_is_refused_with_its_code(db_session) -> None:
    uid, pid = await make_project(db_session)
    async with http(build_app(tasks_router, "/v1/tasks", db_session, uid)) as c:
        r = await _create(c, pid, responsible_id=str(uid), due_date="2026-02-31")
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert detail["error"] == "validation_failed"
    assert detail["code"] == "tasks.due_date_exists"
    assert detail["errors"][0]["element_ref"] == ""


async def test_impossible_due_date_on_update_is_refused(db_session) -> None:
    uid, pid = await make_project(db_session)
    async with http(build_app(tasks_router, "/v1/tasks", db_session, uid)) as c:
        made = (await _create(c, pid, responsible_id=str(uid))).json()
        r = await c.patch(f"/v1/tasks/{made['id']}", json={"due_date": "2027-04-31"})
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "tasks.due_date_exists"


async def test_completing_with_open_checklist_items_warns(db_session) -> None:
    uid, pid = await make_project(db_session)
    async with http(build_app(tasks_router, "/v1/tasks", db_session, uid)) as c:
        made = (
            await _create(
                c,
                pid,
                responsible_id=str(uid),
                checklist=[{"text": "Cure 7 days", "completed": True}, {"text": "Strip formwork", "completed": False}],
            )
        ).json()
        r = await c.post(f"/v1/tasks/{made['id']}/complete/", json={})
    assert r.status_code == 200, r.text
    assert rule_ids(r.json()["validation_warnings"]) == {"tasks.checklist_closed"}
    assert r.json()["status"] == "completed"


async def test_completing_a_decision_without_a_result_warns(db_session) -> None:
    uid, pid = await make_project(db_session)
    async with http(build_app(tasks_router, "/v1/tasks", db_session, uid)) as c:
        made = (await _create(c, pid, task_type="decision", responsible_id=str(uid))).json()
        r = await c.post(f"/v1/tasks/{made['id']}/complete/", json={})
        recorded = (await _create(c, pid, task_type="decision", responsible_id=str(uid))).json()
        ok = await c.post(f"/v1/tasks/{recorded['id']}/complete/", json={"result": "Use C30/37 for the slab"})
    assert rule_ids(r.json()["validation_warnings"]) == {"tasks.decision_recorded"}
    assert ok.status_code == 200 and ok.json()["validation_warnings"] == []


async def test_editing_a_title_does_not_resurface_a_legacy_due_date(db_session) -> None:
    uid, pid = await make_project(db_session)
    async with http(build_app(tasks_router, "/v1/tasks", db_session, uid)) as c:
        made = (await _create(c, pid, responsible_id=str(uid))).json()
        r = await c.patch(f"/v1/tasks/{made['id']}", json={"title": "Pour slab level 2"})
    assert r.status_code == 200, r.text
    assert r.json()["validation_warnings"] == []
