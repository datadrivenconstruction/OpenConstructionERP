# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A locked bill keeps its numbers and its resource breakdown.

``renumber`` and ``enrich-resources`` wrote straight through the position
repository from the router, past the lock guard every service writer takes, so
a locked (issued) bill had its ordinals rewritten. Both now answer 409 on a
locked bill and leave the positions as they were, and still work on an open one.

Run:
    cd backend
    python -m pytest tests/integration/test_locked_bill_refuses_renumber.py -v
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

import app.modules.boq.models  # noqa: F401
import app.modules.costs.models  # noqa: F401
import app.modules.projects.models  # noqa: F401
import app.modules.users.models  # noqa: F401


@pytest_asyncio.fixture(scope="module")
async def http_client():
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    fastapi_app = create_app()
    async with fastapi_app.router.lifespan_context(fastapi_app):
        from app.database import Base, engine

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as ac:
            yield ac


@pytest_asyncio.fixture(scope="module")
async def headers(http_client):
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    email = f"lock-{uuid.uuid4().hex[:8]}@renumber.io"
    password = f"LockRenum{uuid.uuid4().hex[:6]}9"
    reg = await http_client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "Lock Renumber"},
    )
    assert reg.status_code in (200, 201), reg.text
    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(role="admin", is_active=True))
        await s.commit()
    login = await http_client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _bill_with_positions(client: AsyncClient, headers: dict[str, str]) -> str:
    project = await client.post(
        "/api/v1/projects/",
        json={"name": f"Lock {uuid.uuid4().hex[:6]}", "region": "DACH", "currency": "EUR"},
        headers=headers,
    )
    assert project.status_code == 201, project.text
    boq = await client.post(
        "/api/v1/boq/boqs/",
        json={"project_id": project.json()["id"], "name": "Issued bill"},
        headers=headers,
    )
    assert boq.status_code == 201, boq.text
    boq_id = boq.json()["id"]
    for ordinal in ("0007", "0003"):
        pos = await client.post(
            f"/api/v1/boq/boqs/{boq_id}/positions/",
            json={
                "boq_id": boq_id,
                "ordinal": ordinal,
                "description": f"Wall {ordinal}",
                "unit": "m3",
                "quantity": 10.0,
                "unit_rate": 185.0,
            },
            headers=headers,
        )
        assert pos.status_code == 201, pos.text
    return boq_id


async def _ordinals(client: AsyncClient, headers: dict[str, str], boq_id: str) -> list[str]:
    resp = await client.get(f"/api/v1/boq/boqs/{boq_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    return sorted(p["ordinal"] for p in resp.json()["positions"])


@pytest.mark.asyncio
@pytest.mark.parametrize("suffix", ["renumber", "enrich-resources"])
async def test_locked_bill_refuses_the_write_and_keeps_its_positions(http_client, headers, suffix):
    boq_id = await _bill_with_positions(http_client, headers)
    lock = await http_client.post(f"/api/v1/boq/boqs/{boq_id}/lock/", headers=headers)
    assert lock.status_code == 200, lock.text
    before = await _ordinals(http_client, headers, boq_id)

    resp = await http_client.post(f"/api/v1/boq/boqs/{boq_id}/{suffix}/", json={}, headers=headers)

    assert resp.status_code == 409, f"{suffix} on a locked bill answered {resp.status_code}: {resp.text}"
    assert await _ordinals(http_client, headers, boq_id) == before


@pytest.mark.asyncio
async def test_open_bill_is_still_renumbered(http_client, headers):
    boq_id = await _bill_with_positions(http_client, headers)

    resp = await http_client.post(f"/api/v1/boq/boqs/{boq_id}/renumber/", json={}, headers=headers)

    assert resp.status_code == 200, resp.text
    assert await _ordinals(http_client, headers, boq_id) != ["0003", "0007"]
