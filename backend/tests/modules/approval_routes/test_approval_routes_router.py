# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Router-level tests for the approval-routes module.

Coverage:
    * Cross-tenant 404: a caller who is not on the route's project gets
      a 404 (NOT a 403, NOT a 200) — matches the project_access IDOR
      contract.
    * Missing permission 403: ``RequirePermission`` rejects callers who
      lack ``approval_routes.write`` from creating a route.
    * Happy POST /routes → POST /instances → POST /instances/{id}/decide
      round-trip via the actual router endpoints.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from fastapi import status as st
from httpx import ASGITransport, AsyncClient

import app.core.audit_log  # noqa: F401 — registers ActivityLog with Base
from app.dependencies import (
    get_current_user_id,
    get_current_user_payload,
    get_session,
    verify_project_access,
)
from app.modules.approval_routes.models import (  # noqa: F401 — registers ORM
    Instance,
    Route,
    Step,
    StepState,
)
from app.modules.approval_routes.router import router as ar_router
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator:
    """Per-test PostgreSQL session inside a rolled-back outer transaction.

    The shared ``oe_test_unit`` database already carries the full schema, so
    no DDL is applied here. The session's own ``commit()`` calls become
    savepoint releases, visible within the test, and the outer transaction is
    rolled back on teardown so each test starts from an empty database.
    """
    async with transactional_session() as s:
        yield s


async def _make_user(session, *, role: str = "editor") -> uuid.UUID:
    u = User(
        email=f"ar-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        role=role,
    )
    session.add(u)
    await session.flush()
    return u.id


async def _make_project(session, owner_id: uuid.UUID) -> uuid.UUID:
    p = Project(name="AR Router Test", owner_id=owner_id)
    session.add(p)
    await session.flush()
    return p.id


def _build_app(
    db_session,
    *,
    caller_id: str,
    role: str = "admin",
    permissions: list[str] | None = None,
) -> FastAPI:
    """Mount the approval_routes router with auth/session overrides.

    The default uses an ``admin`` role so RequirePermission short-circuits
    on the admin bypass. Tests that exercise permission denial override
    the role to a lower tier and an empty permission list.
    """
    app = FastAPI()
    app.include_router(ar_router, prefix="/v1/approval-routes")

    async def _session_override():
        yield db_session

    async def _user_override() -> str:
        return caller_id

    async def _payload_override() -> dict:
        return {
            "sub": caller_id,
            "role": role,
            "permissions": permissions or [],
        }

    async def _project_access_override(project_id, user_id, session) -> None:
        # Minimal owner-only ACL — matches the IDOR-404 policy.
        row = await session.get(Project, project_id)
        if row is None:
            raise HTTPException(status_code=st.HTTP_404_NOT_FOUND, detail="Project not found")
        if str(row.owner_id) != str(user_id):
            raise HTTPException(status_code=st.HTTP_404_NOT_FOUND, detail="Project not found")

    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[get_current_user_id] = _user_override
    app.dependency_overrides[get_current_user_payload] = _payload_override
    app.dependency_overrides[verify_project_access] = _project_access_override
    return app


@asynccontextmanager
async def _http(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """In-process async HTTP client bound to ``app`` on the current loop."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


# ── Cross-tenant 404 ─────────────────────────────────────────────────


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_cross_tenant_route_returns_404(db_session) -> None:
    owner_id = await _make_user(db_session)
    interloper_id = await _make_user(db_session)
    project_id = await _make_project(db_session, owner_id)
    await db_session.commit()

    # Owner creates a route on their project.
    owner_app = _build_app(db_session, caller_id=str(owner_id))
    other_user = await _make_user(db_session)
    await db_session.commit()
    async with _http(owner_app) as owner_client:
        resp = await owner_client.post(
            "/v1/approval-routes/routes",
            json={
                "project_id": str(project_id),
                "name": "Owner-only",
                "target_kind": "rfi",
                "steps": [
                    {
                        "ordinal": 1,
                        "approver_user_id": str(other_user),
                        "mode": "all",
                    }
                ],
            },
        )
    assert resp.status_code == 201, resp.text
    route_id = resp.json()["id"]

    # Interloper from a different "tenant" tries to fetch it.
    other_app = _build_app(
        db_session,
        caller_id=str(interloper_id),
        role="editor",
        permissions=["approval_routes.read", "approval_routes.write"],
    )
    async with _http(other_app) as other_client:
        resp = await other_client.get(f"/v1/approval-routes/routes/{route_id}")
    assert resp.status_code == 404, resp.text


# ── Missing permission 403 ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_missing_write_permission_is_403(db_session) -> None:
    owner_id = await _make_user(db_session, role="viewer")
    project_id = await _make_project(db_session, owner_id)
    await db_session.commit()

    # Caller has viewer role + empty permission list → RequirePermission
    # blocks any write.
    app = _build_app(
        db_session,
        caller_id=str(owner_id),
        role="viewer",
        permissions=["approval_routes.read"],
    )
    async with _http(app) as client:
        resp = await client.post(
            "/v1/approval-routes/routes",
            json={
                "project_id": str(project_id),
                "name": "Blocked",
                "target_kind": "markup",
                "steps": [
                    {"ordinal": 1, "approver_role": "qa", "mode": "any"},
                ],
            },
        )
    assert resp.status_code == 403, resp.text


# ── Happy POST + decide round-trip ────────────────────────────────────


@pytest.mark.asyncio
async def test_happy_path_post_decide_round_trip(db_session) -> None:
    owner_id = await _make_user(db_session)
    project_id = await _make_project(db_session, owner_id)
    # The owner is also the pinned approver so the IDOR-404 guard on
    # /decide passes (the owner_id is what the project_access override
    # accepts). The HTTP round-trip itself is what we're verifying here;
    # the engine-level user-pin enforcement is covered by
    # test_user_pinned_step_rejects_wrong_approver in the engine suite.
    approver_id = owner_id
    await db_session.commit()

    app = _build_app(db_session, caller_id=str(owner_id))

    async with _http(app) as client:
        # 1. Create route with a single user-pinned step.
        resp = await client.post(
            "/v1/approval-routes/routes",
            json={
                "project_id": str(project_id),
                "name": "RFI sign-off",
                "target_kind": "rfi",
                "steps": [
                    {
                        "ordinal": 1,
                        "approver_user_id": str(approver_id),
                        "mode": "all",
                    },
                ],
            },
        )
        assert resp.status_code == 201, resp.text
        route_id = resp.json()["id"]
        step_id = resp.json()["steps"][0]["id"]

        # 2. Start an instance.
        target_id = str(uuid.uuid4())
        resp = await client.post(
            "/v1/approval-routes/instances",
            json={
                "route_id": route_id,
                "target_kind": "rfi",
                "target_id": target_id,
            },
        )
        assert resp.status_code == 201, resp.text
        instance_id = resp.json()["id"]
        assert resp.json()["status"] == "pending"

        # 3. Owner-as-approver submits the decision on the only step.
        resp = await client.post(
            f"/v1/approval-routes/instances/{instance_id}/decide",
            json={"step_id": step_id, "decision": "approved", "comment": "ok"},
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "approved"
    assert resp.json()["completed_at"] is not None


# ── Clone (adopt into a project, editable) ────────────────────────────


@pytest.mark.asyncio
async def test_clone_route_produces_editable_project_route(db_session) -> None:
    """A tenant-wide route can be cloned into a project-scoped, editable copy.

    Mirrors the "adopt a preset" flow the CDE module uses: cloning a
    read-only route yields a fresh route with no ``system_key`` (so it can be
    PATCHed straight away) while the original is untouched.
    """
    owner_id = await _make_user(db_session)
    project_id = await _make_project(db_session, owner_id)
    await db_session.commit()

    app = _build_app(db_session, caller_id=str(owner_id))
    async with _http(app) as client:
        # Tenant-wide template (no project_id).
        resp = await client.post(
            "/v1/approval-routes/routes",
            json={
                "project_id": None,
                "name": "Tenant-wide template",
                "target_kind": "submittal",
                "steps": [
                    {"ordinal": 1, "approver_role": "editor", "mode": "all"},
                    {"ordinal": 2, "approver_role": "manager", "mode": "all"},
                ],
            },
        )
        assert resp.status_code == 201, resp.text
        source_id = resp.json()["id"]

        resp = await client.post(
            f"/v1/approval-routes/routes/{source_id}/clone",
            json={"project_id": str(project_id), "name": "Our review flow"},
        )
        assert resp.status_code == 201, resp.text
        clone = resp.json()
        assert clone["project_id"] == str(project_id)
        assert clone["system_key"] is None
        assert clone["name"] == "Our review flow"
        assert [s["ordinal"] for s in clone["steps"]] == [1, 2]
        assert [s["approver_role"] for s in clone["steps"]] == ["editor", "manager"]

        # The clone is editable ...
        resp = await client.patch(
            f"/v1/approval-routes/routes/{clone['id']}",
            json={"name": "Renamed"},
        )
        assert resp.status_code == 200, resp.text

        # ... while the source template is untouched.
        resp = await client.get(f"/v1/approval-routes/routes/{source_id}")
        assert resp.status_code == 200, resp.text
        assert resp.json()["name"] == "Tenant-wide template"


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_a_route_on_someone_elses_project_cannot_be_cloned(db_session) -> None:
    """Cloning reads the source route, so it needs the same access as reading it.

    The interloper owns a project of their own, so the target check passes;
    only the source check can refuse, and it must answer 404 like ``GET``.
    """
    owner_id = await _make_user(db_session)
    approver_id = await _make_user(db_session)
    interloper_id = await _make_user(db_session)
    owner_project = await _make_project(db_session, owner_id)
    interloper_project = await _make_project(db_session, interloper_id)
    await db_session.commit()

    async with _http(_build_app(db_session, caller_id=str(owner_id))) as owner_client:
        resp = await owner_client.post(
            "/v1/approval-routes/routes",
            json={
                "project_id": str(owner_project),
                "name": "Owner-only",
                "target_kind": "rfi",
                "steps": [{"ordinal": 1, "approver_user_id": str(approver_id), "mode": "all"}],
            },
        )
    assert resp.status_code == 201, resp.text
    route_id = resp.json()["id"]

    other_app = _build_app(
        db_session,
        caller_id=str(interloper_id),
        role="editor",
        permissions=["approval_routes.read", "approval_routes.write"],
    )
    async with _http(other_app) as other_client:
        resp = await other_client.post(
            f"/v1/approval-routes/routes/{route_id}/clone",
            json={"project_id": str(interloper_project), "name": "Copied"},
        )
        assert resp.status_code == 404, resp.text
        resp = await other_client.get("/v1/approval-routes/routes", params={"project_id": str(interloper_project)})
    assert resp.status_code == 200, resp.text
    assert all(r["name"] != "Copied" for r in resp.json())
