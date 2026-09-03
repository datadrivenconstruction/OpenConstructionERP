# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Work Requests test fixtures.

Attachments land under the app data dir (``module_uploads_dir``), so the
data dir is pointed at a throwaway directory before the router is imported
- the same isolation the register_workflow suite uses. ``setdefault``, so a
caller that deliberately exports its own value still wins.

``api`` is the shared HTTP harness the newer suites use: a bare app with
the auth dependencies overridden and a NON-admin caller, because admin
bypasses every permission check and an admin-run suite would pass against
a module that locked everybody else out.
"""

from __future__ import annotations

import os
import tempfile

if "OE_DATA_DIR" not in os.environ:
    os.environ["OE_DATA_DIR"] = tempfile.mkdtemp(prefix="oe-test-datadir-")

import uuid

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.dependencies import get_current_user_id, get_current_user_payload, get_session
from app.modules.projects.models import Project
from app.modules.users.models import User
from app.modules.work_requests.router import router as wr_router
from tests._pg import isolated_engine

API_BASE = "/api/v1/work-requests"
API_USER_ID = "00000000-0000-0000-0000-0000000000e1"

API_EDITOR = {"role": "editor", "permissions": ["work_requests.read", "work_requests.create", "work_requests.update"]}
API_MANAGER = {"role": "manager", "permissions": [*API_EDITOR["permissions"], "work_requests.manage"]}


@pytest_asyncio.fixture
async def api():
    """``(client, project_id, state)`` - flip ``state["payload"]`` to change
    what the caller is allowed to do mid-test."""
    async with isolated_engine() as engine:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as s:
            user = User(
                id=uuid.UUID(API_USER_ID),
                email=f"wrx-{uuid.uuid4().hex[:8]}@example.com",
                hashed_password="x",
                full_name="Alex Example",
                role="editor",
            )
            s.add(user)
            await s.flush()
            project = Project(
                name="Acme Holdings - MCC upgrade",
                owner_id=user.id,
                currency="AUD",
                project_code="25406",
                client_id="Acme Holdings",
            )
            s.add(project)
            await s.commit()
            project_id = str(project.id)

        state = {"payload": dict(API_EDITOR)}
        app = FastAPI()
        app.include_router(wr_router, prefix=API_BASE)
        app.dependency_overrides[get_current_user_id] = lambda: API_USER_ID
        app.dependency_overrides[get_current_user_payload] = lambda: {"sub": API_USER_ID, **state["payload"]}

        async def _session_override():
            async with maker() as s:
                yield s

        app.dependency_overrides[get_session] = _session_override
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            yield client, project_id, state
