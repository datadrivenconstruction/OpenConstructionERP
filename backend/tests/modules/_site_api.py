# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Minimal FastAPI app and project fixture for the site-module validation tests on PostgreSQL."""

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


def build_app(session, caller: uuid.UUID, router: APIRouter, prefix: str) -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix=prefix)

    async def _session():
        yield session

    async def _uid() -> str:
        return str(caller)

    async def _payload() -> dict:
        return {"sub": str(caller), "role": "admin", "permissions": []}

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_current_user_id] = _uid
    app.dependency_overrides[get_current_user_payload] = _payload
    return app


@asynccontextmanager
async def http(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def make_project(session) -> tuple[uuid.UUID, uuid.UUID]:
    """A user and a project they own; returns ``(user_id, project_id)``."""
    tag = uuid.uuid4().hex[:6]
    user = User(email=f"site-{tag}@example.com", hashed_password="x", role="admin")
    session.add(user)
    await session.flush()
    project = Project(name="Site rules", owner_id=user.id, currency="EUR")
    session.add(project)
    await session.flush()
    await session.commit()
    return user.id, project.id
