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

Scaffolding mirrors ``test_reporting_idor.py``: per-module temp SQLite
registered BEFORE any ``from app...`` import (see
``feedback_test_isolation.md``).
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

# ── Per-module SQLite isolation (must run BEFORE app imports) ──────────────
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-schedule-idor-"))
_TMP_DB = _TMP_DIR / "schedule_idor.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

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


@pytest.mark.asyncio
async def test_owner_can_still_list_activities(http_client, two_schedule_tenants):
    a = two_schedule_tenants["a"]
    resp = await http_client.get(
        f"/api/v1/schedule/schedules/{a['schedule_id']}/activities/",
        headers=a["headers"],
    )
    assert resp.status_code == 200, resp.text
    assert len(resp.json()) == 1


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
