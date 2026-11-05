# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""An admin-authenticated API client over one module router and a real PostgreSQL session."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from httpx import ASGITransport, AsyncClient

import app.core.audit_log  # noqa: F401 - registers ActivityLog with Base
from app.dependencies import get_current_user_id, get_current_user_payload, get_session
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session


@asynccontextmanager
async def api_client(router: APIRouter, prefix: str, *setup: object) -> AsyncIterator[tuple[AsyncClient, object, User]]:
    """Yield ``(client, session, admin_user)``; ``setup`` callables run first (permissions, rule registration)."""
    for fn in setup:
        fn()  # type: ignore[operator]
    async with transactional_session() as session:
        user = User(email=f"est-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", role="admin")
        session.add(user)
        await session.flush()
        await session.commit()
        app = FastAPI()
        app.include_router(router, prefix=prefix)

        async def _session():
            yield session

        app.dependency_overrides[get_session] = _session
        app.dependency_overrides[get_current_user_id] = lambda: str(user.id)
        app.dependency_overrides[get_current_user_payload] = lambda: {
            "sub": str(user.id),
            "role": "admin",
            "permissions": [],
        }
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client, session, user


async def make_project(session: object, user: User, currency: str = "EUR") -> uuid.UUID:
    """A project owned by ``user``."""
    project = Project(name="Estimating rules", owner_id=user.id, currency=currency)
    session.add(project)  # type: ignore[attr-defined]
    await session.flush()  # type: ignore[attr-defined]
    return project.id
