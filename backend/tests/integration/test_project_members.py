"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Integration tests for the project-member endpoints used by the Team Strip.

Covers the three endpoints registered on the ``oe_projects`` router:

    GET    /api/v1/projects/{project_id}/members/
    POST   /api/v1/projects/{project_id}/members/
    DELETE /api/v1/projects/{project_id}/members/{user_id}/

Test matrix:

    * owner can list / add / remove
    * a user with no access gets 404 on the read (``_verify_project_access``,
      so the status code never confirms that a project UUID exists) and 403
      on the writes (``_verify_project_owner``, whose usual caller is a
      member who already knows the project is there)
    * cannot add the same user twice (409)
    * cannot remove the project owner (400)

Uses the PostgreSQL isolation pattern from ``feedback_test_isolation.md``.
"""

from __future__ import annotations

import uuid
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.dependencies import (
    get_current_user_id,
    get_current_user_payload,
    get_session,
)
from tests._pg import isolated_engine


@pytest_asyncio.fixture
async def temp_engine_and_factory():
    """Per-test throwaway PostgreSQL database, cloned from the schema-loaded template.

    The app under test opens its own sessions via the ``get_session`` override, so
    the test and the app run on separate connections that must see each other's
    commits - hence a real throwaway database rather than a savepoint-rolled-back
    shared session.
    """
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        yield engine, factory


@pytest_asyncio.fixture
async def seeded_ids(temp_engine_and_factory) -> dict[str, str]:
    """Seed two users (owner + other) and one project owned by the first."""
    _engine, factory = temp_engine_and_factory
    from app.modules.projects.models import Project
    from app.modules.teams.models import Team, TeamMembership
    from app.modules.users.models import User

    async with factory() as session:
        owner = User(
            email=f"owner-{uuid.uuid4().hex[:6]}@test.io",
            hashed_password="x",
            full_name="Test Owner",
        )
        other = User(
            email=f"other-{uuid.uuid4().hex[:6]}@test.io",
            hashed_password="x",
            full_name="Other User",
        )
        invitee = User(
            email=f"invitee-{uuid.uuid4().hex[:6]}@test.io",
            hashed_password="x",
            full_name="Invitee User",
        )
        session.add_all([owner, other, invitee])
        await session.flush()

        project = Project(name="Members Test", owner_id=owner.id)
        session.add(project)
        await session.flush()

        # Mirror what ProjectService.create_project does — create the default
        # team + owner membership row so the GET /members endpoint has data.
        team = Team(project_id=project.id, name="Default Team", is_default=True)
        session.add(team)
        await session.flush()
        session.add(TeamMembership(team_id=team.id, user_id=owner.id, role="lead"))
        await session.commit()

        return {
            "owner_id": str(owner.id),
            "other_id": str(other.id),
            "invitee_id": str(invitee.id),
            "project_id": str(project.id),
        }


def _build_app(factory, current_user_id: str, role: str = "editor") -> FastAPI:
    """Build a minimal FastAPI app with only the projects router mounted."""
    from app.modules.projects.router import router as projects_router

    app = FastAPI()
    app.include_router(projects_router, prefix="/api/v1/projects")

    async def _override_session() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def _override_user_id() -> str:
        return current_user_id

    async def _override_user_payload() -> dict:
        return {"sub": current_user_id, "role": role}

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user_id] = _override_user_id
    app.dependency_overrides[get_current_user_payload] = _override_user_payload
    return app


@pytest_asyncio.fixture
async def owner_client(temp_engine_and_factory, seeded_ids) -> AsyncGenerator[AsyncClient, None]:
    _engine, factory = temp_engine_and_factory
    app = _build_app(factory, seeded_ids["owner_id"])
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def other_client(temp_engine_and_factory, seeded_ids) -> AsyncGenerator[AsyncClient, None]:
    _engine, factory = temp_engine_and_factory
    app = _build_app(factory, seeded_ids["other_id"])
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ── Tests ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_owner_can_list_members(owner_client: AsyncClient, seeded_ids: dict[str, str]):
    """Owner sees themselves as the sole member after project creation."""
    pid = seeded_ids["project_id"]
    resp = await owner_client.get(f"/api/v1/projects/{pid}/members/")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) == 1
    assert body[0]["user_id"] == seeded_ids["owner_id"]
    assert body[0]["is_owner"] is True
    # Email and full_name come from the joined User row.
    assert "@" in body[0]["email"]
    assert body[0]["full_name"] == "Test Owner"


@pytest.mark.asyncio
async def test_owner_can_add_member(owner_client: AsyncClient, seeded_ids: dict[str, str]):
    """Owner adds the invitee with a non-default role; result echoes inputs."""
    pid = seeded_ids["project_id"]
    resp = await owner_client.post(
        f"/api/v1/projects/{pid}/members/",
        json={"user_id": seeded_ids["invitee_id"], "role": "estimator"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["user_id"] == seeded_ids["invitee_id"]
    assert body["role"] == "estimator"
    assert body["is_owner"] is False

    # Verify it shows up in the list.
    listing = await owner_client.get(f"/api/v1/projects/{pid}/members/")
    assert listing.status_code == 200
    members = listing.json()
    assert {m["user_id"] for m in members} == {
        seeded_ids["owner_id"],
        seeded_ids["invitee_id"],
    }


@pytest.mark.asyncio
async def test_cannot_add_same_user_twice(owner_client: AsyncClient, seeded_ids: dict[str, str]):
    """Second POST with the same user_id returns 409 Conflict."""
    pid = seeded_ids["project_id"]
    first = await owner_client.post(
        f"/api/v1/projects/{pid}/members/",
        json={"user_id": seeded_ids["invitee_id"], "role": "viewer"},
    )
    assert first.status_code == 201

    second = await owner_client.post(
        f"/api/v1/projects/{pid}/members/",
        json={"user_id": seeded_ids["invitee_id"], "role": "viewer"},
    )
    assert second.status_code == 409, second.text


@pytest.mark.asyncio
async def test_owner_can_remove_member(owner_client: AsyncClient, seeded_ids: dict[str, str]):
    """Owner removes a previously-added member; subsequent list excludes them."""
    pid = seeded_ids["project_id"]
    add = await owner_client.post(
        f"/api/v1/projects/{pid}/members/",
        json={"user_id": seeded_ids["invitee_id"], "role": "viewer"},
    )
    assert add.status_code == 201

    delete = await owner_client.delete(f"/api/v1/projects/{pid}/members/{seeded_ids['invitee_id']}/")
    assert delete.status_code == 204, delete.text

    listing = await owner_client.get(f"/api/v1/projects/{pid}/members/")
    assert listing.status_code == 200
    user_ids = {m["user_id"] for m in listing.json()}
    assert seeded_ids["invitee_id"] not in user_ids


@pytest.mark.asyncio
async def test_cannot_remove_owner(owner_client: AsyncClient, seeded_ids: dict[str, str]):
    """Attempting to delete the owner returns 400 with a clear message."""
    pid = seeded_ids["project_id"]
    resp = await owner_client.delete(f"/api/v1/projects/{pid}/members/{seeded_ids['owner_id']}/")
    assert resp.status_code == 400, resp.text
    assert "owner" in resp.json()["detail"].lower()


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_non_owner_cannot_access_members(other_client: AsyncClient, seeded_ids: dict[str, str]):
    """A logged-in user that is NOT the project owner is rejected on every verb.

    The two guards in ``backend/app/modules/projects/router.py`` deny with
    different codes on purpose, so the expected status differs per verb.

    The listing is a read and runs through ``_verify_project_access``, which
    raises 404, not 403: "missing" and "denied" have to be indistinguishable
    or the status code itself becomes an oracle telling an outsider that a
    given project UUID exists. That is the same policy the shared
    ``verify_project_access`` helper applies platform-wide.

    The writes run through ``_verify_project_owner``, which raises 403. It is
    reached by project members who are not the owner, and to them the project
    is no secret, so the code can say plainly that ownership is what is
    missing.
    """
    pid = seeded_ids["project_id"]

    listing = await other_client.get(f"/api/v1/projects/{pid}/members/")
    assert listing.status_code == 404, listing.text

    add = await other_client.post(
        f"/api/v1/projects/{pid}/members/",
        json={"user_id": seeded_ids["invitee_id"], "role": "viewer"},
    )
    assert add.status_code == 403, add.text

    delete = await other_client.delete(f"/api/v1/projects/{pid}/members/{seeded_ids['invitee_id']}/")
    assert delete.status_code == 403, delete.text
