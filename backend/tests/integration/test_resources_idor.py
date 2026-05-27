"""Resources module IDOR regression suite.

The ``/api/v1/resources/`` router exposes endpoints keyed off
``project_id`` for the resource-request and assignment flows, plus a
``GET /board/?project_id=...`` dispatcher view. Several endpoints
historically accepted an arbitrary ``project_id`` from the caller and
never verified that the user has access to that project, letting one
tenant create resource requests against another tenant's project or
enumerate that project's pending requests, assignments, and dispatcher
board.

Endpoints under test (all must reject cross-tenant access with 403/404,
never a 2xx — matching ``verify_project_access`` so endpoints can't be
turned into a UUID-existence oracle):

* ``GET  /resources/requests/?project_id=X``      — list-leak vector
* ``POST /resources/requests/``                   — write IDOR (body.project_id)
* ``GET  /resources/requests/{id}``               — read leak per-request
* ``PATCH /resources/requests/{id}``              — write IDOR per-request
* ``DELETE /resources/requests/{id}``             — write IDOR per-request
* ``POST /resources/requests/{id}/fulfill``       — write IDOR per-request
* ``POST /resources/assignments/``                — write IDOR (body.project_id)
* ``POST /resources/assignments/propose``         — write IDOR (body.project_id)
* ``GET  /resources/board/?project_id=X``         — list-leak vector

Convention: cross-tenant access returns **403/404**, never a 2xx.

Scaffolding mirrors ``test_schedule_idor.py``.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

# ── Per-module SQLite isolation (must run BEFORE app imports) ──────────────
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-resources-idor-"))
_TMP_DB = _TMP_DIR / "resources_idor.db"
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
        from app.modules.resources import models as _resources_models  # noqa: F401

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
    email = f"{tenant}-{uuid.uuid4().hex[:8]}@resources-idor.io"
    password = f"ResourcesIdor{uuid.uuid4().hex[:6]}9"

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


async def _promote_to_admin(email: str) -> None:
    """Promote a user to admin via direct DB write (registration → viewer)."""
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(role="admin", is_active=True))
        await s.commit()


@pytest_asyncio.fixture(scope="module")
async def two_tenants(http_client):
    """A owns a project + resource + request; B is the attacker."""
    a_uid, a_email, a_password, _a_headers0 = await _register_and_login(
        http_client,
        tenant="a",
    )
    b_uid, b_email, _b_password, b_headers = await _register_and_login(
        http_client,
        tenant="b",
    )

    # A needs admin so they can create projects + resources (registration
    # drops new accounts to viewer; viewer cannot create resources).
    await _promote_to_admin(a_email)

    a_login = await http_client.post(
        "/api/v1/users/auth/login",
        json={"email": a_email, "password": a_password},
    )
    assert a_login.status_code == 200, a_login.text
    a_headers = {"Authorization": f"Bearer {a_login.json()['access_token']}"}

    # A's confidential project
    proj = await http_client.post(
        "/api/v1/projects/",
        json={
            "name": f"Resources-A {uuid.uuid4().hex[:6]}",
            "description": "owned by A — used by resources IDOR tests",
            "currency": "EUR",
        },
        headers=a_headers,
    )
    assert proj.status_code == 201, f"project create failed: {proj.text}"
    project_id = proj.json()["id"]

    # A's resource (global catalogue but linked to A's project as home)
    rcode = f"RES-{uuid.uuid4().hex[:6].upper()}"
    res = await http_client.post(
        "/api/v1/resources/resources/",
        json={
            "code": rcode,
            "name": "A confidential foreman",
            "resource_type": "person",
            "home_project_id": project_id,
            "default_cost_rate": "75.00",
            "currency": "EUR",
            "status": "active",
        },
        headers=a_headers,
    )
    assert res.status_code == 201, f"resource create failed: {res.text}"
    resource_id = res.json()["id"]

    # A's resource request against A's project
    req = await http_client.post(
        "/api/v1/resources/requests/",
        json={
            "project_id": project_id,
            "title": "A confidential resource request",
            "description": "secret-payload-marker",
            "start_at": "2026-06-01T08:00:00+00:00",
            "end_at": "2026-06-10T17:00:00+00:00",
            "quantity": 1,
            "priority": "high",
        },
        headers=a_headers,
    )
    assert req.status_code == 201, f"request create failed: {req.text}"
    request_id = req.json()["id"]

    return {
        "a": {
            "headers": a_headers,
            "project_id": project_id,
            "resource_id": resource_id,
            "request_id": request_id,
            "resource_code": rcode,
        },
        "b": {"user_id": b_uid, "email": b_email, "headers": b_headers},
    }


# ── Read-leak vectors ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tenant_b_cannot_list_requests_for_a_project(http_client, two_tenants):
    """``GET /requests/?project_id=X`` must NOT leak A's resource requests."""
    a = two_tenants["a"]
    b = two_tenants["b"]

    resp = await http_client.get(
        f"/api/v1/resources/requests/?project_id={a['project_id']}",
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), f"LEAK: B listed A's resource requests: {resp.status_code} {resp.text!r}"
    assert "secret-payload-marker" not in resp.text
    assert "confidential resource request" not in resp.text


@pytest.mark.asyncio
async def test_tenant_b_cannot_read_request_by_id(http_client, two_tenants):
    """``GET /requests/{id}`` must NOT leak A's resource request."""
    a = two_tenants["a"]
    b = two_tenants["b"]

    resp = await http_client.get(
        f"/api/v1/resources/requests/{a['request_id']}",
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), f"LEAK: B read A's resource request: {resp.status_code} {resp.text!r}"
    assert "secret-payload-marker" not in resp.text


@pytest.mark.asyncio
async def test_tenant_b_cannot_view_board_for_a_project(http_client, two_tenants):
    """``GET /board/?project_id=X`` must NOT leak A's dispatcher board."""
    a = two_tenants["a"]
    b = two_tenants["b"]

    resp = await http_client.get(
        f"/api/v1/resources/board/?project_id={a['project_id']}"
        f"&start=2026-06-01T00:00:00%2B00:00&end=2026-07-01T00:00:00%2B00:00",
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), f"LEAK: B viewed A's dispatcher board: {resp.status_code} {resp.text!r}"
    assert "confidential foreman" not in resp.text


# ── Write IDOR vectors ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tenant_b_cannot_create_request_against_a_project(
    http_client,
    two_tenants,
):
    """``POST /requests/`` body must reject foreign project_id."""
    a = two_tenants["a"]
    b = two_tenants["b"]

    resp = await http_client.post(
        "/api/v1/resources/requests/",
        json={
            "project_id": a["project_id"],
            "title": "B's malicious request against A's project",
            "start_at": "2026-06-01T08:00:00+00:00",
            "end_at": "2026-06-10T17:00:00+00:00",
            "quantity": 1,
            "priority": "low",
        },
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), (
        f"WRITE-IDOR: B opened a request on A's project: {resp.status_code} {resp.text!r}"
    )


@pytest.mark.asyncio
async def test_tenant_b_cannot_patch_a_request(http_client, two_tenants):
    """``PATCH /requests/{id}`` must reject foreign request id."""
    a = two_tenants["a"]
    b = two_tenants["b"]

    resp = await http_client.patch(
        f"/api/v1/resources/requests/{a['request_id']}",
        json={"title": "B-overwrote-A"},
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), f"WRITE-IDOR: B patched A's request: {resp.status_code} {resp.text!r}"


@pytest.mark.asyncio
async def test_tenant_b_cannot_delete_a_request(http_client, two_tenants):
    """``DELETE /requests/{id}`` must reject foreign request id."""
    a = two_tenants["a"]
    b = two_tenants["b"]

    resp = await http_client.delete(
        f"/api/v1/resources/requests/{a['request_id']}",
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), f"WRITE-IDOR: B deleted A's request: {resp.status_code} {resp.text!r}"


@pytest.mark.asyncio
async def test_tenant_b_cannot_fulfill_a_request(http_client, two_tenants):
    """``POST /requests/{id}/fulfill`` must reject foreign request id."""
    a = two_tenants["a"]
    b = two_tenants["b"]

    resp = await http_client.post(
        f"/api/v1/resources/requests/{a['request_id']}/fulfill",
        json={
            "resource_id": a["resource_id"],
            "allocation_percent": 100,
            "cost_rate": "75.00",
            "currency": "EUR",
        },
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), f"WRITE-IDOR: B fulfilled A's request: {resp.status_code} {resp.text!r}"


@pytest.mark.asyncio
async def test_tenant_b_cannot_create_assignment_against_a_project(
    http_client,
    two_tenants,
):
    """``POST /assignments/`` body must reject foreign project_id."""
    a = two_tenants["a"]
    b = two_tenants["b"]

    resp = await http_client.post(
        "/api/v1/resources/assignments/",
        json={
            "resource_id": a["resource_id"],
            "project_id": a["project_id"],
            "start_at": "2026-06-01T08:00:00+00:00",
            "end_at": "2026-06-10T17:00:00+00:00",
            "allocation_percent": 100,
        },
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), (
        f"WRITE-IDOR: B created assignment on A's project: {resp.status_code} {resp.text!r}"
    )


@pytest.mark.asyncio
async def test_tenant_b_cannot_propose_assignment_against_a_project(
    http_client,
    two_tenants,
):
    """``POST /assignments/propose`` body must reject foreign project_id."""
    a = two_tenants["a"]
    b = two_tenants["b"]

    resp = await http_client.post(
        "/api/v1/resources/assignments/propose",
        json={
            "resource_id": a["resource_id"],
            "project_id": a["project_id"],
            "start_at": "2026-06-01T08:00:00+00:00",
            "end_at": "2026-06-10T17:00:00+00:00",
            "allocation_percent": 100,
        },
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), (
        f"WRITE-IDOR: B proposed assignment on A's project: {resp.status_code} {resp.text!r}"
    )
