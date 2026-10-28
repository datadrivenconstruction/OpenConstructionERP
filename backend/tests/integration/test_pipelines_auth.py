"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pre-release security regression — Pipeline Builder auth gating.

The Pipeline Builder router is auto-mounted by the module loader, which
injects NO global auth dependency (auth in this codebase is per-route).
Phase 1 shipped several endpoints — including ``DELETE /{id}`` — taking
only a DB session, so they were reachable unauthenticated (data exposure
+ unauthenticated destructive delete / IDOR). Every read/mutate endpoint
now carries a ``CurrentUserId`` gate. These tests pin that: an anonymous
request must never reach pipeline data.

Test isolation (``feedback_test_isolation.md``): the per-session
PostgreSQL database is provided by ``backend/tests/conftest.py``; the
production database is never touched.

Run:
    cd backend
    python -m pytest tests/integration/test_pipelines_auth.py -v --tb=short
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest_asyncio.fixture(scope="module")
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


@pytest_asyncio.fixture
async def auth_headers(client: AsyncClient) -> dict[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"pipelines-{unique}@smoke.io"
    password = f"PipelinesTest{unique}9!"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "Pipelines Tester"},
    )
    assert reg.status_code == 201, reg.text
    resp = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    token = resp.json().get("access_token", "")
    assert token, resp.text
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_an_authenticated_caller_reaches_the_pipeline_reads(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    """The positive half: the two tests below pass on a router that refuses everyone.

    Both of them assert only that an anonymous request is turned away, and a
    dead route, an unmounted module or a blanket deny satisfies that as readily
    as a working gate does. So one caller has to get through, or "the gate
    works" is indistinguishable from "the feature is gone". These two paths take
    no id and no project, so a fresh user with no data still reaches 200.
    """
    for path in ("/api/v1/pipelines/", "/api/v1/pipelines/node-types/"):
        resp = await client.get(path, headers=auth_headers)
        assert resp.status_code == 200, f"GET {path} must serve an authenticated caller, got {resp.status_code}"


@pytest.mark.asyncio
async def test_pipeline_reads_require_auth(client: AsyncClient) -> None:
    pid = str(uuid.uuid4())
    for method, path in [
        ("GET", "/api/v1/pipelines/"),
        ("GET", "/api/v1/pipelines/node-types/"),
        ("GET", f"/api/v1/pipelines/{pid}"),
        ("GET", f"/api/v1/pipelines/{pid}/runs/"),
        ("GET", f"/api/v1/pipelines/runs/{pid}"),
    ]:
        resp = await client.request(method, path)
        assert resp.status_code in (401, 403), f"{method} {path} must require auth, got {resp.status_code}"


@pytest.mark.asyncio
async def test_pipeline_mutations_require_auth(client: AsyncClient) -> None:
    pid = str(uuid.uuid4())
    # The unauthenticated DELETE was the most dangerous gap — assert it 401s
    # BEFORE any row is loaded or deleted.
    for method, path, body in [
        ("POST", "/api/v1/pipelines/", {"name": "x", "graph": {"nodes": [], "edges": []}}),
        ("PUT", f"/api/v1/pipelines/{pid}", {"name": "y"}),
        ("DELETE", f"/api/v1/pipelines/{pid}", None),
        ("POST", f"/api/v1/pipelines/{pid}/run", {}),
    ]:
        resp = await client.request(method, path, json=body)
        assert resp.status_code in (401, 403), f"{method} {path} must require auth, got {resp.status_code}"
