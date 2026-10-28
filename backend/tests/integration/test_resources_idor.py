"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Resources module IDOR regression suite.

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


async def _promote_to_manager(email: str) -> None:
    """Promote a user to manager via direct DB write.

    The attacker B is a *manager*, not a viewer: the assignment mutation
    endpoints require EDITOR/MANAGER permissions, so a viewer would be
    rejected at the RBAC layer (403) and never reach the project-access
    guard under test. A manager clears the permission gate but is NOT an
    admin, so ``verify_project_access`` still denies every project B does
    not own - proving the guard (not the permission layer) is what stops
    the cross-tenant access. Role is re-hydrated from the DB per request,
    so no re-login is needed for the new role to take effect.
    """
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(role="manager", is_active=True))
        await s.commit()


@pytest_asyncio.fixture(scope="module")
async def two_tenants(http_client):
    """A owns a project + resource + request + assignment; B is the attacker.

    B is promoted to *manager* and given their own project + resource +
    assignment. The manager role lets B clear the RBAC permission gate on
    the mutation endpoints (so the project-access guard is what must deny
    the cross-tenant calls), and owning a project lets B exercise the
    "move an assignment onto a foreign project" guard on PATCH.
    """
    a_uid, a_email, a_password, _a_headers0 = await _register_and_login(
        http_client,
        tenant="a",
    )
    b_uid, b_email, b_password, b_headers = await _register_and_login(
        http_client,
        tenant="b",
    )

    # A needs admin so they can create projects + resources (registration
    # drops new accounts to viewer; viewer cannot create resources).
    await _promote_to_admin(a_email)
    # B is a manager (not admin): high enough to pass the mutation RBAC gate,
    # not high enough to bypass verify_project_access. See _promote_to_manager.
    await _promote_to_manager(b_email)

    a_login = await http_client.post(
        "/api/v1/users/auth/login",
        json={"email": a_email, "password": a_password},
    )
    assert a_login.status_code == 200, a_login.text
    a_headers = {"Authorization": f"Bearer {a_login.json()['access_token']}"}

    # Re-login B so the manager role lands in the JWT too (role is also
    # re-hydrated from the DB per request, so this is belt-and-braces).
    b_login = await http_client.post(
        "/api/v1/users/auth/login",
        json={"email": b_email, "password": b_password},
    )
    assert b_login.status_code == 200, b_login.text
    b_headers = {"Authorization": f"Bearer {b_login.json()['access_token']}"}

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

    # A's confidential assignment (the by-id IDOR target).
    assign = await http_client.post(
        "/api/v1/resources/assignments/",
        json={
            "resource_id": resource_id,
            "project_id": project_id,
            "start_at": "2026-06-01T08:00:00+00:00",
            "end_at": "2026-06-10T17:00:00+00:00",
            "allocation_percent": 100,
            "status": "proposed",
            "notes": "secret-assignment-marker",
        },
        headers=a_headers,
    )
    assert assign.status_code == 201, f"assignment create failed: {assign.text}"
    assignment_id = assign.json()["id"]

    # B's OWN project + resource + assignment, used to exercise the PATCH
    # move-guard (B legitimately owns this assignment but must not be able to
    # re-home it onto A's project).
    b_proj = await http_client.post(
        "/api/v1/projects/",
        json={"name": f"Resources-B {uuid.uuid4().hex[:6]}", "currency": "EUR"},
        headers=b_headers,
    )
    assert b_proj.status_code == 201, f"B project create failed: {b_proj.text}"
    b_project_id = b_proj.json()["id"]

    b_res = await http_client.post(
        "/api/v1/resources/resources/",
        json={
            "code": f"RES-{uuid.uuid4().hex[:6].upper()}",
            "name": "B own worker",
            "resource_type": "person",
            "home_project_id": b_project_id,
            "default_cost_rate": "50.00",
            "currency": "EUR",
            "status": "active",
        },
        headers=b_headers,
    )
    assert b_res.status_code == 201, f"B resource create failed: {b_res.text}"
    b_resource_id = b_res.json()["id"]

    b_assign = await http_client.post(
        "/api/v1/resources/assignments/",
        json={
            "resource_id": b_resource_id,
            "project_id": b_project_id,
            "start_at": "2026-06-01T08:00:00+00:00",
            "end_at": "2026-06-10T17:00:00+00:00",
            "allocation_percent": 100,
            "status": "proposed",
        },
        headers=b_headers,
    )
    assert b_assign.status_code == 201, f"B assignment create failed: {b_assign.text}"
    b_assignment_id = b_assign.json()["id"]

    return {
        "a": {
            "headers": a_headers,
            "project_id": project_id,
            "resource_id": resource_id,
            "request_id": request_id,
            "assignment_id": assignment_id,
            "resource_code": rcode,
        },
        "b": {
            "user_id": b_uid,
            "email": b_email,
            "headers": b_headers,
            "project_id": b_project_id,
            "resource_id": b_resource_id,
            "assignment_id": b_assignment_id,
        },
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


# ── Assignment by-id IDOR vectors (regression for issue #29) ───────────────
#
# The by-id assignment endpoints (GET/PATCH/DELETE/confirm/complete/cancel)
# historically took only ``assignment_id`` + a permission gate and never
# verified the caller could access the assignment's project. B is a manager
# here, so these calls clear the RBAC gate and reach - and must be stopped
# by - the new ``verify_project_access`` guard.


@pytest.mark.asyncio
async def test_tenant_b_cannot_read_assignment_by_id(http_client, two_tenants):
    """``GET /assignments/{id}`` must NOT leak A's assignment."""
    a = two_tenants["a"]
    b = two_tenants["b"]

    resp = await http_client.get(
        f"/api/v1/resources/assignments/{a['assignment_id']}",
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), f"LEAK: B read A's assignment: {resp.status_code} {resp.text!r}"
    assert "secret-assignment-marker" not in resp.text


@pytest.mark.asyncio
async def test_tenant_b_cannot_patch_assignment(http_client, two_tenants):
    """``PATCH /assignments/{id}`` must reject A's assignment."""
    a = two_tenants["a"]
    b = two_tenants["b"]

    resp = await http_client.patch(
        f"/api/v1/resources/assignments/{a['assignment_id']}",
        json={"notes": "B-overwrote-A"},
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), f"WRITE-IDOR: B patched A's assignment: {resp.status_code} {resp.text!r}"


@pytest.mark.asyncio
async def test_tenant_b_cannot_delete_assignment(http_client, two_tenants):
    """``DELETE /assignments/{id}`` must reject A's assignment."""
    a = two_tenants["a"]
    b = two_tenants["b"]

    resp = await http_client.delete(
        f"/api/v1/resources/assignments/{a['assignment_id']}",
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), f"WRITE-IDOR: B deleted A's assignment: {resp.status_code} {resp.text!r}"


@pytest.mark.asyncio
async def test_tenant_b_cannot_confirm_assignment(http_client, two_tenants):
    """``POST /assignments/{id}/confirm`` must reject A's assignment."""
    a = two_tenants["a"]
    b = two_tenants["b"]

    resp = await http_client.post(
        f"/api/v1/resources/assignments/{a['assignment_id']}/confirm",
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), f"WRITE-IDOR: B confirmed A's assignment: {resp.status_code} {resp.text!r}"


@pytest.mark.asyncio
async def test_tenant_b_cannot_complete_assignment(http_client, two_tenants):
    """``POST /assignments/{id}/complete`` must reject A's assignment."""
    a = two_tenants["a"]
    b = two_tenants["b"]

    resp = await http_client.post(
        f"/api/v1/resources/assignments/{a['assignment_id']}/complete",
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), f"WRITE-IDOR: B completed A's assignment: {resp.status_code} {resp.text!r}"


@pytest.mark.asyncio
async def test_tenant_b_cannot_cancel_assignment(http_client, two_tenants):
    """``POST /assignments/{id}/cancel`` must reject A's assignment."""
    a = two_tenants["a"]
    b = two_tenants["b"]

    resp = await http_client.post(
        f"/api/v1/resources/assignments/{a['assignment_id']}/cancel?reason=x",
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), f"WRITE-IDOR: B cancelled A's assignment: {resp.status_code} {resp.text!r}"


@pytest.mark.asyncio
async def test_tenant_b_cannot_move_own_assignment_onto_a_project(http_client, two_tenants):
    """PATCH move-guard: B owns this assignment but must not re-home it onto A's project.

    Exercises the *second* guard branch in ``update_assignment`` - the caller
    clears the current-project check (B owns b_project) but the body-supplied
    ``project_id`` points at A's project, which B cannot access.
    """
    a = two_tenants["a"]
    b = two_tenants["b"]

    resp = await http_client.patch(
        f"/api/v1/resources/assignments/{b['assignment_id']}",
        json={"project_id": a["project_id"]},
        headers=b["headers"],
    )
    assert resp.status_code in (403, 404), (
        f"WRITE-IDOR: B moved own assignment onto A's project: {resp.status_code} {resp.text!r}"
    )


@pytest.mark.asyncio
async def test_tenant_b_can_update_own_assignment(http_client, two_tenants):
    """Positive control: the new guard must NOT block legitimate owner access."""
    b = two_tenants["b"]

    resp = await http_client.patch(
        f"/api/v1/resources/assignments/{b['assignment_id']}",
        json={"notes": "B edits own assignment"},
        headers=b["headers"],
    )
    assert resp.status_code == 200, f"REGRESSION: B blocked from own assignment: {resp.status_code} {resp.text!r}"
