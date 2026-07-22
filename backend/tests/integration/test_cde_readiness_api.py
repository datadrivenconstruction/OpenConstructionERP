"""Integration: CDE go-live readiness endpoint (GET /v1/cde/readiness).

Drives real data through the public API and checks the readiness score reflects
it - which exercises the aggregate repository SQL (mixed COUNT(*)/COUNT(col),
distinct states, the signed-transition join and the multi-revision HAVING) on
the test database, not just the pure engine.

Each test creates its OWN project because readiness is a project-level aggregate;
sharing one project would let tests interfere with each other's score.

Fixtures mirror the CDE transmittals suite to avoid the login rate limiter.
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
    email = f"cde-ready-{unique}@test.io"
    password = f"CdeReady{unique}9"

    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "CDE Readiness Tester"},
    )
    assert reg.status_code == 201, f"Registration failed: {reg.text}"

    from sqlalchemy import update as sa_update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(sa_update(User).where(User.email == email).values(role="admin", is_active=True))
        await s.commit()

    token = ""
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
        json={"name": f"CDE Readiness {uuid.uuid4().hex[:6]}", "currency": "EUR"},
        headers=auth,
    )
    assert resp.status_code == 201, f"Project create failed: {resp.text}"
    return resp.json()["id"]


def _signals(body: dict) -> dict[str, bool]:
    return {s["key"]: s["done"] for s in body["signals"]}


class TestCDEReadiness:
    async def test_empty_project_is_not_started(
        self, client: AsyncClient, auth: dict[str, str]
    ) -> None:
        pid = await _new_project(client, auth)
        r = await client.get(f"/api/v1/cde/readiness/?project_id={pid}", headers=auth)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["score"] == 0
        assert body["level"] == "not_started"
        assert body["total_containers"] == 0
        assert all(not done for done in _signals(body).values())
        # the nudge leads with creating the first container
        assert body["next_actions"][0]["key"] == "containers_created"

    async def test_metadata_signals_light_up(
        self, client: AsyncClient, auth: dict[str, str]
    ) -> None:
        pid = await _new_project(client, auth)
        # One WIP container carrying a structured name, suitability and class.
        r = await client.post(
            "/api/v1/cde/containers/",
            json={
                "project_id": pid,
                "container_code": f"OCE-XX-XX-M3-A-{uuid.uuid4().hex[:4]}",
                "title": "Readiness metadata container",
                "originator_code": "OCE",
                "suitability_code": "S0",
                "classification_code": "Ss_25_10_30",
                "classification_system": "uniclass",
            },
            headers=auth,
        )
        assert r.status_code == 201, r.text

        r = await client.get(f"/api/v1/cde/readiness/?project_id={pid}", headers=auth)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total_containers"] == 1
        sig = _signals(body)
        assert sig["containers_created"] is True
        assert sig["structured_naming"] is True
        assert sig["suitability_assigned"] is True
        assert sig["classification_used"] is True
        # workflow not exercised yet
        assert sig["shared_reached"] is False
        assert sig["published_reached"] is False
        assert sig["gate_signed"] is False
        assert sig["revision_controlled"] is False
        # (2 + 2 + 2 + 1) / 17 -> 41
        assert body["score"] == 41
        assert body["level"] == "forming"

    async def test_workflow_signals_light_up(
        self, client: AsyncClient, auth: dict[str, str]
    ) -> None:
        pid = await _new_project(client, auth)
        # Create straight into SHARED, then publish with a signature (Gate B),
        # and give it two revisions so version control counts.
        r = await client.post(
            "/api/v1/cde/containers/",
            json={
                "project_id": pid,
                "container_code": f"WF-{uuid.uuid4().hex[:6]}",
                "title": "Readiness workflow container",
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
                "approver_signature": "Readiness Tester",
                "approval_comments": "approved",
            },
            headers=auth,
        )
        assert r.status_code == 200, r.text

        r = await client.get(f"/api/v1/cde/readiness/?project_id={pid}", headers=auth)
        assert r.status_code == 200, r.text
        body = r.json()
        sig = _signals(body)
        assert sig["containers_created"] is True
        assert sig["shared_reached"] is True
        assert sig["published_reached"] is True
        assert sig["gate_signed"] is True
        assert sig["revision_controlled"] is True
        # (2 + 2 + 3 + 2 + 2) / 17 -> 65
        assert body["score"] == 65
        assert body["level"] == "operational"

    async def test_readiness_requires_auth(self, client: AsyncClient) -> None:
        r = await client.get(f"/api/v1/cde/readiness/?project_id={uuid.uuid4()}")
        assert r.status_code in (401, 403)
