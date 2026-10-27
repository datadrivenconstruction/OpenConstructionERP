# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""List-views API against a real database: ownership, sharing, tenant bounds.

Two editors of one install: a personal view stays with its owner, a shared one
reaches the colleague read-only, and a view of another tenant never shows up.
"""

from __future__ import annotations

import uuid

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

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield app


@pytest_asyncio.fixture(scope="module")
async def client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _register(client: AsyncClient, tag: str) -> tuple[dict[str, str], uuid.UUID]:
    email = f"list-views-{tag}-{uuid.uuid4().hex[:6]}@test.io"
    password = f"ListViews{tag}9x"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": f"List Views {tag}", "role": "editor"},
    )
    assert reg.status_code in (200, 201), reg.text

    from sqlalchemy import select, update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as session:
        await session.execute(update(User).where(User.email == email.lower()).values(role="editor", is_active=True))
        await session.commit()
        user_id = (await session.execute(select(User.id).where(User.email == email.lower()))).scalar_one()

    login = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    token = login.json().get("access_token", "")
    assert token, login.text
    return {"Authorization": f"Bearer {token}"}, user_id


SCOPE = f"tests.list-{uuid.uuid4().hex[:8]}"
STATE = {"columns": ["code", "qty"], "sort": {"key": "qty", "dir": "desc"}, "filters": {"code": "01"}}


async def test_personal_shared_and_owner_only_changes(client):
    owner, _ = await _register(client, "owner")
    colleague, _ = await _register(client, "peer")

    r = await client.post(
        "/api/v1/list-views/", headers=owner, json={"scope_key": SCOPE, "name": "Mine", "state": STATE}
    )
    assert r.status_code == 201, r.text
    mine = r.json()["view"]
    assert mine["is_own"] and r.json()["findings"] == []

    seen = await client.get("/api/v1/list-views/", headers=colleague, params={"scope_key": SCOPE})
    assert seen.status_code == 200 and seen.json() == []

    dup = await client.post("/api/v1/list-views/", headers=owner, json={"scope_key": SCOPE, "name": "Mine"})
    assert dup.status_code == 409

    shared = await client.patch(f"/api/v1/list-views/{mine['id']}", headers=owner, json={"is_shared": True})
    assert shared.status_code == 200, shared.text

    seen = (await client.get("/api/v1/list-views/", headers=colleague, params={"scope_key": SCOPE})).json()
    assert [v["name"] for v in seen] == ["Mine"] and seen[0]["is_own"] is False

    forbidden = await client.patch(f"/api/v1/list-views/{mine['id']}", headers=colleague, json={"name": "Theirs"})
    assert forbidden.status_code == 403
    assert (await client.delete(f"/api/v1/list-views/{mine['id']}", headers=colleague)).status_code == 403
    assert (await client.delete(f"/api/v1/list-views/{mine['id']}", headers=owner)).status_code == 204


async def test_warnings_come_back_and_errors_block(client):
    owner, _ = await _register(client, "warn")
    r = await client.post(
        "/api/v1/list-views/",
        headers=owner,
        json={"scope_key": SCOPE, "name": "Hidden sort", "state": {"columns": ["code"], "sort": {"key": "qty"}}},
    )
    assert r.status_code == 201, r.text
    assert [f["rule_id"] for f in r.json()["findings"]] == ["list_views.sort_column_visible"]

    bad = await client.post(
        "/api/v1/list-views/",
        headers=owner,
        json={"scope_key": SCOPE, "name": "Huge", "state": {"query": {"q": "x" * 40000}}},
    )
    assert bad.status_code == 422


async def test_a_default_view_stays_unique_per_page(client):
    owner, _ = await _register(client, "default")
    a = (
        await client.post(
            "/api/v1/list-views/", headers=owner, json={"scope_key": SCOPE, "name": "A", "is_default": True}
        )
    ).json()["view"]
    b = (
        await client.post(
            "/api/v1/list-views/", headers=owner, json={"scope_key": SCOPE, "name": "B", "is_default": True}
        )
    ).json()["view"]
    views = {
        v["name"]: v
        for v in (await client.get("/api/v1/list-views/", headers=owner, params={"scope_key": SCOPE})).json()
    }
    assert views["B"]["is_default"] and not views["A"]["is_default"]
    again = await client.patch(f"/api/v1/list-views/{a['id']}", headers=owner, json={"is_default": True})
    assert again.json()["view"]["is_default"] is True
    views = {
        v["name"]: v
        for v in (await client.get("/api/v1/list-views/", headers=owner, params={"scope_key": SCOPE})).json()
    }
    assert views["A"]["is_default"] and not views["B"]["is_default"]
    assert b["id"] != a["id"]


async def test_a_shared_view_of_another_tenant_stays_invisible(client):
    owner, owner_id = await _register(client, "tenant")
    from app.database import async_session_factory
    from app.modules.list_views.models import ListView
    from app.modules.list_views.service import ListViewService

    async with async_session_factory() as session:
        session.add(
            ListView(
                user_id=owner_id, tenant_id="other-tenant", scope_key=SCOPE, name="Foreign", state={}, is_shared=True
            )
        )
        await session.commit()
        visible = await ListViewService(session, user_id=uuid.uuid4(), tenant_id="workspace").list(SCOPE)
    assert "Foreign" not in [v.name for v in visible]
    seen = (await client.get("/api/v1/list-views/", headers=owner, params={"scope_key": SCOPE})).json()
    assert "Foreign" not in [v["name"] for v in seen]
