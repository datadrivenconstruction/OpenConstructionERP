# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Shared fixtures for the cost_match database-backed suites.

The app is booted once for the whole package rather than once per module:
standing it up is the expensive part of these tests, and both the service-level
and the HTTP-level suites need the same thing from it (the schema, an
authenticated admin, and the module's routes mounted).

A cost base is seeded under its own ``region`` tag so retrieval in these tests
can never reach a row some other suite left behind, and so the tests can assert
on an exact candidate pool.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Every seeded cost item lives under this region, which no other suite uses.
# Retrieval is always scoped to it, so the candidate pool in these tests is
# exactly the rows below and nothing else.
TEST_REGION = "OE_TEST_COST_MATCH"
TEST_SOURCE = "cwicr"

# The seeded base. Small on purpose: every tier assertion in the suite is
# derived by hand from these four descriptions and the matcher's published
# formula, so a scoring change shows up as a failing test rather than as a
# silently different number.
SEED_ITEMS: tuple[dict[str, Any], ...] = (
    {
        "code": "CM-C30-WALL",
        "description": "Reinforced concrete wall C30/37",
        "descriptions": {
            "en": "Reinforced concrete wall C30/37",
            "de": "Stahlbetonwand C30/37",
        },
        "unit": "m3",
        "rate": "185.00",
    },
    {
        "code": "CM-REBAR",
        "description": "Reinforcement steel B500B",
        "descriptions": {
            "en": "Reinforcement steel B500B",
            "de": "Bewehrungsstahl B500B",
        },
        "unit": "kg",
        "rate": "1.85",
    },
    {
        "code": "CM-FORMWORK",
        "description": "Formwork for walls",
        "descriptions": {"en": "Formwork for walls", "de": "Wandschalung"},
        "unit": "m2",
        "rate": "42.50",
    },
    {
        "code": "CM-PLASTER",
        "description": "Gypsum plaster on walls",
        "descriptions": {"en": "Gypsum plaster on walls", "de": "Gipsputz auf Waenden"},
        "unit": "m2",
        "rate": "18.00",
    },
)


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


@pytest_asyncio.fixture(scope="session")
async def header(client: AsyncClient) -> dict[str, str]:
    """Register, force-activate and log in one admin for the whole package."""
    tag = uuid.uuid4().hex[:8]
    email = f"cost-match-{tag}@test.io"
    password = f"CostMatch{tag}9"
    registration = await client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": f"Cost Match {tag}",
            "role": "admin",
        },
    )
    assert registration.status_code in (200, 201), registration.text

    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as session:
        await session.execute(
            update(User).where(User.email == email.lower()).values(role="admin", is_active=True),
        )
        await session.commit()

    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    token = login.json().get("access_token", "")
    assert token, login.text
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture(scope="session")
async def cost_base(app_instance) -> dict[str, uuid.UUID]:
    """Seed the isolated cost base and return ``{code: cost_item_id}``.

    Idempotent within a session: the codes are namespaced by ``TEST_REGION``
    and the unique constraint is on ``(code, region)``, so a re-run of the
    suite against a persistent database updates nothing and inserts nothing
    twice.
    """
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.costs.models import CostItem

    ids: dict[str, uuid.UUID] = {}
    async with async_session_factory() as session:
        for row in SEED_ITEMS:
            existing = await session.execute(
                select(CostItem).where(
                    CostItem.code == row["code"],
                    CostItem.region == TEST_REGION,
                )
            )
            item = existing.scalars().first()
            if item is None:
                item = CostItem(
                    code=row["code"],
                    description=row["description"],
                    descriptions=row["descriptions"],
                    unit=row["unit"],
                    rate=row["rate"],
                    currency="EUR",
                    source=TEST_SOURCE,
                    region=TEST_REGION,
                    is_active=True,
                )
                session.add(item)
                await session.flush()
            ids[row["code"]] = item.id
        await session.commit()
    return ids


@pytest_asyncio.fixture(scope="session")
async def project_id(client: AsyncClient, header: dict[str, str]) -> str:
    """One project the whole package hangs its runs off."""
    response = await client.post(
        "/api/v1/projects/",
        json={"name": f"Cost match {uuid.uuid4().hex[:6]}", "description": "cost match suite"},
        headers=header,
    )
    assert response.status_code in (200, 201), response.text
    return response.json()["id"]
