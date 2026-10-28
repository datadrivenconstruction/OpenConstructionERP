# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A resource's dashboard shows only the bookings of projects the caller can reach.

Resources are a shared pool, so any reader may open any resource. Its
dashboard, though, listed every active and upcoming assignment of that
resource, and each assignment names its project, its window and its status.
A reader of one project could so read the bookings of projects they neither
own nor belong to. The assignment routes and the histogram beside them scope
to ``accessible_project_ids``; the dashboard did not.

B is a manager, not an admin, so the admin bypass cannot stand in for the
scope, and B's own resource is the control that the list is not just empty.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Every test in this file has identity as the variable under test.
pytestmark = pytest.mark.tenant_isolation

RESOURCES = "/api/v1/resources"


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
        from app.modules.resources import resource_depth_models as _depth_models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _set_user_fields(email: str, **values) -> None:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(**values))
        await s.commit()


async def _register_login_and_promote(
    client: AsyncClient,
    *,
    tenant: str,
    role: str,
) -> dict[str, str]:
    """Register a user, activate it, promote it, return its auth headers."""
    email = f"{tenant}-{uuid.uuid4().hex[:8]}@dashboard-idor.io"
    password = f"DashIdor{uuid.uuid4().hex[:6]}9"

    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": f"Tenant {tenant}"},
    )
    assert reg.status_code in (200, 201), reg.text

    await _set_user_fields(email, is_active=True, role=role)

    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _make_project_with_assignment(
    client: AsyncClient,
    headers: dict[str, str],
    label: str,
) -> dict[str, str]:
    """A project, a resource homed on it and one upcoming assignment, all owned by ``headers``."""
    proj = await client.post(
        "/api/v1/projects/",
        json={
            "name": f"Dash-{label} {uuid.uuid4().hex[:6]}",
            "description": f"owned by {label}, used by the dashboard IDOR suite",
            "currency": "EUR",
        },
        headers=headers,
    )
    assert proj.status_code == 201, proj.text
    project_id = proj.json()["id"]

    res = await client.post(
        f"{RESOURCES}/resources/",
        json={
            "code": f"RES-{uuid.uuid4().hex[:6].upper()}",
            "name": f"{label} crane crew",
            "resource_type": "person",
            "home_project_id": project_id,
            "default_cost_rate": "75.00",
            "currency": "EUR",
            "status": "active",
        },
        headers=headers,
    )
    assert res.status_code == 201, res.text

    assign = await client.post(
        f"{RESOURCES}/assignments/",
        json={
            "resource_id": res.json()["id"],
            "project_id": project_id,
            "start_at": "2027-06-01T08:00:00+00:00",
            "end_at": "2027-06-10T17:00:00+00:00",
            "allocation_percent": 100,
            "status": "proposed",
        },
        headers=headers,
    )
    assert assign.status_code == 201, assign.text
    return {"resource_id": res.json()["id"], "assignment_id": assign.json()["id"]}


@pytest_asyncio.fixture(scope="module")
async def two_tenants(http_client):
    """A owns an assignment; B is a manager with an assignment of its own."""
    a_headers = await _register_login_and_promote(http_client, tenant="a", role="admin")
    # B is a manager, not an admin: it clears ``resources.read`` and
    # ``resources.update`` so every probe reaches the project check, and it
    # misses the admin bypass inside ``verify_project_access``.
    b_headers = await _register_login_and_promote(http_client, tenant="b", role="manager")

    a_rows = await _make_project_with_assignment(http_client, a_headers, "A")
    b_rows = await _make_project_with_assignment(http_client, b_headers, "B")

    return {"a": {"headers": a_headers, **a_rows}, "b": {"headers": b_headers, **b_rows}}


def _assignment_ids(body: dict) -> set[str]:
    return {a["id"] for a in body["active_assignments"] + body["upcoming_assignments"]}


@pytest.mark.asyncio
async def test_b_does_not_see_a_bookings_on_a_shared_resource(http_client, two_tenants):
    a, b = two_tenants["a"], two_tenants["b"]
    resp = await http_client.get(f"{RESOURCES}/resources/{a['resource_id']}/dashboard", headers=b["headers"])
    assert resp.status_code == 200, resp.text
    assert a["assignment_id"] not in _assignment_ids(resp.json())


@pytest.mark.asyncio
async def test_b_still_sees_its_own_bookings(http_client, two_tenants):
    b = two_tenants["b"]
    resp = await http_client.get(f"{RESOURCES}/resources/{b['resource_id']}/dashboard", headers=b["headers"])
    assert resp.status_code == 200, resp.text
    assert b["assignment_id"] in _assignment_ids(resp.json())
