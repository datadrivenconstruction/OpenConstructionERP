"""Planned / actual cost on a schedule activity has a WRITE path.

``ActivityResponse`` always carried ``cost_planned`` / ``cost_actual``, but
neither ``ActivityCreate`` nor ``ActivityUpdate`` accepted them, so every
activity in every schedule had a zero budget and the EVM / budget-burn views
(BAC = sum of cost_planned) could only ever report 0. A seeded programme
with an 18-line estimate behind it still read as "no budget".

Pins: cost set on create is echoed back; a PATCH updates one figure without
touching the other; a negative figure is refused by validation.

Runs against the PostgreSQL cluster provisioned by ``tests/conftest.py``.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()

    async with app.router.lifespan_context(app):
        from app.database import Base, engine
        from app.modules.schedule import models as _schedule_models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _admin_headers(client: AsyncClient) -> dict[str, str]:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    email = f"sched-cost-{uuid.uuid4().hex[:8]}@schedule.io"
    password = f"SchedCost{uuid.uuid4().hex[:6]}9"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "Cost Owner"},
    )
    assert reg.status_code in (200, 201), reg.text
    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(role="admin", is_active=True))
        await s.commit()
    login = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _schedule(client: AsyncClient, headers: dict[str, str]) -> str:
    proj = await client.post(
        "/api/v1/projects/",
        json={"name": f"Cost {uuid.uuid4().hex[:6]}", "currency": "AUD"},
        headers=headers,
    )
    assert proj.status_code == 201, proj.text
    sched = await client.post(
        "/api/v1/schedule/schedules/",
        json={
            "project_id": proj.json()["id"],
            "name": "Master program",
            "start_date": "2026-09-07",
            "end_date": "2026-11-27",
        },
        headers=headers,
    )
    assert sched.status_code == 201, sched.text
    return sched.json()["id"]


def _dec(value) -> Decimal:
    return Decimal(str(value))


@pytest.mark.asyncio
async def test_planned_and_actual_cost_round_trip(http_client: AsyncClient):
    headers = await _admin_headers(http_client)
    schedule_id = await _schedule(http_client, headers)

    created = await http_client.post(
        f"/api/v1/schedule/schedules/{schedule_id}/activities/",
        json={
            "name": "MCC-2 switchgear supply",
            "start_date": "2026-09-14",
            "end_date": "2026-09-18",
            "cost_planned": "12500.50",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert _dec(body["cost_planned"]) == Decimal("12500.50")
    assert body["cost_actual"] in (None, 0, "0", "0.00")

    patched = await http_client.patch(
        f"/api/v1/schedule/activities/{body['id']}",
        json={"cost_actual": "4800"},
        headers=headers,
    )
    assert patched.status_code == 200, patched.text
    after = patched.json()
    assert _dec(after["cost_actual"]) == Decimal("4800")
    # The other figure is untouched by a partial update.
    assert _dec(after["cost_planned"]) == Decimal("12500.50")


@pytest.mark.asyncio
async def test_negative_cost_is_refused(http_client: AsyncClient):
    headers = await _admin_headers(http_client)
    schedule_id = await _schedule(http_client, headers)

    bad = await http_client.post(
        f"/api/v1/schedule/schedules/{schedule_id}/activities/",
        json={
            "name": "Cable tray",
            "start_date": "2026-09-14",
            "end_date": "2026-09-18",
            "cost_planned": "-1",
        },
        headers=headers,
    )
    assert bad.status_code == 422, bad.text
