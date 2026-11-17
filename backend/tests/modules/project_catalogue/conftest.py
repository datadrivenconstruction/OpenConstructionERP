# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Shared fixtures for the project catalogue database-backed suite.

The app is booted once for the package. The cost base lives under its own
``region`` tag so searches here never reach another suite's rows.
"""

from __future__ import annotations

import uuid

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

TEST_REGION = "OE_TEST_PROJECT_CATALOGUE"


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


async def _login(client: AsyncClient, role: str) -> dict[str, str]:
    tag = uuid.uuid4().hex[:8]
    email = f"project-catalogue-{tag}@test.io"
    password = f"ProjCat{tag}9"
    registration = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": f"Project Catalogue {tag}", "role": role},
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
    return await _login(client, "admin")


@pytest_asyncio.fixture(scope="session")
async def stranger(client: AsyncClient) -> dict[str, str]:
    """An editor who owns none of the projects below."""
    return await _login(client, "editor")


@pytest_asyncio.fixture
async def project_id(client: AsyncClient, header: dict[str, str]) -> str:
    """A fresh EUR project per test, so catalogues never leak between tests."""
    response = await client.post(
        "/api/v1/projects/",
        json={"name": f"Catalogue {uuid.uuid4().hex[:6]}", "description": "project catalogue suite", "currency": "EUR"},
        headers=header,
    )
    assert response.status_code in (200, 201), response.text
    return response.json()["id"]


@pytest_asyncio.fixture
async def wall_item(app_instance) -> uuid.UUID:
    """A fresh regional database row: reinforced concrete wall at 185.00 EUR per m3."""
    from app.database import async_session_factory
    from app.modules.costs.models import CostItem

    async with async_session_factory() as session:
        item = CostItem(
            code=f"PC-WALL-{uuid.uuid4().hex[:6]}",
            description="Reinforced concrete wall C30/37",
            unit="m3",
            rate="185.00",
            currency="EUR",
            source="cwicr",
            region=TEST_REGION,
            is_active=True,
        )
        session.add(item)
        await session.commit()
        return item.id


async def set_source_rate(cost_item_id: uuid.UUID, rate: str) -> None:
    """Move the master price, as a database update would."""
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.costs.models import CostItem

    async with async_session_factory() as session:
        await session.execute(update(CostItem).where(CostItem.id == cost_item_id).values(rate=rate))
        await session.commit()


async def master_rate(cost_item_id: uuid.UUID) -> str:
    from app.database import async_session_factory
    from app.modules.costs.models import CostItem

    async with async_session_factory() as session:
        return (await session.get(CostItem, cost_item_id)).rate
