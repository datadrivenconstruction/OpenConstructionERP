"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Integration: CDE per-project settings + the go-live invite gate.

Exercises the setup-wizard persistence (GET/PATCH /v1/cde/settings) and the
go-live gate (GET /v1/cde/go-live) end to end through the public API, plus the
mass-invite gate on POST /v1/projects/{id}/members/bulk - the anti-"showroom"
protection that stops a team opening an unconfigured CDE to everyone.

Fixtures mirror the CDE readiness suite to avoid the login rate limiter.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app


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
    email = f"cde-gate-{unique}@test.io"
    password = f"CdeGate{unique}9"

    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "CDE Gate Tester"},
    )
    assert reg.status_code == 201, f"Registration failed: {reg.text}"

    from sqlalchemy import update as sa_update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(sa_update(User).where(User.email == email).values(role="admin", is_active=True))
        await s.commit()

    token = ""
    data: dict = {}
    for attempt in range(3):
        resp = await client.post(
            "/api/v1/users/auth/login",
            json={"email": email, "password": password},
        )
        data = resp.json()
        token = data.get("access_token", "")
        if token:
            break
        if "Too many login attempts" in data.get("detail", ""):
            await asyncio.sleep(5 * (attempt + 1))
            continue
        break
    assert token, f"Login failed after retries: {data}"
    return {"Authorization": f"Bearer {token}"}


async def _new_project(client: AsyncClient, auth: dict[str, str]) -> str:
    resp = await client.post(
        "/api/v1/projects/",
        json={"name": f"CDE Gate {uuid.uuid4().hex[:6]}", "currency": "EUR"},
        headers=auth,
    )
    assert resp.status_code == 201, f"Project create failed: {resp.text}"
    return resp.json()["id"]


async def _register_user() -> str:
    """Register an active user (no login needed) and return its id."""
    unique = uuid.uuid4().hex[:8]
    email = f"cde-invitee-{unique}@test.io"

    from sqlalchemy import select
    from sqlalchemy import update as sa_update

    from app.database import async_session_factory
    from app.modules.users.models import User

    # Register via the model layer to avoid the auth rate limiter entirely.
    from app.modules.users.service import hash_password

    async with async_session_factory() as s:
        user = User(
            email=email,
            hashed_password=hash_password("Invitee12345"),
            full_name="CDE Invitee",
            role="viewer",
            is_active=True,
        )
        s.add(user)
        await s.commit()
        await s.execute(sa_update(User).where(User.email == email).values(is_active=True))
        await s.commit()
        row = (await s.execute(select(User).where(User.email == email))).scalar_one()
        return str(row.id)


async def _drive_to_operational(client: AsyncClient, auth: dict[str, str], pid: str) -> None:
    """Create a shared container, two revisions, and publish with a signature.

    This lights up enough readiness signals to reach the 'operational' level
    (see test_cde_readiness_api.test_workflow_signals_light_up).
    """
    r = await client.post(
        "/api/v1/cde/containers/",
        json={
            "project_id": pid,
            "container_code": f"GATE-{uuid.uuid4().hex[:6]}",
            "title": "Gate workflow container",
            "cde_state": "shared",
        },
        headers=auth,
    )
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    for n in (1, 2):
        r = await client.post(
            f"/api/v1/cde/containers/{cid}/revisions/",
            json={"file_name": f"rev-{n}.pdf", "change_summary": f"rev {n}"},
            headers=auth,
        )
        assert r.status_code == 201, r.text
    r = await client.post(
        f"/api/v1/cde/containers/{cid}/transition/",
        json={
            "target_state": "published",
            "approver_signature": "Gate Tester",
            "approval_comments": "approved",
        },
        headers=auth,
    )
    assert r.status_code == 200, r.text


class TestCdeSettings:
    async def test_get_creates_defaults(self, client: AsyncClient, auth: dict[str, str]) -> None:
        pid = await _new_project(client, auth)
        r = await client.get(f"/api/v1/cde/settings/?project_id={pid}", headers=auth)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["project_id"] == pid
        assert body["suitability_set"] == "iso19650"
        assert body["go_live_gate_enabled"] is True
        assert body["min_readiness_level"] == "operational"
        assert body["setup_completed"] is False
        assert body["setup_step"] == 0
        assert body["role_assignments"] == {}

    async def test_patch_persists(self, client: AsyncClient, auth: dict[str, str]) -> None:
        pid = await _new_project(client, auth)
        author_id = str(uuid.uuid4())
        r = await client.patch(
            f"/api/v1/cde/settings/?project_id={pid}",
            json={
                "naming_convention": "Proj-Orig-Func-Spat-Form-Disc-Num",
                "review_preset_key": "cde_review_and_publish",
                "role_assignments": {"author": author_id},
                "min_readiness_level": "forming",
                "setup_completed": True,
                "setup_step": 4,
            },
            headers=auth,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["naming_convention"] == "Proj-Orig-Func-Spat-Form-Disc-Num"
        assert body["review_preset_key"] == "cde_review_and_publish"
        assert body["role_assignments"] == {"author": author_id}
        assert body["min_readiness_level"] == "forming"
        assert body["setup_completed"] is True
        assert body["setup_step"] == 4

        # Re-read: the update stuck.
        r = await client.get(f"/api/v1/cde/settings/?project_id={pid}", headers=auth)
        assert r.json()["setup_completed"] is True

    async def test_patch_rejects_unknown_role(self, client: AsyncClient, auth: dict[str, str]) -> None:
        pid = await _new_project(client, auth)
        r = await client.patch(
            f"/api/v1/cde/settings/?project_id={pid}",
            json={"role_assignments": {"chief": str(uuid.uuid4())}},
            headers=auth,
        )
        assert r.status_code == 422, r.text

    async def test_patch_rejects_unknown_level(self, client: AsyncClient, auth: dict[str, str]) -> None:
        pid = await _new_project(client, auth)
        r = await client.patch(
            f"/api/v1/cde/settings/?project_id={pid}",
            json={"min_readiness_level": "legendary"},
            headers=auth,
        )
        assert r.status_code == 422, r.text


class TestGoLiveGate:
    async def test_empty_project_blocks(self, client: AsyncClient, auth: dict[str, str]) -> None:
        pid = await _new_project(client, auth)
        r = await client.get(f"/api/v1/cde/go-live/?project_id={pid}", headers=auth)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["gate_enabled"] is True
        assert body["allowed"] is False
        assert body["level"] == "not_started"
        assert body["min_readiness_level"] == "operational"

    async def test_operational_project_allows(self, client: AsyncClient, auth: dict[str, str]) -> None:
        pid = await _new_project(client, auth)
        await _drive_to_operational(client, auth, pid)
        r = await client.get(f"/api/v1/cde/go-live/?project_id={pid}", headers=auth)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["level"] == "operational"
        assert body["allowed"] is True

    async def test_disabled_gate_allows_empty(self, client: AsyncClient, auth: dict[str, str]) -> None:
        pid = await _new_project(client, auth)
        r = await client.patch(
            f"/api/v1/cde/settings/?project_id={pid}",
            json={"go_live_gate_enabled": False},
            headers=auth,
        )
        assert r.status_code == 200, r.text
        r = await client.get(f"/api/v1/cde/go-live/?project_id={pid}", headers=auth)
        body = r.json()
        assert body["gate_enabled"] is False
        assert body["allowed"] is True


class TestBulkInviteGate:
    async def test_bulk_invite_blocked_on_unconfigured_cde(self, client: AsyncClient, auth: dict[str, str]) -> None:
        pid = await _new_project(client, auth)
        invitee = await _register_user()
        r = await client.post(
            f"/api/v1/projects/{pid}/members/bulk/",
            json={"members": [{"user_id": invitee, "role": "viewer"}]},
            headers=auth,
        )
        assert r.status_code == 409, r.text
        assert "go-live gate" in r.json()["detail"].lower()

    async def test_bulk_invite_allowed_after_operational(self, client: AsyncClient, auth: dict[str, str]) -> None:
        pid = await _new_project(client, auth)
        await _drive_to_operational(client, auth, pid)
        invitee = await _register_user()
        r = await client.post(
            f"/api/v1/projects/{pid}/members/bulk/",
            json={"members": [{"user_id": invitee, "role": "viewer"}]},
            headers=auth,
        )
        assert r.status_code == 201, r.text
        added = r.json()["added"]
        assert len(added) == 1
        assert added[0]["user_id"] == invitee

    async def test_bulk_invite_allowed_when_gate_disabled(self, client: AsyncClient, auth: dict[str, str]) -> None:
        pid = await _new_project(client, auth)
        await client.patch(
            f"/api/v1/cde/settings/?project_id={pid}",
            json={"go_live_gate_enabled": False},
            headers=auth,
        )
        invitee = await _register_user()
        r = await client.post(
            f"/api/v1/projects/{pid}/members/bulk/",
            json={"members": [{"user_id": invitee, "role": "viewer"}]},
            headers=auth,
        )
        assert r.status_code == 201, r.text
