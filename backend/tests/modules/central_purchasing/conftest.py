"""Fixtures for central purchasing API tests, on the PostgreSQL the top-level conftest provisions."""

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
    async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://test") as ac:
        yield ac


async def register_user(client: AsyncClient, role: str, tag: str) -> tuple[str, dict[str, str]]:
    """A fresh active user with ``role``; returns ``(user_id, auth header)``."""
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    tag = f"{tag}-{uuid.uuid4().hex[:6]}"
    email, password = f"cpb-{tag}@test.io", f"CpbTest{tag}9"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": f"Cpb {tag}", "role": role},
    )
    assert reg.status_code in (200, 201), reg.text
    async with async_session_factory() as session:
        await session.execute(update(User).where(User.email == email.lower()).values(role=role, is_active=True))
        await session.commit()
    login = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    token = login.json().get("access_token", "")
    assert token, login.text
    return reg.json()["id"], {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture(scope="module")
async def buyer(client: AsyncClient) -> tuple[str, dict[str, str]]:
    return await register_user(client, "admin", "buyer")
