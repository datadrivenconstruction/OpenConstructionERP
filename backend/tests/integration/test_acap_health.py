from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest_asyncio.fixture
async def client():
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest.mark.asyncio
async def test_acap_health_returns_ok(client):
    resp = await client.get("/api/v1/acap/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"status": "ok", "module": "acap"}
