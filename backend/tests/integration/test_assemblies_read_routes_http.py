"""The assembly read routes enforce ownership over HTTP.

An assembly is a recipe in its owner's catalogue, not a project record, so
these routes stay out of the project-access check and sit in the security
ratchet baseline on purpose. What keeps them safe is the owner gate, and
``test_assemblies_idor.py`` only calls that helper directly. This file pins
that the routes themselves are wired to it: another tenant gets 404 on the
item and its export and does not find it in search, while the owner reads all
three.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from app.dependencies import get_current_user_id, get_current_user_payload, get_session
from tests._pg import transactional_session

pytestmark = pytest.mark.tenant_isolation

PREFIX = "/v1/assemblies"


@pytest_asyncio.fixture
async def session() -> AsyncIterator[Any]:
    async with transactional_session() as s:
        yield s


async def _make_user(session) -> uuid.UUID:
    from app.modules.users.models import User

    user = User(email=f"asm-{uuid.uuid4().hex[:10]}@example.com", hashed_password="x", role="editor")
    session.add(user)
    await session.flush()
    return user.id


async def _make_assembly(session, owner_id: uuid.UUID) -> tuple[uuid.UUID, str]:
    from app.modules.assemblies.models import Assembly

    code = f"ASM-{uuid.uuid4().hex[:8]}"
    asm = Assembly(
        code=code,
        name=code,
        description="",
        unit="m3",
        category="",
        classification={},
        total_rate="100",
        currency="EUR",
        bid_factor="1.0",
        regional_factors={},
        is_template=False,
        project_id=None,
        owner_id=owner_id,
        is_active=True,
        metadata_={},
    )
    session.add(asm)
    await session.flush()
    return asm.id, code


def _app(session, caller: uuid.UUID) -> FastAPI:
    from app.modules.assemblies.permissions import register_assemblies_permissions
    from app.modules.assemblies.router import router

    register_assemblies_permissions()
    app = FastAPI()
    app.include_router(router, prefix=PREFIX)

    async def _session_override():
        yield session

    async def _user_override() -> str:
        return str(caller)

    async def _payload_override() -> dict[str, Any]:
        return {"sub": str(caller), "role": "editor", "permissions": ["assemblies.read"]}

    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[get_current_user_id] = _user_override
    app.dependency_overrides[get_current_user_payload] = _payload_override
    return app


async def _read(session, caller: uuid.UUID, asm_id: uuid.UUID, code: str) -> tuple[int, int, bool]:
    transport = httpx.ASGITransport(app=_app(session, caller))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        item = await client.get(f"{PREFIX}/{asm_id}")
        export = await client.get(f"{PREFIX}/{asm_id}/export/")
        search = await client.get(f"{PREFIX}/", params={"q": code})
    assert search.status_code == 200, search.text
    listed = any(row["id"] == str(asm_id) for row in search.json()["items"])
    return item.status_code, export.status_code, listed


@pytest.mark.asyncio
async def test_another_tenant_cannot_read_an_assembly(session) -> None:
    owner = await _make_user(session)
    outsider = await _make_user(session)
    asm_id, code = await _make_assembly(session, owner)
    await session.commit()

    assert await _read(session, outsider, asm_id, code) == (404, 404, False)


@pytest.mark.asyncio
async def test_the_owner_reads_the_assembly(session) -> None:
    owner = await _make_user(session)
    asm_id, code = await _make_assembly(session, owner)
    await session.commit()

    assert await _read(session, owner, asm_id, code) == (200, 200, True)
