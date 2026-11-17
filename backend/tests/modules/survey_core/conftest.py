# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Shared fixtures for the survey register database-backed suite.

The app is booted once for the package; each test gets a fresh project.
"""

from __future__ import annotations

import uuid

import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture(scope="session")
async def app_instance():
    """The full application, booted once, with the schema created."""
    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        from app.database import Base, engine

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield app


@pytest_asyncio.fixture(scope="session")
async def client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def login(client: AsyncClient, role: str) -> dict[str, str]:
    tag = uuid.uuid4().hex[:8]
    email = f"survey-{tag}@test.io"
    password = f"Survey{tag}9"
    registration = await client.post(
        "/api/v1/users/auth/register",
        # Self-registration knows four roles; a surveyor is made by an admin, so the row is changed below.
        json={
            "email": email,
            "password": password,
            "full_name": f"Survey {tag}",
            "role": role if role in ("admin", "manager", "editor", "viewer") else "editor",
        },
    )
    assert registration.status_code in (200, 201), registration.text

    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as session:
        await session.execute(update(User).where(User.email == email.lower()).values(role=role, is_active=True))
        await session.commit()
    login = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    token = login.json().get("access_token", "")
    assert token, login.text
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture(scope="session")
async def header(client: AsyncClient) -> dict[str, str]:
    """An admin for the whole package."""
    return await login(client, "admin")


@pytest_asyncio.fixture(scope="session")
async def stranger(client: AsyncClient) -> dict[str, str]:
    """An editor who owns none of the projects below."""
    return await login(client, "editor")


@pytest_asyncio.fixture
async def project_id(client: AsyncClient, header: dict[str, str]) -> str:
    """A fresh project per test, so registers never leak between tests."""
    response = await client.post(
        "/api/v1/projects/",
        json={"name": f"Survey {uuid.uuid4().hex[:6]}", "description": "survey register suite", "currency": "EUR"},
        headers=header,
    )
    assert response.status_code in (200, 201), response.text
    return response.json()["id"]


@pytest_asyncio.fixture(scope="session")
async def viewer(client: AsyncClient) -> dict[str, str]:
    """A viewer."""
    return await login(client, "viewer")
