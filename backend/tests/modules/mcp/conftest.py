# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Shared fixtures for the MCP server tests.

The session is the shared PostgreSQL unit database from ``tests/_pg.py`` inside
an outer transaction rolled back on teardown. The MCP endpoint authenticates by
token, so its app needs only the session override; the settings routes also get
a fixed signed-in caller.

Permissions and validation rules are registered here because no test process
runs application startup, and an unknown permission is denied by the registry,
which would look like an authorisation bug rather than missing setup.
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

from app.dependencies import get_current_user_id, get_current_user_payload, get_session
from app.modules.mcp.auth import tool_call_limiter
from app.modules.mcp.models import McpSettings
from app.modules.mcp.protocol import LATEST_PROTOCOL_VERSION
from app.modules.mcp.router import router as mcp_router
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

API_PREFIX = "/v1/mcp"
PROTOCOL_VERSION = LATEST_PROTOCOL_VERSION


@pytest.fixture(scope="session", autouse=True)
def _mcp_module_registered() -> None:
    """Register the permissions the tools check and the module's validation rules."""
    from app.modules.boq.permissions import register_boq_permissions
    from app.modules.costs.permissions import register_cost_permissions
    from app.modules.documents.permissions import register_document_permissions
    from app.modules.mcp.permissions import register_mcp_permissions
    from app.modules.mcp.validators import register_mcp_rules
    from app.modules.projects.permissions import register_project_permissions
    from app.modules.punchlist.permissions import register_punchlist_permissions
    from app.modules.rfi.permissions import register_rfi_permissions
    from app.modules.risk.permissions import register_risk_permissions
    from app.modules.schedule.permissions import register_schedule_permissions
    from app.modules.submittals.permissions import register_submittals_permissions
    from app.modules.tasks.permissions import register_tasks_permissions
    from app.modules.validation.permissions import register_validation_permissions

    for register in (
        register_boq_permissions,
        register_cost_permissions,
        register_document_permissions,
        register_mcp_permissions,
        register_project_permissions,
        register_punchlist_permissions,
        register_rfi_permissions,
        register_risk_permissions,
        register_schedule_permissions,
        register_submittals_permissions,
        register_tasks_permissions,
        register_validation_permissions,
    ):
        register()
    register_mcp_rules()


@pytest.fixture(autouse=True)
def _fresh_rate_windows() -> None:
    """Each test starts with an untouched per-token budget."""
    tool_call_limiter.reset()


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """A rolled-back session on the shared PostgreSQL unit database."""
    async with transactional_session() as s:
        yield s


async def make_user(session: AsyncSession, *, role: str = "editor") -> User:
    """Persist an active user with an explicit role."""
    user = User(
        email=f"mcp-{uuid.uuid4().hex[:10]}@example.com",
        hashed_password="x",
        role=role,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


async def make_project(session: AsyncSession, owner_id: uuid.UUID, *, name: str | None = None) -> Project:
    """Persist a project owned by ``owner_id``."""
    project = Project(name=name or f"MCP {uuid.uuid4().hex[:6]}", owner_id=owner_id, currency="EUR")
    session.add(project)
    await session.flush()
    return project


async def enable_mcp(session: AsyncSession, user_id: uuid.UUID, *, rate_limit: int = 60) -> McpSettings:
    """Switch MCP on for ``user_id``."""
    row = McpSettings(user_id=user_id, enabled=True, rate_limit_per_minute=rate_limit)
    session.add(row)
    await session.flush()
    return row


async def issue_token(session: AsyncSession, user_id: uuid.UUID, *, can_propose: bool = True) -> tuple[str, str]:
    """Create an MCP token through the service; returns (secret, token id)."""
    from app.modules.mcp.schemas import McpTokenCreate
    from app.modules.mcp.service import McpService

    created = await McpService(session).create_token(
        user_id, McpTokenCreate(name="Desktop client", expires_in_days=30, can_propose=can_propose)
    )
    return created.token, str(created.id)


def build_app(db_session: AsyncSession, *, caller_id: uuid.UUID | str | None = None, role: str = "editor") -> FastAPI:
    """Mount the MCP router on the test session; with ``caller_id`` the settings routes see that person."""
    app = FastAPI()
    app.include_router(mcp_router, prefix=API_PREFIX)

    async def _session_override() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = _session_override
    if caller_id is not None:

        async def _user_override() -> str:
            return str(caller_id)

        async def _payload_override() -> dict[str, Any]:
            return {"sub": str(caller_id), "role": role, "permissions": []}

        app.dependency_overrides[get_current_user_id] = _user_override
        app.dependency_overrides[get_current_user_payload] = _payload_override
    return app


def http_client(app: FastAPI) -> AsyncClient:
    """In-process async client on the test's own event loop."""
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def rpc(method: str, params: dict[str, Any] | None = None, msg_id: int | str | None = 1) -> dict[str, Any]:
    """A JSON-RPC request (or a notification when ``msg_id`` is None)."""
    message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        message["params"] = params
    if msg_id is not None:
        message["id"] = msg_id
    return message


def auth(token: str) -> dict[str, str]:
    """Headers an MCP client sends."""
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": PROTOCOL_VERSION,
    }
