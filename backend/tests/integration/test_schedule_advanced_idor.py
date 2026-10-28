"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Schedule Advanced (LPS) HTTP-level IDOR regression suite.

``tests/modules/test_schedule_advanced_security.py`` proves the resolver
helpers + ``verify_project_access`` reject cross-tenant access, but it does so
with in-memory stubs and never boots the FastAPI app. This suite drives the
real ``/api/v1/schedule-advanced/`` routes end to end - real registration,
login, RBAC, the throwaway PostgreSQL DB and the parent->project resolver
chains - so an accidental drop of a ``verify_project_access`` call on any of
these endpoints is caught at the boundary a client actually hits.

The module mounts at the kebab prefix ``/api/v1/schedule-advanced`` (the
loader's ``oe_schedule_advanced`` -> ``schedule-advanced`` convention).

Convention (matches ``dependencies.verify_project_access``): cross-tenant
access returns **404**, never a 2xx and never a 403, so the endpoint can't be
turned into a UUID-existence oracle.

Scaffolding mirrors ``test_schedule_idor.py``: the engine is bound to the
shared PostgreSQL cluster by ``conftest.py`` before any ``from app...`` import.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Every test in this file has identity as the variable under test.
pytestmark = pytest.mark.tenant_isolation

# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()

    async with app.router.lifespan_context(app):
        from app.database import Base, engine
        from app.modules.schedule_advanced import models as _sa_models  # noqa: F401

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


async def _register_and_login(client: AsyncClient, *, tenant: str) -> tuple[str, str, str, dict[str, str]]:
    email = f"{tenant}-{uuid.uuid4().hex[:8]}@sa-idor.io"
    password = f"SaIdor{uuid.uuid4().hex[:6]}9"

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
    return user_id, email, password, {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest_asyncio.fixture(scope="module")
async def two_lps_tenants(http_client):
    """A owns a project + master schedule + phase plan; B is the attacker."""
    a_uid, a_email, a_password, _a_headers = await _register_and_login(http_client, tenant="a")
    b_uid, b_email, _b_password, b_headers = await _register_and_login(http_client, tenant="b")

    # Promote A to admin so they can create projects (new accounts are viewers
    # and lack projects.create + schedule_advanced.create). B stays a viewer.
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
            "name": f"LPS-A {uuid.uuid4().hex[:6]}",
            "description": "owned by A - used by schedule_advanced IDOR tests",
            "currency": "EUR",
        },
        headers=a_headers,
    )
    assert proj.status_code == 201, f"project create failed: {proj.text}"
    project_id = proj.json()["id"]

    ms = await http_client.post(
        "/api/v1/schedule-advanced/master-schedules/",
        json={"project_id": project_id, "name": "A confidential master schedule"},
        headers=a_headers,
    )
    assert ms.status_code == 201, f"master-schedule create failed: {ms.text}"
    master_id = ms.json()["id"]

    phase = await http_client.post(
        "/api/v1/schedule-advanced/phase-plans/",
        json={"master_schedule_id": master_id, "name": "A secret foundation phase"},
        headers=a_headers,
    )
    assert phase.status_code == 201, f"phase-plan create failed: {phase.text}"
    phase_id = phase.json()["id"]

    return {
        "a": {
            "headers": a_headers,
            "project_id": project_id,
            "master_id": master_id,
            "phase_id": phase_id,
        },
        "b": {"user_id": b_uid, "email": b_email, "headers": b_headers},
    }


# ── Read-leak vectors ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tenant_b_cannot_read_master_schedule(http_client, two_lps_tenants):
    a = two_lps_tenants["a"]
    b = two_lps_tenants["b"]

    resp = await http_client.get(
        f"/api/v1/schedule-advanced/master-schedules/{a['master_id']}",
        headers=b["headers"],
    )
    assert resp.status_code == 404, f"LEAK: B read A's master schedule: {resp.status_code} {resp.text!r}"
    assert "confidential master" not in resp.text


@pytest.mark.asyncio
async def test_tenant_b_cannot_list_master_schedules_for_as_project(http_client, two_lps_tenants):
    """Listing is keyed off ``project_id`` - B must be 404'd on A's project."""
    a = two_lps_tenants["a"]
    b = two_lps_tenants["b"]

    resp = await http_client.get(
        f"/api/v1/schedule-advanced/master-schedules/?project_id={a['project_id']}",
        headers=b["headers"],
    )
    assert resp.status_code == 404, f"LEAK: B listed A's master schedules: {resp.status_code} {resp.text!r}"
    assert "confidential master" not in resp.text


@pytest.mark.asyncio
async def test_tenant_b_cannot_list_phase_plans(http_client, two_lps_tenants):
    """Nested resolver chain: phase-plans list resolves master -> project."""
    a = two_lps_tenants["a"]
    b = two_lps_tenants["b"]

    resp = await http_client.get(
        f"/api/v1/schedule-advanced/phase-plans/?master_schedule_id={a['master_id']}",
        headers=b["headers"],
    )
    assert resp.status_code == 404, f"LEAK: B listed A's phase plans: {resp.status_code} {resp.text!r}"
    assert "secret foundation" not in resp.text


@pytest.mark.asyncio
async def test_tenant_b_cannot_read_phase_plan(http_client, two_lps_tenants):
    a = two_lps_tenants["a"]
    b = two_lps_tenants["b"]

    resp = await http_client.get(
        f"/api/v1/schedule-advanced/phase-plans/{a['phase_id']}",
        headers=b["headers"],
    )
    assert resp.status_code == 404, f"LEAK: B read A's phase plan: {resp.status_code} {resp.text!r}"
    assert "secret foundation" not in resp.text


@pytest.mark.asyncio
async def test_tenant_b_cannot_read_master_dashboard(http_client, two_lps_tenants):
    a = two_lps_tenants["a"]
    b = two_lps_tenants["b"]

    resp = await http_client.get(
        f"/api/v1/schedule-advanced/master-schedules/{a['master_id']}/dashboard",
        headers=b["headers"],
    )
    assert resp.status_code == 404, f"LEAK: B read A's LPS dashboard: {resp.status_code} {resp.text!r}"


# ── Write IDOR vectors ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tenant_b_cannot_create_phase_plan_on_as_master(http_client, two_lps_tenants):
    """Nested create must resolve the master's project BEFORE writing.

    B (a viewer) is rejected; whether the gate trips on RBAC or the
    cross-tenant resolver, it must never be a 2xx and must never write a row
    into A's master schedule.
    """
    a = two_lps_tenants["a"]
    b = two_lps_tenants["b"]

    resp = await http_client.post(
        "/api/v1/schedule-advanced/phase-plans/",
        json={"master_schedule_id": a["master_id"], "name": "B injected phase"},
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), f"WRITE-IDOR: B wrote into A's master: {resp.status_code} {resp.text!r}"


@pytest.mark.asyncio
async def test_tenant_b_cannot_delete_master_schedule(http_client, two_lps_tenants):
    a = two_lps_tenants["a"]
    b = two_lps_tenants["b"]

    resp = await http_client.delete(
        f"/api/v1/schedule-advanced/master-schedules/{a['master_id']}",
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), f"WRITE-IDOR: B deleted A's master: {resp.status_code} {resp.text!r}"

    # And A's master must still exist afterwards.
    still = await http_client.get(
        f"/api/v1/schedule-advanced/master-schedules/{a['master_id']}",
        headers=a["headers"],
    )
    assert still.status_code == 200, f"A's master schedule was wrongly removed: {still.text}"


@pytest.mark.asyncio
async def test_unknown_master_id_404s_not_500(http_client, two_lps_tenants):
    """A nested resource that doesn't exist must 404 cleanly (no oracle / no 500)."""
    a = two_lps_tenants["a"]
    resp = await http_client.get(
        f"/api/v1/schedule-advanced/master-schedules/{uuid.uuid4()}",
        headers=a["headers"],
    )
    assert resp.status_code == 404, resp.text


# ── Regression guards: the owner must still have access ────────────────────


@pytest.mark.asyncio
async def test_owner_can_still_read_master_schedule(http_client, two_lps_tenants):
    a = two_lps_tenants["a"]
    resp = await http_client.get(
        f"/api/v1/schedule-advanced/master-schedules/{a['master_id']}",
        headers=a["headers"],
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "A confidential master schedule"


@pytest.mark.asyncio
async def test_owner_can_still_list_phase_plans(http_client, two_lps_tenants):
    a = two_lps_tenants["a"]
    resp = await http_client.get(
        f"/api/v1/schedule-advanced/phase-plans/?master_schedule_id={a['master_id']}",
        headers=a["headers"],
    )
    assert resp.status_code == 200, resp.text
    names = {p["name"] for p in resp.json()}
    assert "A secret foundation phase" in names


# ── Delay-analysis cross-tenant schedule_id (forensic delay engine) ─────────


@pytest.mark.asyncio
async def test_delay_analysis_rejects_cross_tenant_schedule_id(http_client):
    """A forensic delay analysis must not target another tenant's schedule.

    ``create_delay_analysis`` verifies access to the ``project_id`` query param
    but used to store the body's ``schedule_id`` without checking it belonged to
    that project. ``/compute`` and ``/auto-fragnet`` then read that schedule's
    activities + relationships, leaking another tenant's network. The create
    must 404 (not 403, not 201) when ``schedule_id`` is foreign.
    """
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    # Two independent admins - each needs create rights in their OWN project.
    _a_uid, a_email, a_pw, _a_h = await _register_and_login(http_client, tenant="dla-a")
    _b_uid, b_email, b_pw, _b_h = await _register_and_login(http_client, tenant="dla-b")
    async with async_session_factory() as s:
        await s.execute(
            update(User).where(User.email.in_([a_email.lower(), b_email.lower()])).values(role="admin", is_active=True)
        )
        await s.commit()

    async def _admin_headers(email: str, password: str) -> dict[str, str]:
        login = await http_client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
        assert login.status_code == 200, login.text
        return {"Authorization": f"Bearer {login.json()['access_token']}"}

    a_headers = await _admin_headers(a_email, a_pw)
    b_headers = await _admin_headers(b_email, b_pw)

    # A owns a project + a confidential schedule (the exfiltration target).
    a_proj = await http_client.post(
        "/api/v1/projects/",
        json={"name": f"DLA-A {uuid.uuid4().hex[:6]}", "description": "A", "currency": "EUR"},
        headers=a_headers,
    )
    assert a_proj.status_code == 201, a_proj.text
    a_project_id = a_proj.json()["id"]

    a_sched = await http_client.post(
        "/api/v1/schedule/schedules/",
        json={"project_id": a_project_id, "name": "A confidential schedule"},
        headers=a_headers,
    )
    assert a_sched.status_code == 201, f"schedule create failed: {a_sched.text}"
    a_schedule_id = a_sched.json()["id"]

    # B owns their own project.
    b_proj = await http_client.post(
        "/api/v1/projects/",
        json={"name": f"DLA-B {uuid.uuid4().hex[:6]}", "description": "B", "currency": "EUR"},
        headers=b_headers,
    )
    assert b_proj.status_code == 201, b_proj.text
    b_project_id = b_proj.json()["id"]

    # B creates a delay analysis in their OWN project but points schedule_id at
    # A's schedule -> must be rejected at create.
    attack = await http_client.post(
        f"/api/v1/schedule-advanced/delay-analyses?project_id={b_project_id}",
        json={"name": "B exfil", "method": "tia", "schedule_id": a_schedule_id},
        headers=b_headers,
    )
    assert attack.status_code == 404, (
        f"IDOR: B targeted A's schedule in a delay analysis: {attack.status_code} {attack.text!r}"
    )
    assert "confidential" not in attack.text

    # Regression guard: B can still create a delay analysis with no foreign
    # schedule (schedule_id omitted).
    ok = await http_client.post(
        f"/api/v1/schedule-advanced/delay-analyses?project_id={b_project_id}",
        json={"name": "B own analysis", "method": "tia"},
        headers=b_headers,
    )
    assert ok.status_code == 201, f"owner create regressed: {ok.text}"
