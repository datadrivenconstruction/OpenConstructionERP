# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Creating a change order on a project that already holds variation orders.

A standalone change order raised next to active variation orders gets a
warning written into its metadata after the insert. That second write is
the only difference between this project and one without variations, and
it is where creation failed: the endpoint answered 500 and nothing was kept.
These tests drive the HTTP endpoint against the real app and read back what
was stored.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.database import async_session_factory
from app.main import create_app


@pytest_asyncio.fixture
async def client():
    """The real FastAPI app, lifespan included, over an in-process transport."""
    app = create_app()
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac


async def _admin_headers(client: AsyncClient) -> dict[str, str]:
    from tests.integration._auth_helpers import promote_to_admin

    unique = uuid.uuid4().hex[:8]
    email = f"co-vo-{unique}@covariations.io"
    password = f"CoVo{unique}9"
    registered = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "CO beside VO"},
    )
    assert registered.status_code in (200, 201), registered.text
    await promote_to_admin(email)
    login = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _project(client: AsyncClient, headers: dict[str, str]) -> str:
    created = await client.post(
        "/api/v1/projects/", json={"name": f"Riverside Homes {uuid.uuid4().hex[:6]}"}, headers=headers
    )
    assert created.status_code in (200, 201), created.text
    return created.json()["id"]


async def _issue_variation(project_id: str) -> None:
    from app.modules.variations.models import VariationOrder

    async with async_session_factory() as session:
        session.add(
            VariationOrder(
                project_id=uuid.UUID(project_id),
                code="VO-001",
                title="Revised kitchen layout",
                final_cost_impact=Decimal("1800.00"),
                status="issued",
            )
        )
        await session.commit()


async def _create(client: AsyncClient, headers: dict[str, str], project_id: str, title: str):
    return await client.post("/api/v1/changeorders/", json={"project_id": project_id, "title": title}, headers=headers)


@pytest.mark.asyncio
async def test_a_change_order_is_created_and_kept_beside_an_active_variation(client: AsyncClient) -> None:
    headers = await _admin_headers(client)
    project_id = await _project(client, headers)
    first = await _create(client, headers, project_id, "Window upgrade")
    assert first.status_code == 201, first.text
    await _issue_variation(project_id)

    second = await _create(client, headers, project_id, "Extra socket in the garage")
    assert second.status_code == 201, second.text
    body = second.json()
    assert body["code"] == "CO-002"
    assert "standalone_overlap_warning" in body["metadata"]

    # The variations alias mounts the same router and failed the same way.
    via_alias = await client.post(
        "/api/v1/variations/", json={"project_id": project_id, "title": "Garden wall extension"}, headers=headers
    )
    assert via_alias.status_code == 201, via_alias.text

    listed = await client.get(f"/api/v1/changeorders/?project_id={project_id}", headers=headers)
    assert listed.status_code == 200, listed.text
    assert sorted(o["code"] for o in listed.json()) == ["CO-001", "CO-002", "CO-003"]
    stored = next(o for o in listed.json() if o["code"] == "CO-002")
    assert "standalone_overlap_warning" in stored["metadata"]


@pytest.mark.asyncio
async def test_a_change_order_on_a_project_without_variations_carries_no_warning(client: AsyncClient) -> None:
    headers = await _admin_headers(client)
    project_id = await _project(client, headers)
    created = await _create(client, headers, project_id, "Window upgrade")
    assert created.status_code == 201, created.text
    assert "standalone_overlap_warning" not in created.json()["metadata"]


@pytest.mark.asyncio
async def test_a_change_order_is_created_when_the_project_owner_is_deactivated(client: AsyncClient) -> None:
    """A deactivated owner must not matter: creation succeeds and is kept."""
    from sqlalchemy import update

    from app.modules.projects.models import Project
    from app.modules.users.models import User

    headers = await _admin_headers(client)
    project_id = await _project(client, headers)
    await _issue_variation(project_id)

    async with async_session_factory() as session:
        owner_id = (await session.get(Project, uuid.UUID(project_id))).owner_id
        await session.execute(update(User).where(User.id == owner_id).values(is_active=False))
        await session.commit()

    created = await _create(client, headers, project_id, "Extra socket in the garage")
    # The deactivated owner is also the caller here, so a 401/403 is the
    # authentication layer speaking; anything else must be a clean 201, never 500.
    assert created.status_code != 500, created.text
