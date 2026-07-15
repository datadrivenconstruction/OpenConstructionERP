# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Boot-level checks for the Schedule Intelligence module.

Proves the module is wired into the assembled app: the loader mounts its router
at ``/api/v1/schedule-intelligence`` and ``on_startup`` registers its permission
set. Uses the same ``create_app`` + lifespan harness as the other integration
suites so the whole startup path (module discovery, permission registration,
schema bring-up) actually runs.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest_asyncio.fixture(scope="module")
async def client() -> AsyncClient:
    app = create_app()

    @asynccontextmanager
    async def lifespan_ctx():
        async with app.router.lifespan_context(app):
            yield

    async with lifespan_ctx():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


async def test_module_health_endpoint_is_mounted(client: AsyncClient) -> None:
    """The loader mounts the router at the kebab-cased module path."""
    resp = await client.get("/api/v1/schedule-intelligence/")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"module": "oe_schedule_intelligence", "status": "active"}


async def test_permissions_registered_at_startup() -> None:
    """on_startup registered the full verb set on the shared registry."""
    from app.core.permissions import Role, permission_registry

    all_perms = permission_registry.list_all()
    assert all_perms.get("schedule_intelligence.read") == Role.VIEWER.value
    assert all_perms.get("schedule_intelligence.lock") == Role.MANAGER.value
    assert all_perms.get("schedule_intelligence.apply") == Role.MANAGER.value


async def test_locked_figure_endpoint_requires_auth(client: AsyncClient) -> None:
    """A project-scoped governance endpoint is gated (401 without a token)."""
    resp = await client.get(
        "/api/v1/schedule-intelligence/projects/00000000-0000-0000-0000-000000000000/locked-figures"
    )
    assert resp.status_code == 401
