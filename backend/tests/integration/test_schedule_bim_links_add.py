# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Add BIM links to an activity without erasing the ones already there.

The link-activity dialog merged the new element ids into a cached copy of the
activity and sent the whole list back, which the route stores as given. A
second link within the cache lifetime, from another tab or another user,
erased the first. ``mode: "add"`` merges on the server instead.
"""

from __future__ import annotations

import uuid

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


async def _register_login_admin(client: AsyncClient) -> dict[str, str]:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    email = f"bim-add-{uuid.uuid4().hex[:8]}@schedule.io"
    password = f"BimAdd{uuid.uuid4().hex[:6]}9"

    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "BIM Link Owner"},
    )
    assert reg.status_code in (200, 201), reg.text

    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(role="admin", is_active=True))
        await s.commit()

    login = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest_asyncio.fixture(scope="module")
async def activity(http_client):
    """One activity with no BIM links yet, and its auth headers."""
    headers = await _register_login_admin(http_client)

    proj = await http_client.post(
        "/api/v1/projects/",
        json={"name": f"BIM Links {uuid.uuid4().hex[:6]}", "description": "bim links", "currency": "EUR"},
        headers=headers,
    )
    assert proj.status_code == 201, proj.text

    sched = await http_client.post(
        "/api/v1/schedule/schedules/",
        json={
            "project_id": proj.json()["id"],
            "name": "BIM Link Schedule",
            "start_date": "2026-05-01",
            "end_date": "2026-09-30",
        },
        headers=headers,
    )
    assert sched.status_code == 201, sched.text

    act = await http_client.post(
        f"/api/v1/schedule/schedules/{sched.json()['id']}/activities/",
        json={
            "name": "Pour slab",
            "wbs_code": "01.01",
            "start_date": "2026-05-04",
            "end_date": "2026-05-15",
            "activity_type": "task",
        },
        headers=headers,
    )
    assert act.status_code == 201, act.text
    return act.json()["id"], headers


async def _links(client: AsyncClient, activity_id: str, headers: dict[str, str], ids: list[str], mode: str | None):
    body: dict[str, object] = {"bim_element_ids": ids}
    if mode:
        body["mode"] = mode
    resp = await client.patch(f"/api/v1/schedule/activities/{activity_id}/bim-links/", json=body, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["bim_element_ids"]


@pytest.mark.asyncio
async def test_add_keeps_the_links_already_stored(http_client, activity):
    activity_id, headers = activity
    a, b = str(uuid.uuid4()), str(uuid.uuid4())

    assert await _links(http_client, activity_id, headers, [a], "add") == [a]
    # The second call sends only B, as a dialog holding a stale copy would.
    assert await _links(http_client, activity_id, headers, [b], "add") == [a, b]
    # Adding an id that is already there changes nothing.
    assert await _links(http_client, activity_id, headers, [a], "add") == [a, b]


@pytest.mark.asyncio
async def test_replace_is_still_the_default(http_client, activity):
    activity_id, headers = activity
    c = str(uuid.uuid4())

    assert await _links(http_client, activity_id, headers, [c], None) == [c]
