"""Schedule (4D Schedule) IDOR regression suite.

The ``/api/v1/schedule/`` router exposes endpoints keyed off
``schedule_id``. Several read/mutate endpoints historically skipped the
project-ownership gate that every sibling endpoint applies, letting one
tenant enumerate (and in some cases mutate) another tenant's schedule:

* ``GET  /schedules/{id}/gantt/``            — primary read leak; the
  frontend's main data feed. Pre-fix: no ownership check at all.
* ``GET  /schedules/{id}/activities/``       — list-leak vector.
* ``POST /schedules/{id}/calculate-cpm/``    — write IDOR (mutates
  activity colours / CPM metadata of any schedule).
* ``GET  /schedules/{id}/risk-analysis/``    — read leak + write
  side-effect (re-runs CPM).
* ``POST /schedules/{id}/generate-from-boq/``— write IDOR (populates
  another tenant's schedule).
* ``GET  /work-orders/?schedule_id=X``       — list-leak vector.
* ``GET  /schedule/export/csv/?schedule_id=X`` — full-schedule leak.
* ``POST /schedule/cpm/calculate/?schedule_id=X`` — write IDOR.

Convention: cross-tenant access returns **403/404**, never a 2xx —
matching ``verify_project_access`` so endpoints can't be turned into a
UUID-existence oracle.

Scaffolding mirrors ``test_reporting_idor.py``: the engine is bound to the
shared PostgreSQL cluster by ``conftest.py`` before any ``from app...``
import runs (see ``feedback_test_isolation.md``).
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()

    async with app.router.lifespan_context(app):
        from app.database import Base, engine
        from app.modules.schedule import models as _schedule_models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _activate_user(email: str) -> None:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(is_active=True))
        await s.commit()


async def _register_and_login(
    client: AsyncClient,
    *,
    tenant: str,
) -> tuple[str, str, str, dict[str, str]]:
    email = f"{tenant}-{uuid.uuid4().hex[:8]}@schedule-idor.io"
    password = f"ScheduleIdor{uuid.uuid4().hex[:6]}9"

    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": f"Tenant {tenant}"},
    )
    assert reg.status_code in (200, 201), f"register failed for {tenant}: {reg.status_code} {reg.text}"
    user_id = reg.json()["id"]

    await _activate_user(email)

    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, f"login failed for {tenant}: {login.text}"
    token = login.json()["access_token"]
    return user_id, email, password, {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture(scope="module")
async def two_schedule_tenants(http_client):
    """A owns a project + schedule + activities; B is the attacker."""
    a_uid, a_email, a_password, _a_headers = await _register_and_login(
        http_client,
        tenant="a",
    )
    b_uid, b_email, _b_password, b_headers = await _register_and_login(
        http_client,
        tenant="b",
    )

    # Promote A so they can hit POST /projects/ (registration drops new
    # accounts to viewer, which lacks projects.create). B stays a viewer.
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == a_email.lower()).values(role="admin", is_active=True))
        await s.commit()

    a_login = await http_client.post(
        "/api/v1/users/auth/login",
        json={"email": a_email, "password": a_password},
    )
    assert a_login.status_code == 200, a_login.text
    a_headers = {"Authorization": f"Bearer {a_login.json()['access_token']}"}

    proj = await http_client.post(
        "/api/v1/projects/",
        json={
            "name": f"Schedule-A {uuid.uuid4().hex[:6]}",
            "description": "owned by A — used by schedule IDOR tests",
            "currency": "EUR",
        },
        headers=a_headers,
    )
    assert proj.status_code == 201, f"project create failed: {proj.text}"
    project_id = proj.json()["id"]

    sched = await http_client.post(
        "/api/v1/schedule/schedules/",
        json={
            "project_id": project_id,
            "name": "A confidential master schedule",
            "start_date": "2026-05-01",
            "end_date": "2026-09-30",
        },
        headers=a_headers,
    )
    assert sched.status_code == 201, f"schedule create failed: {sched.text}"
    schedule_id = sched.json()["id"]

    act = await http_client.post(
        f"/api/v1/schedule/schedules/{schedule_id}/activities/",
        json={
            "name": "A secret foundation works",
            "wbs_code": "01.01",
            "start_date": "2026-05-04",
            "end_date": "2026-05-15",
            "activity_type": "task",
        },
        headers=a_headers,
    )
    assert act.status_code == 201, f"activity create failed: {act.text}"
    activity_id = act.json()["id"]

    wo = await http_client.post(
        f"/api/v1/schedule/activities/{activity_id}/work-orders/",
        json={"code": "WO-A-001", "description": "A confidential work order"},
        headers=a_headers,
    )
    assert wo.status_code == 201, f"work order create failed: {wo.text}"

    return {
        "a": {
            "headers": a_headers,
            "project_id": project_id,
            "schedule_id": schedule_id,
            "activity_id": activity_id,
        },
        "b": {"user_id": b_uid, "email": b_email, "headers": b_headers},
    }


# ── Read-leak vectors ──────────────────────────────────────────────────────


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_tenant_b_cannot_read_gantt(http_client, two_schedule_tenants):
    """``GET /schedules/{id}/gantt/`` must NOT leak A's schedule.

    Primary fix: this is the frontend's main data feed and pre-fix it
    had zero ownership verification.
    """
    a = two_schedule_tenants["a"]
    b = two_schedule_tenants["b"]

    resp = await http_client.get(
        f"/api/v1/schedule/schedules/{a['schedule_id']}/gantt/",
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), f"LEAK: B read A's gantt: {resp.status_code} {resp.text!r}"
    assert "secret foundation" not in resp.text


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_tenant_b_cannot_list_activities(http_client, two_schedule_tenants):
    a = two_schedule_tenants["a"]
    b = two_schedule_tenants["b"]

    resp = await http_client.get(
        f"/api/v1/schedule/schedules/{a['schedule_id']}/activities/",
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), f"LEAK: B listed A's activities: {resp.status_code} {resp.text!r}"
    assert "secret foundation" not in resp.text


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_tenant_b_cannot_list_work_orders(http_client, two_schedule_tenants):
    a = two_schedule_tenants["a"]
    b = two_schedule_tenants["b"]

    resp = await http_client.get(
        f"/api/v1/schedule/work-orders/?schedule_id={a['schedule_id']}",
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), f"LEAK: B listed A's work orders: {resp.status_code} {resp.text!r}"
    assert "confidential work order" not in resp.text


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_tenant_b_cannot_export_csv(http_client, two_schedule_tenants):
    a = two_schedule_tenants["a"]
    b = two_schedule_tenants["b"]

    resp = await http_client.get(
        f"/api/v1/schedule/schedule/export/csv/?schedule_id={a['schedule_id']}",
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), f"LEAK: B exported A's schedule CSV: {resp.status_code} {resp.text!r}"
    assert "secret foundation" not in resp.text


# ── Write IDOR vectors ─────────────────────────────────────────────────────


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_tenant_b_cannot_calculate_cpm(http_client, two_schedule_tenants):
    """``POST .../calculate-cpm/`` mutates activity colours/metadata."""
    a = two_schedule_tenants["a"]
    b = two_schedule_tenants["b"]

    resp = await http_client.post(
        f"/api/v1/schedule/schedules/{a['schedule_id']}/calculate-cpm/",
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), f"WRITE-IDOR: B ran CPM on A's schedule: {resp.status_code} {resp.text!r}"


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_tenant_b_cannot_get_risk_analysis(http_client, two_schedule_tenants):
    a = two_schedule_tenants["a"]
    b = two_schedule_tenants["b"]

    resp = await http_client.get(
        f"/api/v1/schedule/schedules/{a['schedule_id']}/risk-analysis/",
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), (
        f"LEAK: B ran risk analysis on A's schedule: {resp.status_code} {resp.text!r}"
    )


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_tenant_b_cannot_generate_from_boq(http_client, two_schedule_tenants):
    a = two_schedule_tenants["a"]
    b = two_schedule_tenants["b"]

    resp = await http_client.post(
        f"/api/v1/schedule/schedules/{a['schedule_id']}/generate-from-boq/",
        json={"boq_id": str(uuid.uuid4())},
        headers=b["headers"],
    )
    # Must be rejected by the ownership gate BEFORE any BOQ lookup.
    assert resp.status_code in (403, 404), (
        f"WRITE-IDOR: B generated into A's schedule: {resp.status_code} {resp.text!r}"
    )


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_tenant_b_cannot_calculate_cpm_full(http_client, two_schedule_tenants):
    a = two_schedule_tenants["a"]
    b = two_schedule_tenants["b"]

    resp = await http_client.post(
        f"/api/v1/schedule/schedule/cpm/calculate/?schedule_id={a['schedule_id']}",
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), (
        f"WRITE-IDOR: B ran full CPM on A's schedule: {resp.status_code} {resp.text!r}"
    )


# ── Regression guards: the owner must still have access ────────────────────


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_owner_can_still_read_gantt(http_client, two_schedule_tenants):
    a = two_schedule_tenants["a"]
    resp = await http_client.get(
        f"/api/v1/schedule/schedules/{a['schedule_id']}/gantt/",
        headers=a["headers"],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["summary"]["total_activities"] == 1


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_owner_can_still_list_activities(http_client, two_schedule_tenants):
    a = two_schedule_tenants["a"]
    resp = await http_client.get(
        f"/api/v1/schedule/schedules/{a['schedule_id']}/activities/",
        headers=a["headers"],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_owner_can_still_calculate_cpm(http_client, two_schedule_tenants):
    a = two_schedule_tenants["a"]
    resp = await http_client.post(
        f"/api/v1/schedule/schedules/{a['schedule_id']}/calculate-cpm/",
        headers=a["headers"],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["schedule_id"] == a["schedule_id"]
    assert len(body["all_activities"]) == 1


# ── CSV formula-injection neutralisation ──────────────────────────────────


@pytest.mark.asyncio
async def test_csv_export_neutralises_formula_payload(http_client, two_schedule_tenants):
    """A malicious activity name must not export as a live spreadsheet formula.

    ``GET /schedule/export/csv/`` writes user-controlled activity fields
    (name, code, WBS) into CSV cells. A value like ``=cmd|'/c calc'!A1``
    would execute when opened in Excel / Sheets / LibreOffice (CSV/formula
    injection - OWASP). The export must prepend a single apostrophe so the
    cell is treated as literal text. Owner-side export so the value round
    trips back to the same tenant.
    """
    a = two_schedule_tenants["a"]
    payload = "=cmd|'/c calc'!A1"

    act = await http_client.post(
        f"/api/v1/schedule/schedules/{a['schedule_id']}/activities/",
        json={
            "name": payload,
            "wbs_code": '=HYPERLINK("http://evil")',
            "start_date": "2026-06-01",
            "end_date": "2026-06-10",
            "activity_type": "task",
        },
        headers=a["headers"],
    )
    assert act.status_code == 201, act.text

    resp = await http_client.get(
        f"/api/v1/schedule/schedule/export/csv/?schedule_id={a['schedule_id']}",
        headers=a["headers"],
    )
    assert resp.status_code == 200, resp.text
    body = resp.text
    # The raw, un-neutralised formula must NOT appear as a cell start; the
    # apostrophe-guarded variant must.
    assert "'" + payload in body, f"formula payload not neutralised: {body!r}"
    assert ",=cmd" not in body and '"=cmd' not in body, f"raw formula leaked into a cell: {body!r}"


# ── Cross-tenant content through ids the attacker supplies ─────────────────
#
# The vectors above send another tenant's SCHEDULE id. These send the
# attacker's own schedule with another tenant's BOQ or activity id inside the
# body: the ownership gate passes (the schedule is theirs), so only a check on
# the referenced row stops the copy or the cross-tenant edge.


@pytest_asyncio.fixture(scope="module")
async def editor_with_own_schedule(http_client, two_schedule_tenants):
    """C is an editor with a project and schedule of their own; A owns a BOQ."""
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.boq.models import BOQ, Position
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    c_uid, c_email, c_password, _ = await _register_and_login(http_client, tenant="c")
    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == c_email.lower()).values(role="editor", is_active=True))
        project = Project(name=f"Schedule-C {uuid.uuid4().hex[:6]}", owner_id=uuid.UUID(c_uid))
        s.add(project)
        a_boq = BOQ(project_id=uuid.UUID(two_schedule_tenants["a"]["project_id"]), name="A confidential bill")
        s.add(a_boq)
        await s.flush()
        s.add(
            Position(
                boq_id=a_boq.id,
                parent_id=None,
                ordinal="01.001",
                description="A secret voce of the bill",
                unit="m3",
                quantity="10",
                unit_rate="100",
                total="1000",
                metadata_={},
                sort_order=1,
            )
        )
        await s.commit()
        c_project_id = str(project.id)
        a_boq_id = str(a_boq.id)

    login = await http_client.post("/api/v1/users/auth/login", json={"email": c_email, "password": c_password})
    assert login.status_code == 200, login.text
    c_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    sched = await http_client.post(
        "/api/v1/schedule/schedules/",
        json={"project_id": c_project_id, "name": "C schedule", "start_date": "2026-05-01"},
        headers=c_headers,
    )
    assert sched.status_code == 201, sched.text
    c_schedule_id = sched.json()["id"]
    act = await http_client.post(
        f"/api/v1/schedule/schedules/{c_schedule_id}/activities/",
        json={"name": "C own work", "start_date": "2026-05-04", "end_date": "2026-05-08", "activity_type": "task"},
        headers=c_headers,
    )
    assert act.status_code == 201, act.text
    return {
        "headers": c_headers,
        "schedule_id": c_schedule_id,
        "activity_id": act.json()["id"],
        "a_boq_id": a_boq_id,
    }


async def _names_in(http_client, schedule_id: str, headers: dict[str, str]) -> list[str]:
    resp = await http_client.get(f"/api/v1/schedule/schedules/{schedule_id}/gantt/", headers=headers)
    assert resp.status_code == 200, resp.text
    return [a["name"] for a in resp.json()["activities"]]


@pytest.mark.asyncio
async def test_two_generations_at_once_write_one_plan(http_client, editor_with_own_schedule):
    """Two generate requests racing on one schedule must not both write a plan."""
    from app.database import async_session_factory
    from app.modules.boq.models import BOQ, Position

    c = editor_with_own_schedule
    own = await http_client.get(f"/api/v1/schedule/schedules/{c['schedule_id']}", headers=c["headers"])
    assert own.status_code == 200, own.text
    project_id = own.json()["project_id"]
    async with async_session_factory() as s:
        boq = BOQ(project_id=uuid.UUID(project_id), name="C bill")
        s.add(boq)
        await s.flush()
        for i in range(3):
            s.add(
                Position(
                    boq_id=boq.id,
                    parent_id=None,
                    ordinal=f"0{i + 1}",
                    description=f"C work {i}",
                    unit="m2",
                    quantity="50",
                    unit_rate="20",
                    total="1000",
                    metadata_={},
                    sort_order=i + 1,
                )
            )
        await s.commit()
        boq_id = str(boq.id)
    sched = await http_client.post(
        "/api/v1/schedule/schedules/",
        json={"project_id": project_id, "name": "C race", "start_date": "2026-05-04"},
        headers=c["headers"],
    )
    assert sched.status_code == 201, sched.text
    sid = sched.json()["id"]
    url = f"/api/v1/schedule/schedules/{sid}/generate-from-boq/"

    async def _count() -> int:
        listed = await http_client.get(f"/api/v1/schedule/schedules/{sid}/gantt/", headers=c["headers"])
        assert listed.status_code == 200, listed.text
        return listed.json()["summary"]["total_activities"]

    first, second = await asyncio.gather(
        *(http_client.post(url, json={"boq_id": boq_id}, headers=c["headers"]) for _ in range(2))
    )
    assert sorted([first.status_code, second.status_code]) == [201, 409], (first.text, second.text)
    written = next(r for r in (first, second) if r.status_code == 201).json()
    assert await _count() == len(written)

    replaced = await asyncio.gather(
        *(http_client.post(url, json={"boq_id": boq_id, "replace": True}, headers=c["headers"]) for _ in range(2))
    )
    assert [r.status_code for r in replaced] == [201, 201]
    assert await _count() == len(written), "two replaces at once must leave one plan, not two"


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_editor_cannot_generate_from_another_tenants_boq(http_client, editor_with_own_schedule):
    c = editor_with_own_schedule
    resp = await http_client.post(
        f"/api/v1/schedule/schedules/{c['schedule_id']}/generate-from-boq/",
        json={"boq_id": c["a_boq_id"], "replace": True},
        headers=c["headers"],
    )
    assert resp.status_code == 404, f"COPY-IDOR: C generated from A's BOQ: {resp.status_code} {resp.text!r}"
    assert resp.json()["detail"]["error"] == "boq_not_found"
    names = await _names_in(http_client, c["schedule_id"], c["headers"])
    assert not any("secret" in n for n in names), names
    assert "C own work" in names, "a refused generation must leave the schedule as it was"


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_editor_cannot_preview_another_tenants_boq(http_client, editor_with_own_schedule):
    # The preview answers with per-position notes, descriptions included, so
    # it is a read of the bill and gets the same check as the generation.
    c = editor_with_own_schedule
    resp = await http_client.post(
        f"/api/v1/schedule/schedules/{c['schedule_id']}/generate-from-boq/preview/",
        json={"boq_id": c["a_boq_id"]},
        headers=c["headers"],
    )
    assert resp.status_code == 404, f"PREVIEW-IDOR: {resp.status_code} {resp.text!r}"
    assert "secret" not in resp.text
    assert resp.json()["detail"]["error"] == "boq_not_found"


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_editor_cannot_link_another_tenants_activity(http_client, two_schedule_tenants, editor_with_own_schedule):
    a = two_schedule_tenants["a"]
    c = editor_with_own_schedule
    for body in (
        {"predecessor_id": a["activity_id"], "successor_id": c["activity_id"]},
        {"predecessor_id": c["activity_id"], "successor_id": a["activity_id"]},
    ):
        resp = await http_client.post(
            f"/api/v1/schedule/schedules/{c['schedule_id']}/relationships/",
            json={**body, "relationship_type": "FS", "lag_days": 0},
            headers=c["headers"],
        )
        assert resp.status_code == 404, f"EDGE-IDOR: {resp.status_code} {resp.text!r}"
        assert resp.json()["detail"]["error"] == "schedule_activity_not_in_schedule"

    gantt = await http_client.get(f"/api/v1/schedule/schedules/{a['schedule_id']}/gantt/", headers=a["headers"])
    a_act = next(x for x in gantt.json()["activities"] if x["id"] == a["activity_id"])
    assert a_act["dependencies"] == [], "A's activity must not have been rewritten"


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_activity_edit_cannot_depend_on_another_tenants_activity(
    http_client, two_schedule_tenants, editor_with_own_schedule
):
    a = two_schedule_tenants["a"]
    c = editor_with_own_schedule
    resp = await http_client.patch(
        f"/api/v1/schedule/activities/{c['activity_id']}",
        json={"dependencies": [{"activity_id": a["activity_id"], "type": "FS", "lag_days": 0}]},
        headers=c["headers"],
    )
    assert resp.status_code == 404, f"EDGE-IDOR via activity edit: {resp.status_code} {resp.text!r}"
    assert resp.json()["detail"]["error"] == "schedule_activity_not_in_schedule"

    created = await http_client.post(
        f"/api/v1/schedule/schedules/{c['schedule_id']}/activities/",
        json={
            "name": "C linked work",
            "start_date": "2026-05-11",
            "end_date": "2026-05-15",
            "activity_type": "task",
            "dependencies": [{"activity_id": a["activity_id"], "type": "FS", "lag_days": 0}],
        },
        headers=c["headers"],
    )
    assert created.status_code == 404, f"EDGE-IDOR via activity create: {created.status_code} {created.text!r}"
