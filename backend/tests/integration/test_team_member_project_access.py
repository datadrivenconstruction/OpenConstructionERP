"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Team-member project access regression suite.

Pins the access policy introduced in fix/user-access-management:
users added via ``add_project_member`` must be able to read the
projects and BOQs they were invited to, while uninvited users must
still receive 404 (not 403 — IDOR defence: keep "missing" and "denied"
indistinguishable, matching the ``verify_project_access`` convention).

Test scaffolding mirrors ``test_erp_chat_idor.py``: the SQLAlchemy engine
is bound to the conftest-provisioned PostgreSQL cluster before any test
module imports, so this suite runs against PostgreSQL.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Every test in this file has identity as the variable under test.
pytestmark = pytest.mark.tenant_isolation

# ── App fixture ────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    """Boot the FastAPI app once for the whole module."""
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()

    async with app.router.lifespan_context(app):
        from app.database import Base, engine

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ── Helpers ────────────────────────────────────────────────────────────────


async def _activate_user(email: str) -> None:
    """Force is_active=True so login works under admin-approve mode."""
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(is_active=True))
        await s.commit()


async def _set_role(email: str, role: str) -> None:
    """Set a user's platform role directly, ahead of the login that mints its token."""
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(role=role))
        await s.commit()


async def _register_and_login(
    client: AsyncClient, suffix: str, *, role: str | None = None
) -> tuple[str, dict[str, str]]:
    """Register a fresh user, activate, login. Returns (user_id, auth_headers).

    ``role`` promotes the account before the token is issued, so the role
    claim in the JWT is the promoted one. Self-registration hands out
    ``viewer``, and only the very first account in the database gets ``admin``
    from the bootstrap path. This module shares its database with every other
    module in the shard, so an actor that needs write permissions has to ask
    for them instead of hoping it registered first.
    """
    email = f"user-{suffix}-{uuid.uuid4().hex[:6]}@team-access.io"
    password = f"TeamAccess{uuid.uuid4().hex[:6]}9!"

    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": f"User {suffix}"},
    )
    assert reg.status_code in (200, 201), f"register failed: {reg.text}"
    user_id = reg.json()["id"]

    await _activate_user(email)
    if role is not None:
        await _set_role(email, role)

    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, f"login failed: {login.text}"
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    return user_id, headers


# ── Shared fixture: A owns a project + BOQ, B is invited, C is not ─────────


@pytest_asyncio.fixture(scope="module")
async def scenario(http_client):
    """
    A creates a project and a BOQ.
    A adds B as a project member.
    C is a separate user with no connection to the project.

    Only A is promoted. B and C stay on the ``viewer`` role that
    self-registration hands out, which is the whole point of the suite: B is
    reaching the project through its membership and C must be reaching
    nothing at all.
    """
    a_id, a_headers = await _register_and_login(http_client, "A", role="admin")
    b_id, b_headers = await _register_and_login(http_client, "B")
    _, c_headers = await _register_and_login(http_client, "C")

    # A creates a project
    proj_resp = await http_client.post(
        "/api/v1/projects/",
        json={"name": "Test Project", "currency": "EUR"},
        headers=a_headers,
    )
    assert proj_resp.status_code in (200, 201), f"create project failed: {proj_resp.text}"
    project_id = proj_resp.json()["id"]

    # A adds B as a team member
    add_resp = await http_client.post(
        f"/api/v1/projects/{project_id}/members/",
        json={"user_id": b_id, "role": "viewer"},
        headers=a_headers,
    )
    assert add_resp.status_code in (200, 201), f"add member failed: {add_resp.text}"

    # A creates a BOQ in the project
    boq_resp = await http_client.post(
        "/api/v1/boq/boqs/",
        json={"project_id": project_id, "name": "Main BOQ"},
        headers=a_headers,
    )
    assert boq_resp.status_code in (200, 201), f"create BOQ failed: {boq_resp.text}"
    boq_id = boq_resp.json()["id"]

    return {
        "project_id": project_id,
        "boq_id": boq_id,
        "a_headers": a_headers,
        "b_headers": b_headers,
        "c_headers": c_headers,
    }


# ── Tests ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_team_member_can_list_project(http_client, scenario):
    """B (team member) must see the project in GET /projects/."""
    resp = await http_client.get("/api/v1/projects/", headers=scenario["b_headers"])
    assert resp.status_code == 200
    # The endpoint answers with a bare list, not an envelope.
    ids = [p["id"] for p in resp.json()]
    assert scenario["project_id"] in ids, "team member's project missing from listing"


@pytest.mark.asyncio
async def test_team_member_can_get_project(http_client, scenario):
    """B can call GET /projects/{id}, /dashboard, /members/ without 4xx."""
    pid = scenario["project_id"]
    headers = scenario["b_headers"]

    get_resp = await http_client.get(f"/api/v1/projects/{pid}", headers=headers)
    assert get_resp.status_code == 200, f"GET project: {get_resp.text}"

    members_resp = await http_client.get(f"/api/v1/projects/{pid}/members/", headers=headers)
    assert members_resp.status_code == 200, f"GET members: {members_resp.text}"

    # The dashboard is registered with a trailing slash only, unlike the
    # project detail above, which carries both spellings.
    dash_resp = await http_client.get(f"/api/v1/projects/{pid}/dashboard/", headers=headers)
    assert dash_resp.status_code == 200, f"GET dashboard: {dash_resp.text}"


@pytest.mark.asyncio
async def test_team_member_can_access_boq(http_client, scenario):
    """B can read BOQs under the project."""
    boq_id = scenario["boq_id"]
    headers = scenario["b_headers"]

    list_resp = await http_client.get(f"/api/v1/boq/boqs/?project_id={scenario['project_id']}", headers=headers)
    assert list_resp.status_code == 200, f"list BOQs: {list_resp.text}"

    get_resp = await http_client.get(f"/api/v1/boq/boqs/{boq_id}", headers=headers)
    assert get_resp.status_code == 200, f"GET BOQ: {get_resp.text}"


@pytest.mark.asyncio
async def test_uninvolved_user_still_404_via_verify_project_access(http_client, scenario):
    """C (no membership) must receive 404 — not 403 — to prevent UUID-oracle attacks."""
    pid = scenario["project_id"]
    headers = scenario["c_headers"]

    get_resp = await http_client.get(f"/api/v1/projects/{pid}", headers=headers)
    assert get_resp.status_code == 404, f"Expected 404 for uninvolved user (IDOR defence), got {get_resp.status_code}"


@pytest.mark.asyncio
async def test_member_dashboard_cards_includes_member_projects(http_client, scenario):
    """B's dashboard_cards response must include the project A invited them to.

    The route is ``/dashboard/cards/``. Asking for ``/dashboard-cards`` puts
    the whole word in the ``{project_id}`` slot, so the reply is a UUID
    parse error rather than anything about access.
    """
    resp = await http_client.get("/api/v1/projects/dashboard/cards/", headers=scenario["b_headers"])
    assert resp.status_code == 200, f"dashboard-cards failed: {resp.text}"
    ids = [p.get("id") or p.get("project_id") for p in resp.json()]
    assert scenario["project_id"] in ids, "invited project missing from team member's dashboard cards"
