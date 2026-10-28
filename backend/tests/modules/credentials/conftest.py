# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Shared fixtures for the credentials registry test suite.

The session fixture runs against the shared PostgreSQL unit database from
``tests/_pg.py``, inside an outer transaction rolled back on teardown.

Foreign keys stay on: the module's access guard resolves real ``User`` and
``Project`` rows, and the requirement table's delete cascade is a database-level
``ON DELETE CASCADE`` from the project that never fires with the replication
role set.

Dates are always expressed relative to ``today`` through :func:`day`. A test
that hard-coded a calendar date would pass until that date drifted into the
past, and a register whose entire subject is expiry is the worst possible place
for a test that silently changes meaning over time.

The module's seven validation rules are registered here. The application does
that from its ``on_startup`` hook, which no test process runs, so without this
the ``credentials`` rule set resolves to zero rules and the engine reports it
as unsupported - which is indistinguishable from "the rules ran and found
nothing".
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from datetime import date as _date
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
from app.modules.credentials.models import Credential, CredentialRequirement
from app.modules.credentials.permissions import register_credentials_permissions
from app.modules.credentials.router import router as credentials_router
from app.modules.credentials.validators import register_credentials_rules
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

API_PREFIX = "/v1/credentials"


@pytest.fixture(scope="session", autouse=True)
def _credentials_module_registered() -> None:
    """Register the module's rules and permissions for the test session.

    Both are done by the module's ``on_startup`` hook in the running app, and no
    test process runs application startup. Without the permissions the routes
    answer 403 on an unknown permission code, which would look like an
    authorisation bug rather than missing test setup.
    """
    register_credentials_rules()
    register_credentials_permissions()


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """A rolled-back session on the shared PostgreSQL unit database."""
    async with transactional_session() as s:
        yield s


def today() -> _date:
    """The service's notion of today, in UTC, so tests agree with it."""
    return datetime.now(UTC).date()


def day(offset: int) -> _date:
    """A date ``offset`` days from today; negative is in the past."""
    return today() + timedelta(days=offset)


# ── Row factories ────────────────────────────────────────────────────────────


async def make_user(session: AsyncSession, *, role: str = "editor") -> User:
    """Persist a user with an explicit role (non-admin by default).

    The access guard reads ``User.role`` from the database rather than the JWT
    payload, so an IDOR test needs a persisted non-admin row to mean anything.
    """
    user = User(
        email=f"cred-{uuid.uuid4().hex[:10]}@example.com",
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
        name=f"Credentials {uuid.uuid4().hex[:6]}",
        owner_id=owner_id,
        currency="EUR",
    )
    session.add(project)
    await session.flush()
    return project


async def make_credential(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    holder_name: str = "Alex Mason",
    holder_kind: str = "person",
    holder_user_id: uuid.UUID | None = None,
    credential_type: str = "professional_license",
    discipline: str | None = None,
    valid_until: _date | None = None,
    issued_at: _date | None = None,
    notify_days_before: int = 30,
    status: str = "active",
    verified_at: _date | None = None,
    verified_by: str | None = None,
    **fields: Any,
) -> Credential:
    """Persist a credential.

    ``status`` defaults to ``active`` and is written verbatim, which is what
    makes the drift tests possible: a row can be planted with a stale stored
    status exactly as an ageing row would have.
    """
    credential = Credential(
        project_id=project_id,
        holder_name=holder_name,
        holder_kind=holder_kind,
        holder_user_id=holder_user_id,
        credential_type=credential_type,
        discipline=discipline,
        issued_at=issued_at,
        valid_until=valid_until,
        notify_days_before=notify_days_before,
        status=status,
        verified_at=verified_at,
        verified_by=verified_by,
        notes="",
        metadata_=fields.pop("metadata_", {}),
        **fields,
    )
    session.add(credential)
    await session.flush()
    return credential


async def make_requirement(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    credential_type: str = "professional_license",
    applies_to: str = "all",
    holder_kind: str = "person",
    is_blocking: bool = True,
    grace_days: int = 0,
    is_active: bool = True,
    description: str = "",
) -> CredentialRequirement:
    """Persist a requirement."""
    requirement = CredentialRequirement(
        project_id=project_id,
        credential_type=credential_type,
        applies_to=applies_to,
        holder_kind=holder_kind,
        is_blocking=is_blocking,
        grace_days=grace_days,
        is_active=is_active,
        description=description,
        metadata_={},
    )
    session.add(requirement)
    await session.flush()
    return requirement


# ── HTTP plumbing ────────────────────────────────────────────────────────────


def build_app(
    db_session: AsyncSession,
    *,
    caller_id: uuid.UUID | str,
    role: str = "editor",
) -> FastAPI:
    """Mount the module router with the test session and a fixed caller.

    ``role`` is the RBAC role in the token payload, which is what
    ``RequirePermission`` reads. It is deliberately separate from the persisted
    ``User.role`` the access guard reads: ``credentials.delete`` needs a manager,
    but persisting that caller as an *admin* would trip the guard's admin bypass
    and quietly turn a cross-project test into a permitted one.
    """
    app = FastAPI()
    app.include_router(credentials_router, prefix=API_PREFIX)

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
