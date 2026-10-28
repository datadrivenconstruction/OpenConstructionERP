# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Shared fixtures for the timeline test suite.

The session fixture runs against the shared PostgreSQL unit database from
``tests/_pg.py``, inside an outer transaction rolled back on teardown.

The module's validation rules are registered here because the application does
that from its ``on_startup`` hook and no test process runs application startup.
Without it the ``timeline`` rule set resolves to zero rules and the engine
reports it as *unsupported*, which in the payload is indistinguishable from
"the rules ran and found nothing".

That fixture is deliberately **not** what proves startup wiring works. Doing
the registration here and then asserting on it would pass just as happily if
``on_startup`` registered nothing at all, which is precisely how the same bug
survived in the credentials module. ``test_timeline_startup.py`` asserts
against ``on_startup`` itself instead.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit_log import ActivityLog
from app.dependencies import (
    get_current_user_id,
    get_current_user_payload,
    get_session,
)
from app.modules.projects.models import Project
from app.modules.timeline.router import router as timeline_router
from app.modules.timeline.validators import register_timeline_rules
from app.modules.users.models import User
from tests._pg import transactional_session

API_PREFIX = "/v1/timeline"


@pytest.fixture(scope="session", autouse=True)
def _timeline_rules_registered() -> None:
    """Register the module's validation rules for the test session."""
    register_timeline_rules()


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """A rolled-back session on the shared PostgreSQL unit database."""
    async with transactional_session() as s:
        yield s


def now() -> datetime:
    """Timezone-aware UTC now, matching what the ORM default writes."""
    return datetime.now(UTC)


def minutes_ago(n: int) -> datetime:
    """A timestamp *n* minutes in the past."""
    return now() - timedelta(minutes=n)


# ── Row factories ────────────────────────────────────────────────────────────


async def make_user(session: AsyncSession, *, role: str = "editor") -> User:
    """Persist a user with an explicit role (non-admin by default).

    The access guard reads ``User.role`` from the database rather than the JWT
    payload, so a cross-project test needs a persisted non-admin row to mean
    anything.
    """
    user = User(
        email=f"tl-{uuid.uuid4().hex[:10]}@example.com",
        hashed_password="x",
        role=role,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


async def make_project(session: AsyncSession, owner_id: uuid.UUID) -> Project:
    """Persist a project owned by ``owner_id``."""
    project = Project(
        name=f"Timeline {uuid.uuid4().hex[:6]}",
        owner_id=owner_id,
        currency="EUR",
    )
    session.add(project)
    await session.flush()
    return project


async def make_entry(
    session: AsyncSession,
    *,
    project_id: uuid.UUID | str | None,
    action: str = "ncr.created",
    entity_type: str = "ncr",
    entity_id: str | None = None,
    module: str | None = "ncr",
    actor_id: uuid.UUID | None = None,
    created_at: datetime | None = None,
    metadata: dict[str, Any] | None = None,
) -> ActivityLog:
    """Persist one activity-log row directly.

    ``created_at`` is written verbatim rather than left to the ORM default,
    which is what makes the ordering tests possible: two rows can be planted on
    byte-identical timestamps exactly as a burst of bridge writes would land
    them.
    """
    entry = ActivityLog(
        actor_id=actor_id,
        entity_type=entity_type,
        entity_id=entity_id if entity_id is not None else str(uuid.uuid4()),
        action=action,
        module=module,
        parent_entity_type="project" if project_id is not None else None,
        parent_entity_id=str(project_id) if project_id is not None else None,
        metadata_=dict(metadata or {}),
    )
    if created_at is not None:
        entry.created_at = created_at
    session.add(entry)
    await session.flush()
    return entry


# ── HTTP plumbing ────────────────────────────────────────────────────────────


def build_app(
    db_session: AsyncSession,
    *,
    caller_id: uuid.UUID | str,
    role: str = "editor",
) -> FastAPI:
    """Mount the module router with the test session and a fixed caller."""
    app = FastAPI()
    app.include_router(timeline_router, prefix=API_PREFIX)

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
