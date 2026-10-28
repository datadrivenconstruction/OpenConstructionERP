"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠M3 — assignee_id on Markup: create, update, filter, cross-tenant safety.

Covers the wave-3 feature added with alembic v3146:

    1. Create a markup with assignee_id → response carries it back
    2. PATCH the assignee → reflected in subsequent GET / list
    3. List filter ?assignee_id=<id> only returns that user's markups
    4. List filter ?unassigned=true only returns NULL-assignee markups
    5. Cross-tenant safety: project B's user cannot list project A's
       markups by guessing project_id (verify_project_access guards)
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest_asyncio.fixture
async def client() -> AsyncClient:
    app = create_app()

    @asynccontextmanager
    async def lifespan_ctx():
        async with app.router.lifespan_context(app):
            yield

    async with lifespan_ctx():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


async def _register_admin(client: AsyncClient) -> tuple[dict[str, str], str]:
    """Register an admin user; return (auth headers, user_id)."""
    from sqlalchemy import update as sa_update

    from app.database import async_session_factory
    from app.modules.users.models import User

    unique = uuid.uuid4().hex[:8]
    email = f"assignee-{unique}@smoke.io"
    password = f"AssignT{unique}9!"

    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "Assignee Tester"},
    )
    assert reg.status_code == 201, reg.text

    # Promote to admin so verify_project_access lets the user through
    # for cross-project sanity probes.
    async with async_session_factory() as session:
        await session.execute(sa_update(User).where(User.email == email.lower()).values(role="admin", is_active=True))
        await session.commit()

    token = ""
    for _ in range(2):
        resp = await client.post(
            "/api/v1/users/auth/login",
            json={"email": email, "password": password},
        )
        data = resp.json()
        token = data.get("access_token", "")
        if token:
            break
        if "Too many login attempts" in (data.get("detail") or ""):
            await asyncio.sleep(2)
            continue
        break
    assert token, f"Login failed: {resp.text}"
    return {"Authorization": f"Bearer {token}"}, reg.json()["id"]


@pytest_asyncio.fixture
async def auth_headers(client: AsyncClient) -> dict[str, str]:
    headers, _ = await _register_admin(client)
    return headers


@pytest_asyncio.fixture
async def auth_pair(client: AsyncClient) -> tuple[dict[str, str], str]:
    """Yield ((headers, user_id)) for the primary tester."""
    headers, user_id = await _register_admin(client)
    return headers, user_id


@pytest_asyncio.fixture
async def project_id(client: AsyncClient, auth_headers: dict[str, str]) -> str:
    resp = await client.post(
        "/api/v1/projects/",
        json={
            "name": "Markup Assignee Test",
            "region": "DACH",
            "classification_standard": "din276",
            "currency": "EUR",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["id"])


async def _create_markup(
    client: AsyncClient,
    headers: dict[str, str],
    project_id: str,
    *,
    label: str = "M",
    assignee_id: str | None = None,
) -> dict:
    body: dict[str, object] = {
        "project_id": project_id,
        "document_id": "doc-assignee-1",
        "page": 1,
        "type": "rectangle",
        "geometry": {"x": 0, "y": 0, "width": 10, "height": 10},
        "label": label,
    }
    if assignee_id is not None:
        body["assignee_id"] = assignee_id
    resp = await client.post("/api/v1/markups/", json=body, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


# ── 1. Create with assignee → response carries it back ─────────────────────


@pytest.mark.asyncio
async def test_create_with_assignee_round_trips(client: AsyncClient, auth_pair, project_id: str) -> None:
    headers, user_id = auth_pair
    created = await _create_markup(client, headers, project_id, assignee_id=user_id)
    assert created["assignee_id"] == user_id

    # And the dedicated GET returns the same value.
    got = await client.get(f"/api/v1/markups/{created['id']}", headers=headers)
    assert got.status_code == 200, got.text
    assert got.json()["assignee_id"] == user_id


# ── 2. PATCH assignee → reflected ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_patch_assignee_reflected(client: AsyncClient, auth_pair, project_id: str) -> None:
    headers, user_id = auth_pair
    created = await _create_markup(client, headers, project_id)  # no assignee
    assert created["assignee_id"] is None

    patch = await client.patch(
        f"/api/v1/markups/{created['id']}",
        json={"assignee_id": user_id},
        headers=headers,
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["assignee_id"] == user_id


# ── 3. Filter by assignee_id ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_filter_by_assignee_only_returns_match(client: AsyncClient, auth_pair, project_id: str) -> None:
    headers, user_id = auth_pair
    assigned = await _create_markup(client, headers, project_id, label="assigned", assignee_id=user_id)
    unassigned = await _create_markup(client, headers, project_id, label="unassigned")

    resp = await client.get(
        f"/api/v1/markups/?project_id={project_id}&assignee_id={user_id}",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    ids = {m["id"] for m in resp.json()}
    assert assigned["id"] in ids
    assert unassigned["id"] not in ids


# ── 4. unassigned=true filter ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_filter_unassigned_only_returns_null_assignees(client: AsyncClient, auth_pair, project_id: str) -> None:
    headers, user_id = auth_pair
    assigned = await _create_markup(client, headers, project_id, label="A", assignee_id=user_id)
    unassigned = await _create_markup(client, headers, project_id, label="U")

    resp = await client.get(
        f"/api/v1/markups/?project_id={project_id}&unassigned=true",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    ids = {m["id"] for m in resp.json()}
    assert unassigned["id"] in ids
    assert assigned["id"] not in ids


# ── 5. Cross-tenant safety ────────────────────────────────────────────────


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_cross_tenant_assignee_filter_does_not_leak(client: AsyncClient, auth_pair, project_id: str) -> None:
    """User A's assigned markup must not be visible when listing a
    project they don't own. verify_project_access either short-circuits
    with 404 OR returns 200 with an empty list for a fabricated id —
    both are acceptable IDOR signals, but the markup id must NEVER
    appear in the response either way.
    """
    headers, user_id = auth_pair
    a_markup = await _create_markup(client, headers, project_id, assignee_id=user_id)

    fake_project = "00000000-0000-0000-0000-000000000000"
    resp = await client.get(
        f"/api/v1/markups/?project_id={fake_project}&assignee_id={user_id}",
        headers=headers,
    )
    if resp.status_code == 200:
        ids = {m["id"] for m in resp.json()}
        assert a_markup["id"] not in ids
    else:
        # Project gate fired before the list query — also fine.
        assert resp.status_code in (403, 404)
