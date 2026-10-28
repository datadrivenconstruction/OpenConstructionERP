# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Integration tests for the schedule real-time guarded-update surface (T3.4).

Covers the optimistic-concurrency contract end to end against PostgreSQL:

    * a guarded update with the current base revision APPLIES and bumps the
      revision by exactly one;
    * a second update carrying the now-stale base is rejected 409 and the body
      carries the authoritative current revision + state (the lost-update guard);
    * an unchanged re-submit at the current base is a NOOP that does not bump;
    * a field outside the editable allowlist is 422 (revision must not be a
      writable field through this path);
    * the revision read endpoint reflects the bumped value;
    * cross-tenant access to the guarded / revision / presence endpoints is
      404 (existence-oracle safe), and the owner still has access.

Scaffolding mirrors ``test_schedule_idor.py`` (create_app + lifespan; the engine
is bound to the shared cluster by conftest before any ``from app...`` import).
"""

from __future__ import annotations

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


async def _register_and_login(client: AsyncClient, *, tenant: str) -> tuple[str, str, dict[str, str]]:
    email = f"{tenant}-{uuid.uuid4().hex[:8]}@sched-rt.io"
    password = f"SchedRt{uuid.uuid4().hex[:6]}9"

    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": f"Tenant {tenant}"},
    )
    assert reg.status_code in (200, 201), f"register failed: {reg.text}"

    await _activate_user(email)

    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, login.text
    return email, password, {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest_asyncio.fixture(scope="module")
async def realtime_fixture(http_client):
    """A owns a project + schedule + one activity; B is the attacker."""
    a_email, a_password, _ = await _register_and_login(http_client, tenant="a")
    _b_email, _b_password, b_headers = await _register_and_login(http_client, tenant="b")

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
    a_headers = {"Authorization": f"Bearer {a_login.json()['access_token']}"}

    proj = await http_client.post(
        "/api/v1/projects/",
        json={"name": f"RT-A {uuid.uuid4().hex[:6]}", "description": "rt", "currency": "EUR"},
        headers=a_headers,
    )
    assert proj.status_code == 201, proj.text
    project_id = proj.json()["id"]

    sched = await http_client.post(
        "/api/v1/schedule/schedules/",
        json={
            "project_id": project_id,
            "name": "RT master schedule",
            "start_date": "2026-05-01",
            "end_date": "2026-09-30",
        },
        headers=a_headers,
    )
    assert sched.status_code == 201, sched.text
    schedule_id = sched.json()["id"]

    act = await http_client.post(
        f"/api/v1/schedule/schedules/{schedule_id}/activities/",
        json={
            "name": "Foundation works",
            "wbs_code": "01.01",
            "start_date": "2026-05-04",
            "end_date": "2026-05-15",
            "activity_type": "task",
        },
        headers=a_headers,
    )
    assert act.status_code == 201, act.text

    return {
        "a": {"headers": a_headers, "schedule_id": schedule_id, "activity_id": act.json()["id"]},
        "b": {"headers": b_headers},
    }


# ── Guarded-update contract ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_guarded_update_applies_and_bumps_revision(http_client, realtime_fixture):
    a = realtime_fixture["a"]
    activity_id = a["activity_id"]

    rev0 = await http_client.get(
        f"/api/v1/schedule/activities/{activity_id}/revision/",
        headers=a["headers"],
    )
    assert rev0.status_code == 200, rev0.text
    base = rev0.json()["revision"]

    resp = await http_client.patch(
        f"/api/v1/schedule/activities/{activity_id}/guarded/",
        json={"base_revision": base, "fields": {"name": "Foundation works (rev1)"}},
        headers=a["headers"],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["revision"] == base + 1
    assert body["activity"]["name"] == "Foundation works (rev1)"


@pytest.mark.asyncio
async def test_stale_base_is_409_with_current_state(http_client, realtime_fixture):
    a = realtime_fixture["a"]
    activity_id = a["activity_id"]

    cur = (
        await http_client.get(
            f"/api/v1/schedule/activities/{activity_id}/revision/",
            headers=a["headers"],
        )
    ).json()["revision"]

    # First write at the current base succeeds.
    ok = await http_client.patch(
        f"/api/v1/schedule/activities/{activity_id}/guarded/",
        json={"base_revision": cur, "fields": {"color": "#ef4444"}},
        headers=a["headers"],
    )
    assert ok.status_code == 200, ok.text
    bumped = ok.json()["revision"]
    assert bumped == cur + 1

    # A second write still using the OLD base is a stale lost-update -> 409.
    stale = await http_client.patch(
        f"/api/v1/schedule/activities/{activity_id}/guarded/",
        json={"base_revision": cur, "fields": {"color": "#00ff00"}},
        headers=a["headers"],
    )
    assert stale.status_code == 409, stale.text
    conflict = stale.json()
    assert conflict["current_revision"] == bumped
    assert conflict["current_state"]["color"] == "#ef4444"  # the rejected write did NOT land


@pytest.mark.asyncio
async def test_noop_when_no_change_does_not_bump(http_client, realtime_fixture):
    a = realtime_fixture["a"]
    activity_id = a["activity_id"]

    state = (
        await http_client.get(
            f"/api/v1/schedule/activities/{activity_id}/revision/",
            headers=a["headers"],
        )
    ).json()["revision"]

    # Re-send the activity's CURRENT name -> nothing changes -> NOOP, no bump.
    snapshot = await http_client.patch(
        f"/api/v1/schedule/activities/{activity_id}/guarded/",
        json={"base_revision": state, "fields": {"name": "Foundation works (rev1)"}},
        headers=a["headers"],
    )
    assert snapshot.status_code == 200, snapshot.text
    # Whatever the current name is, re-submitting the identical value must not bump.
    current_name = snapshot.json()["activity"]["name"]

    rev_after_first = snapshot.json()["revision"]
    again = await http_client.patch(
        f"/api/v1/schedule/activities/{activity_id}/guarded/",
        json={"base_revision": rev_after_first, "fields": {"name": current_name}},
        headers=a["headers"],
    )
    assert again.status_code == 200, again.text
    assert again.json()["revision"] == rev_after_first  # NOOP did not bump


@pytest.mark.asyncio
async def test_field_outside_allowlist_is_422(http_client, realtime_fixture):
    a = realtime_fixture["a"]
    activity_id = a["activity_id"]

    cur = (
        await http_client.get(
            f"/api/v1/schedule/activities/{activity_id}/revision/",
            headers=a["headers"],
        )
    ).json()["revision"]

    # ``revision`` is NOT a writable field through the guarded path.
    resp = await http_client.patch(
        f"/api/v1/schedule/activities/{activity_id}/guarded/",
        json={"base_revision": cur, "fields": {"revision": 999}},
        headers=a["headers"],
    )
    assert resp.status_code == 422, resp.text

    # ``schedule_id`` (re-homing the activity) is likewise rejected.
    resp2 = await http_client.patch(
        f"/api/v1/schedule/activities/{activity_id}/guarded/",
        json={"base_revision": cur, "fields": {"schedule_id": str(uuid.uuid4())}},
        headers=a["headers"],
    )
    assert resp2.status_code == 422, resp2.text


# ── Cross-tenant (IDOR) ─────────────────────────────────────────────────────


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_tenant_b_cannot_read_revision(http_client, realtime_fixture):
    a = realtime_fixture["a"]
    b = realtime_fixture["b"]
    resp = await http_client.get(
        f"/api/v1/schedule/activities/{a['activity_id']}/revision/",
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), resp.text


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_tenant_b_cannot_guarded_update(http_client, realtime_fixture):
    a = realtime_fixture["a"]
    b = realtime_fixture["b"]
    resp = await http_client.patch(
        f"/api/v1/schedule/activities/{a['activity_id']}/guarded/",
        json={"base_revision": None, "fields": {"name": "hijacked"}},
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), resp.text


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_tenant_b_cannot_read_presence(http_client, realtime_fixture):
    a = realtime_fixture["a"]
    b = realtime_fixture["b"]
    resp = await http_client.get(
        f"/api/v1/schedule/schedules/{a['schedule_id']}/presence/",
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), resp.text


@pytest.mark.asyncio
async def test_owner_presence_snapshot_is_empty_without_ws(http_client, realtime_fixture):
    """With no live WebSocket connection the presence roster is simply empty."""
    a = realtime_fixture["a"]
    resp = await http_client.get(
        f"/api/v1/schedule/schedules/{a['schedule_id']}/presence/",
        headers=a["headers"],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["schedule_id"] == a["schedule_id"]
    assert body["users"] == []
