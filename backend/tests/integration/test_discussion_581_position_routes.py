"""Routes of discussion 581 over the real app: save a position as a cost item,
refresh it, check the composition, replace a resource row by a matched item."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(scope="module")
async def client():
    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        from app.database import Base, engine

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac


@pytest_asyncio.fixture(scope="module")
async def headers(client):
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    tag = uuid.uuid4().hex[:8]
    email, password = f"d581-{tag}@test.io", f"D581Test{tag}9!"
    reg = await client.post(
        "/api/v1/users/auth/register", json={"email": email, "password": password, "full_name": "Estimator"}
    )
    assert reg.status_code in (200, 201), reg.text
    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(role="admin", is_active=True))
        await s.commit()
    login = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _position(client, headers, *, unit="m2", unit_rate="95", resources=None):
    proj = await client.post("/api/v1/projects/", headers=headers, json={"name": f"P-{uuid.uuid4().hex[:6]}"})
    assert proj.status_code in (200, 201), proj.text
    boq = await client.post(
        "/api/v1/boq/boqs/", headers=headers, json={"project_id": proj.json()["id"], "name": "Bill"}
    )
    assert boq.status_code in (200, 201), boq.text
    rows = (
        resources
        if resources is not None
        else [
            {"name": "Mason", "code": "L1", "type": "labor", "unit": "h", "quantity": 2, "unit_rate": 40},
            {"name": "Cement", "code": "M1", "type": "material", "unit": "kg", "quantity": 0.5, "unit_rate": 30},
        ]
    )
    pos = await client.post(
        f"/api/v1/boq/boqs/{boq.json()['id']}/positions/",
        headers=headers,
        json={
            "boq_id": boq.json()["id"],
            "ordinal": "01.001",
            "description": "Brick wall",
            "unit": unit,
            "quantity": 10,
            "unit_rate": unit_rate,
            "metadata": {"resources": rows},
        },
    )
    assert pos.status_code in (200, 201), pos.text
    return pos.json()


async def test_composition_route_reports_stored_vs_derived(client, headers):
    pos = await _position(client, headers)
    r = await client.get(f"/api/v1/boq/positions/{pos['id']}/composition/", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert Decimal(body["derived_unit_rate"]) == Decimal("95")
    assert body["coherent"] is True
    assert len(body["components"]) == 2


async def test_composition_of_a_stranger_position_is_404(client, headers):
    r = await client.get(f"/api/v1/boq/positions/{uuid.uuid4()}/composition/", headers=headers)
    assert r.status_code == 404


async def test_save_refresh_and_conflict(client, headers):
    pos = await _position(client, headers)
    created = await client.post(f"/api/v1/costs/from-boq-position/{pos['id']}/", headers=headers, json={})
    assert created.status_code == 201, created.text
    item = created.json()
    assert item["description"] == "Brick wall"
    assert len(item["components"]) == 2
    assert item["region"] == "CUSTOM"
    again = await client.post(f"/api/v1/costs/from-boq-position/{pos['id']}/", headers=headers, json={})
    assert again.status_code == 409
    refreshed = await client.put(
        f"/api/v1/costs/from-boq-position/{item['id']}/", headers=headers, json={"position_id": pos["id"]}
    )
    assert refreshed.status_code == 200, refreshed.text
    assert Decimal(refreshed.json()["rate"]) == Decimal("95")


async def test_a_section_cannot_be_saved(client, headers):
    pos = await _position(client, headers, unit="section", unit_rate="0", resources=[])
    r = await client.post(f"/api/v1/costs/from-boq-position/{pos['id']}/", headers=headers, json={})
    assert r.status_code == 422


async def test_replace_resource_by_matched_item_keeps_quantity_and_rederives_rate(client, headers):
    pos = await _position(client, headers)
    cost = await client.post(
        "/api/v1/costs/",
        headers=headers,
        json={
            "code": f"R-{uuid.uuid4().hex[:6]}",
            "description": "Mason skilled",
            "unit": "h",
            "rate": "50",
            "region": "CUSTOM",
            "source": "custom",
        },
    )
    assert cost.status_code == 201, cost.text
    r = await client.post(
        f"/api/v1/boq/positions/{pos['id']}/resources/0/replace/",
        headers=headers,
        json={"cost_item_id": cost.json()["id"], "score": 0.82},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    row = body["metadata"]["resources"][0]
    assert row["name"] == "Mason skilled" and Decimal(str(row["quantity"])) == 2
    assert row["replaced_by_match"]["score"] == 0.82
    assert Decimal(str(body["unit_rate"])) == Decimal("115")  # 2*50 + 0.5*30
    out = await client.post(
        f"/api/v1/boq/positions/{pos['id']}/resources/9/replace/",
        headers=headers,
        json={"cost_item_id": cost.json()["id"]},
    )
    assert out.status_code == 422
