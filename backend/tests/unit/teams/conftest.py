"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Shared fixtures for the Teams test suite.

Placed under ``tests/unit`` rather than ``tests/modules`` on purpose. This is an
access-control module, and ``tests/unit`` is what the sharded CI gate actually
runs (``.github/workflows/ci.yml`` lines 131 and 377); ``tests/modules`` runs
only in the chronically-red "CI" job, which is not a gate. A negative
access-control case that nothing gates is only half a proof.

The session fixture runs against the shared PostgreSQL unit database from
``tests/_pg.py``, inside an outer transaction that is rolled back on teardown.
Foreign keys stay ON: the module's guards resolve real ``User`` and ``Project``
rows, and the delete cascade under test is a real FK chain.

The module's validation rules are registered here. The application
registers them from its ``on_startup`` hook, which no test process runs, so
without this the ``teams`` rule set resolves to zero rules and the engine
reports it as ``unsupported`` - which is indistinguishable from "the rules ran
and found nothing".
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import (
    get_current_user_id,
    get_current_user_payload,
    get_session,
)
from app.modules.projects.models import Project
from app.modules.teams.models import EntityVisibility, Team, TeamMembership
from app.modules.teams.router import router as teams_router
from app.modules.teams.validators import register_teams_rules
from app.modules.users.models import User
from tests._pg import transactional_session

API_PREFIX = "/v1/teams"


@pytest.fixture(scope="session", autouse=True)
def _teams_rules_registered() -> None:
    """Register the module's rule set for the whole test session."""
    register_teams_rules()


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """A rolled-back session on the shared PostgreSQL unit database."""
    async with transactional_session() as s:
        yield s


# ── Row factories ────────────────────────────────────────────────────────────


async def make_user(
    session: AsyncSession,
    *,
    role: str = "editor",
    is_active: bool = True,
    full_name: str = "",
) -> User:
    """Persist a user with an explicit role (non-admin by default).

    The guards read ``User.role`` from the database, not from the JWT payload,
    so an access-control test needs a persisted non-admin row to be meaningful.
    """
    user = User(
        email=f"teams-{uuid.uuid4().hex[:10]}@example.com",
        hashed_password="x",
        role=role,
        is_active=is_active,
        full_name=full_name,
    )
    session.add(user)
    await session.flush()
    return user


async def make_project(session: AsyncSession, owner_id: uuid.UUID, *, name: str = "") -> Project:
    """Persist a project owned by ``owner_id``."""
    project = Project(
        name=name or f"Teams {uuid.uuid4().hex[:6]}",
        owner_id=owner_id,
        currency="EUR",
    )
    session.add(project)
    await session.flush()
    return project


async def make_team(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    name: str = "Team",
    is_default: bool = False,
    is_active: bool = True,
    sort_order: int = 0,
    metadata: dict[str, Any] | None = None,
) -> Team:
    """Persist a team inside a project."""
    team = Team(
        project_id=project_id,
        name=name,
        is_default=is_default,
        is_active=is_active,
        sort_order=sort_order,
        metadata_=metadata or {},
    )
    session.add(team)
    await session.flush()
    return team


async def make_membership(
    session: AsyncSession,
    team_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    role: str = "member",
) -> TeamMembership:
    """Persist a membership row directly, bypassing the service gate.

    Used to arrange a starting state - never to assert one. Anything that
    checks who may CREATE a membership must go through the service or HTTP.
    """
    membership = TeamMembership(team_id=team_id, user_id=user_id, role=role)
    session.add(membership)
    await session.flush()
    return membership


async def make_restriction(
    session: AsyncSession,
    team_id: uuid.UUID,
    *,
    entity_type: str = "document",
    entity_id: str = "",
) -> EntityVisibility:
    """Persist a restriction row directly."""
    row = EntityVisibility(
        entity_type=entity_type,
        entity_id=entity_id or str(uuid.uuid4()),
        team_id=team_id,
    )
    session.add(row)
    await session.flush()
    return row


# ── HTTP plumbing ────────────────────────────────────────────────────────────


def build_app(
    db_session: AsyncSession,
    *,
    caller_id: uuid.UUID | str,
    role: str = "editor",
) -> FastAPI:
    """Mount the module router with the test session and a fixed caller.

    ``role`` only seeds the JWT payload. The guards deliberately read the role
    off the persisted ``User`` row instead, so a test that wants a real admin
    has to create one with ``make_user(role="admin")`` - a forged payload is
    not enough, which is itself worth having covered.
    """
    app = FastAPI()
    app.include_router(teams_router, prefix=API_PREFIX)

    async def _session_override() -> AsyncIterator[AsyncSession]:
        yield db_session

    async def _user_override() -> str:
        return str(caller_id)

    async def _payload_override() -> dict[str, Any]:
        return {"sub": str(caller_id), "role": role, "permissions": []}

    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[get_current_user_id] = _user_override
    app.dependency_overrides[get_current_user_payload] = _payload_override
    return app


def http_client(app: FastAPI) -> AsyncClient:
    """In-process async client bound to ``app`` on the current event loop.

    ``httpx.AsyncClient`` over ``ASGITransport`` keeps the app on the test's own
    event loop; the synchronous ``TestClient`` would drive it from a worker
    thread on a second loop and break the asyncpg session created here.
    """
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
