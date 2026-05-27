"""Integration tests for the project-member endpoints used by the Team Strip.

Covers the three endpoints registered on the ``oe_projects`` router:

    GET    /api/v1/projects/{project_id}/members/
    POST   /api/v1/projects/{project_id}/members/
    DELETE /api/v1/projects/{project_id}/members/{user_id}/

Test matrix:

    * owner can list / add / remove
    * non-owner gets 404 (the router's verify_project_owner shape — 403 is
      reserved for the owner endpoint; non-owner access is rejected as
      404 to avoid leaking the existence of project UUIDs they may not see)
    * cannot add the same user twice (409)
    * cannot remove the project owner (400)

Follows the temp-SQLite isolation pattern from ``feedback_test_isolation.md``.
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import Base
from app.dependencies import (
    get_current_user_id,
    get_current_user_payload,
    get_session,
)


def _register_models() -> None:
    import app.modules.projects.models  # noqa: F401
    import app.modules.teams.models  # noqa: F401
    import app.modules.users.models  # noqa: F401


@pytest_asyncio.fixture
async def temp_engine_and_factory():
    """Spin up a per-test SQLite file and return engine + session factory."""
    tmp_db = Path(tempfile.mkdtemp()) / "project_members.db"
    url = f"sqlite+aiosqlite:///{tmp_db.as_posix()}"
    engine = create_async_engine(url, future=True)

    _register_models()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    yield engine, factory, tmp_db

    await engine.dispose()
    try:
        tmp_db.unlink(missing_ok=True)
        tmp_db.parent.rmdir()
    except OSError:
        pass


@pytest_asyncio.fixture
async def seeded_ids(temp_engine_and_factory) -> dict[str, str]:
    """Seed two users (owner + other) and one project owned by the first."""
    _engine, factory, _tmp = temp_engine_and_factory
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
    _engine, factory, _tmp = temp_engine_and_factory
    app = _build_app(factory, seeded_ids["owner_id"])
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def other_client(temp_engine_and_factory, seeded_ids) -> AsyncGenerator[AsyncClient, None]:
    _engine, factory, _tmp = temp_engine_and_factory
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


@pytest.mark.asyncio
async def test_non_owner_cannot_access_members(other_client: AsyncClient, seeded_ids: dict[str, str]):
    """A logged-in user that is NOT the project owner gets 403 on every verb.

    The router's ``_verify_project_owner`` raises 403 directly (not 404) for
    non-owners — see ``backend/app/modules/projects/router.py``.
    """
    pid = seeded_ids["project_id"]

    listing = await other_client.get(f"/api/v1/projects/{pid}/members/")
    assert listing.status_code == 403, listing.text

    add = await other_client.post(
        f"/api/v1/projects/{pid}/members/",
        json={"user_id": seeded_ids["invitee_id"], "role": "viewer"},
    )
    assert add.status_code == 403, add.text

    delete = await other_client.delete(f"/api/v1/projects/{pid}/members/{seeded_ids['invitee_id']}/")
    assert delete.status_code == 403, delete.text
