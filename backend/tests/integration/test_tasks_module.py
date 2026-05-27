"""Integration tests for the Tasks (Planning) module.

Covers the bugs fixed in the v3.0.x Tasks audit:

* status state-machine enforcement on PATCH (illegal transitions -> 400)
* completion is allowed from any non-completed state and now publishes a
  ``tasks.task.updated`` event + writes an audit log
* dependency guard on complete + on create-as-completed (409)
* dependency cycle / self-reference rejection
* ``assigned_to_name`` is resolved from ``responsible_id`` (was always
  null)
* ``/my-tasks/`` returns only the caller's tasks (cross-project)
* checklist_progress / is_overdue computed fields
* Excel export + template + CSV import round-trip
* private-task visibility

Test isolation: the session-scoped temp SQLite from ``tests/conftest.py``
is used; no production DB is touched.

Run:
    cd backend
    python -m pytest tests/integration/test_tasks_module.py -q
"""

from __future__ import annotations

import io
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app

TASKS = "/api/v1/tasks"


# ── Module-scoped client + auth (avoid login rate limiter) ─────────────────


@pytest_asyncio.fixture(scope="module")
async def client():
    app = create_app()
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan_ctx():
        async with app.router.lifespan_context(app):
            yield

    async with lifespan_ctx():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest_asyncio.fixture(scope="module")
async def auth(client: AsyncClient) -> dict[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"tasks-{unique}@test.io"
    password = f"TasksPw{unique}9"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": "Task Tester",
            "role": "admin",
        },
    )
    assert reg.status_code == 201, f"register failed: {reg.text}"

    from tests.integration._auth_helpers import promote_to_admin

    await promote_to_admin(email)

    resp = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    token = resp.json().get("access_token", "")
    assert token, f"login failed: {resp.text}"
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture(scope="module")
async def user_id(auth: dict[str, str]) -> str:
    from jose import jwt

    from app.config import get_settings

    settings = get_settings()
    token = auth["Authorization"].removeprefix("Bearer ")
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    return payload["sub"]


@pytest_asyncio.fixture(scope="module")
async def project_id(client: AsyncClient, auth: dict[str, str]) -> str:
    resp = await client.post(
        "/api/v1/projects/",
        json={
            "name": f"Tasks Project {uuid.uuid4().hex[:6]}",
            "description": "Tasks module test project",
            "region": "DACH",
            "classification_standard": "din276",
            "currency": "EUR",
        },
        headers=auth,
    )
    assert resp.status_code == 201, f"project create failed: {resp.text}"
    return resp.json()["id"]


# ── Helpers ────────────────────────────────────────────────────────────────


async def _create_task(client, auth, project_id, **overrides):
    body = {
        "project_id": project_id,
        "task_type": "task",
        "title": "Default task",
    }
    body.update(overrides)
    resp = await client.post(f"{TASKS}/", json=body, headers=auth)
    return resp


# ── CRUD ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_and_get_task(client, auth, project_id):
    resp = await _create_task(client, auth, project_id, title="Inspect facade")
    assert resp.status_code == 201, resp.text
    task = resp.json()
    assert task["title"] == "Inspect facade"
    assert task["status"] == "draft"
    assert task["is_overdue"] is False
    assert task["checklist_progress"] == 0.0

    got = await client.get(f"{TASKS}/{task['id']}", headers=auth)
    assert got.status_code == 200
    assert got.json()["id"] == task["id"]


@pytest.mark.asyncio
async def test_list_tasks_for_project(client, auth, project_id):
    await _create_task(client, auth, project_id, title="Listed task")
    resp = await client.get(f"{TASKS}/?project_id={project_id}", headers=auth)
    assert resp.status_code == 200
    assert any(t["title"] == "Listed task" for t in resp.json())


# ── Status state machine (BUG: illegal transitions silently rolled back) ────


@pytest.mark.asyncio
async def test_illegal_status_transition_rejected(client, auth, project_id):
    """draft -> in_progress is NOT allowed (draft can only go to open)."""
    created = (await _create_task(client, auth, project_id)).json()
    resp = await client.patch(
        f"{TASKS}/{created['id']}",
        json={"status": "in_progress"},
        headers=auth,
    )
    assert resp.status_code == 400
    assert "transition" in resp.text.lower()


@pytest.mark.asyncio
async def test_legal_status_transition_chain(client, auth, project_id):
    created = (await _create_task(client, auth, project_id)).json()
    tid = created["id"]
    # draft -> open -> in_progress
    r1 = await client.patch(f"{TASKS}/{tid}", json={"status": "open"}, headers=auth)
    assert r1.status_code == 200, r1.text
    r2 = await client.patch(f"{TASKS}/{tid}", json={"status": "in_progress"}, headers=auth)
    assert r2.status_code == 200, r2.text
    assert r2.json()["status"] == "in_progress"


# ── Completion: any non-completed state + event + audit ────────────────────


@pytest.mark.asyncio
async def test_complete_task_from_draft_succeeds(client, auth, project_id):
    """The dedicated complete endpoint is the canonical happy path and is
    allowed from any non-completed status (incl. draft)."""
    created = (await _create_task(client, auth, project_id)).json()
    resp = await client.post(
        f"{TASKS}/{created['id']}/complete/",
        json={"result": "All good"},
        headers=auth,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "completed"
    assert body["result"] == "All good"
    assert body["completed_at"] is not None


@pytest.mark.asyncio
async def test_complete_publishes_update_event(client, auth, project_id):
    """Completion must keep the vector index in sync (regression: it used
    to skip the lifecycle event entirely)."""
    from app.core.events import event_bus

    seen: list[dict] = []

    async def _capture(ev):
        seen.append(ev.data or {})

    event_bus.subscribe("tasks.task.updated", _capture)
    try:
        created = (await _create_task(client, auth, project_id)).json()
        await client.post(f"{TASKS}/{created['id']}/complete/", headers=auth)
    finally:
        event_bus.unsubscribe("tasks.task.updated", _capture)

    assert any(d.get("task_id") == created["id"] for d in seen), (
        f"no tasks.task.updated event for completed task; saw {seen}"
    )


@pytest.mark.asyncio
async def test_double_complete_rejected(client, auth, project_id):
    created = (await _create_task(client, auth, project_id)).json()
    await client.post(f"{TASKS}/{created['id']}/complete/", headers=auth)
    again = await client.post(f"{TASKS}/{created['id']}/complete/", headers=auth)
    assert again.status_code == 400


@pytest.mark.asyncio
async def test_cannot_edit_completed_task(client, auth, project_id):
    created = (await _create_task(client, auth, project_id)).json()
    await client.post(f"{TASKS}/{created['id']}/complete/", headers=auth)
    resp = await client.patch(f"{TASKS}/{created['id']}", json={"title": "new"}, headers=auth)
    assert resp.status_code == 400


# ── Dependency guard ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_complete_blocked_by_incomplete_dependency(client, auth, project_id):
    pred = (await _create_task(client, auth, project_id, title="Predecessor")).json()
    dep = (await _create_task(client, auth, project_id, title="Dependent", depends_on=pred["id"])).json()
    resp = await client.post(f"{TASKS}/{dep['id']}/complete/", headers=auth)
    assert resp.status_code == 409
    assert "blocked by" in resp.text.lower()

    # Complete predecessor, then the dependent goes through.
    await client.post(f"{TASKS}/{pred['id']}/complete/", headers=auth)
    ok = await client.post(f"{TASKS}/{dep['id']}/complete/", headers=auth)
    assert ok.status_code == 200, ok.text


@pytest.mark.asyncio
async def test_create_completed_with_incomplete_dependency_rejected(client, auth, project_id):
    pred = (await _create_task(client, auth, project_id, title="Pred2")).json()
    resp = await _create_task(
        client,
        auth,
        project_id,
        title="Born done",
        status="completed",
        depends_on=pred["id"],
    )
    assert resp.status_code == 409, resp.text


@pytest.mark.asyncio
async def test_self_dependency_rejected(client, auth, project_id):
    created = (await _create_task(client, auth, project_id)).json()
    resp = await client.patch(
        f"{TASKS}/{created['id']}",
        json={"depends_on": created["id"]},
        headers=auth,
    )
    assert resp.status_code == 400
    assert "itself" in resp.text.lower()


@pytest.mark.asyncio
async def test_dependency_cycle_rejected(client, auth, project_id):
    a = (await _create_task(client, auth, project_id, title="A")).json()
    b = (await _create_task(client, auth, project_id, title="B", depends_on=a["id"])).json()
    # a -> b would close the loop a->b->a
    resp = await client.patch(f"{TASKS}/{a['id']}", json={"depends_on": b["id"]}, headers=auth)
    assert resp.status_code == 400
    assert "cycle" in resp.text.lower()


# ── Assignee name resolution (BUG: assigned_to_name always null) ───────────


@pytest.mark.asyncio
async def test_assigned_to_name_resolved(client, auth, project_id, user_id):
    resp = await _create_task(client, auth, project_id, title="Assigned", responsible_id=user_id)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["assigned_to"] == user_id
    assert body["assigned_to_name"], "assigned_to_name should resolve from user row"

    listed = await client.get(f"{TASKS}/?project_id={project_id}", headers=auth)
    match = next(t for t in listed.json() if t["id"] == body["id"])
    assert match["assigned_to_name"] == body["assigned_to_name"]


# ── My tasks (BUG: client heuristic matched every task) ────────────────────


@pytest.mark.asyncio
async def test_my_tasks_returns_only_callers_tasks(client, auth, project_id, user_id):
    mine = (await _create_task(client, auth, project_id, title="Mine!", responsible_id=user_id)).json()
    resp = await client.get(f"{TASKS}/my-tasks/", headers=auth)
    assert resp.status_code == 200
    ids = {t["id"] for t in resp.json()}
    assert mine["id"] in ids


# ── Checklist progress computed field ──────────────────────────────────────


@pytest.mark.asyncio
async def test_checklist_progress_computed(client, auth, project_id):
    resp = await _create_task(
        client,
        auth,
        project_id,
        title="With checklist",
        checklist=[
            {"text": "Step 1", "completed": True},
            {"text": "Step 2", "completed": False},
        ],
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["checklist_progress"] == 50.0


# ── Stats ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stats_endpoint(client, auth, project_id):
    resp = await client.get(f"{TASKS}/stats/?project_id={project_id}", headers=auth)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    assert isinstance(body["by_status"], dict)


# ── Export / template / import round-trip ──────────────────────────────────


@pytest.mark.asyncio
async def test_export_returns_xlsx(client, auth, project_id):
    resp = await client.get(f"{TASKS}/export/?project_id={project_id}", headers=auth)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert resp.content[:2] == b"PK"  # xlsx is a zip


@pytest.mark.asyncio
async def test_template_download(client, auth):
    resp = await client.get(f"{TASKS}/template/", headers=auth)
    assert resp.status_code == 200
    assert resp.content[:2] == b"PK"


@pytest.mark.asyncio
async def test_csv_import(client, auth, project_id):
    csv_bytes = (
        b"Title,Type,Status,Priority,Due Date,Description\n"
        b"Imported A,task,open,high,2099-01-01,from csv\n"
        b"Imported B,topic,draft,low,,no due date\n"
        b",task,open,low,,blank title skipped\n"
        b"Bad Date,task,open,low,not-a-date,bad\n"
    )

    files = {"file": ("tasks.csv", io.BytesIO(csv_bytes), "text/csv")}
    resp = await client.post(
        f"{TASKS}/import/file/?project_id={project_id}",
        files=files,
        headers=auth,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["imported"] == 2
    assert body["skipped"] == 1  # blank title
    assert len(body["errors"]) == 1  # bad date


@pytest.mark.asyncio
async def test_import_rejects_unsupported_type(client, auth, project_id):
    files = {"file": ("tasks.txt", io.BytesIO(b"nope"), "text/plain")}
    resp = await client.post(
        f"{TASKS}/import/file/?project_id={project_id}",
        files=files,
        headers=auth,
    )
    assert resp.status_code == 400


# ── Private-task visibility ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_private_task_hidden_from_other_user(client, auth, project_id):
    """A second admin cannot see another user's private task."""
    priv = (await _create_task(client, auth, project_id, title="Secret", is_private=True)).json()

    unique = uuid.uuid4().hex[:8]
    email = f"tasks-other-{unique}@test.io"
    password = f"Other{unique}9A"
    await client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": "Other",
            "role": "admin",
        },
    )
    from tests.integration._auth_helpers import promote_to_admin

    await promote_to_admin(email)
    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    other_auth = {"Authorization": f"Bearer {login.json()['access_token']}"}

    got = await client.get(f"{TASKS}/{priv['id']}", headers=other_auth)
    assert got.status_code == 404


# ── Delete ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_task(client, auth, project_id):
    created = (await _create_task(client, auth, project_id, title="Doomed")).json()
    resp = await client.delete(f"{TASKS}/{created['id']}", headers=auth)
    assert resp.status_code == 204
    got = await client.get(f"{TASKS}/{created['id']}", headers=auth)
    assert got.status_code == 404
