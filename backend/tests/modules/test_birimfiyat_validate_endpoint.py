"""The published-prices statement reaches its rule through the validate endpoint.

The MarkupPanel checkbox writes ``metadata.priced_from_published_rates`` on the bill. The
router has to carry that into the rule context, on either the bill or the project.
"""

import os
import uuid
from typing import Any

os.environ.setdefault("SEED_SHOWCASE", "false")

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

RULE = "birimfiyat.overheads_not_applied_twice"


@pytest_asyncio.fixture(scope="module")
async def client():
    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        from app.database import Base, engine
        from app.modules.boq import models as _boq_models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac


@pytest_asyncio.fixture(scope="module")
async def headers(client) -> dict[str, str]:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    email = f"birimfiyat-{uuid.uuid4().hex[:6]}@example.io"
    password = f"Birim{uuid.uuid4().hex[:6]}9"
    reg = await client.post(
        "/api/v1/users/auth/register", json={"email": email, "password": password, "full_name": "Birim Fiyat"}
    )
    assert reg.status_code in (200, 201), reg.text
    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(role="admin", is_active=True))
        await s.commit()
    login = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _bill(client: AsyncClient, headers: dict[str, str]) -> str:
    project = await client.post(
        "/api/v1/projects/",
        json={
            "name": f"Birim {uuid.uuid4().hex[:6]}",
            "region": "TR",
            "currency": "TRY",
            "validation_rule_sets": ["boq_quality", "birimfiyat"],
        },
        headers=headers,
    )
    assert project.status_code in (200, 201), project.text
    boq = await client.post(
        "/api/v1/boq/boqs/", json={"project_id": project.json()["id"], "name": "Metraj"}, headers=headers
    )
    assert boq.status_code in (200, 201), boq.text
    boq_id = boq.json()["id"]
    line = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/positions/",
        json={
            "boq_id": boq_id,
            "ordinal": "01",
            "description": "Betonarme",
            "unit": "m3",
            "quantity": "10",
            "unit_rate": "1000",
        },
        headers=headers,
    )
    assert line.status_code == 201, line.text
    markup = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/markups/",
        json={"name": "Müteahhit kârı ve genel giderler", "category": "overhead", "percentage": "25"},
        headers=headers,
    )
    assert markup.status_code in (200, 201), markup.text
    return boq_id


async def _findings(client: AsyncClient, headers: dict[str, str], boq_id: str) -> list[dict[str, Any]]:
    resp = await client.post(f"/api/v1/boq/boqs/{boq_id}/validate/", headers=headers)
    assert resp.status_code == 200, resp.text
    return [r for r in resp.json()["results"] if r["rule_id"] == RULE]


@pytest.mark.asyncio
async def test_the_statement_on_the_bill_reports_the_second_profit_line(client, headers) -> None:
    boq_id = await _bill(client, headers)
    assert await _findings(client, headers, boq_id) == []

    patched = await client.patch(
        f"/api/v1/boq/boqs/{boq_id}", json={"metadata": {"priced_from_published_rates": True}}, headers=headers
    )
    assert patched.status_code == 200, patched.text

    findings = await _findings(client, headers, boq_id)
    assert [f["passed"] for f in findings] == [False], findings
    assert "25" in findings[0]["message"]
