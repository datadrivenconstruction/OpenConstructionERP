# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Shared PostgreSQL harness for the control-module rule tests (tasks, MoC, risk, progress)."""

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


def build_app(router: APIRouter, prefix: str, session, caller: uuid.UUID) -> FastAPI:
    """A one-router app whose session and caller are the test's own."""
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
    """An admin user and a project they own; returns ``(user_id, project_id)``."""
    tag = uuid.uuid4().hex[:6]
    user = User(email=f"ctl-{tag}@example.com", hashed_password="x", role="admin")
    session.add(user)
    await session.flush()
    project = Project(name=f"Control {tag}", owner_id=user.id, currency="EUR")
    session.add(project)
    await session.flush()
    await session.commit()
    return user.id, project.id


def rule_ids(findings: list[dict]) -> set[str]:
    """The rule ids of a list of findings."""
    return {f["rule_id"] for f in findings}
