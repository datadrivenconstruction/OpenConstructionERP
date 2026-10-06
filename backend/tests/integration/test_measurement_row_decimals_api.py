# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The measurement routes total a sheet with the line rounding stored on it.

A sheet saved with ``row_decimals`` (``metadata.measurement.row_decimals``)
rounds every line before adding them; the read route and the compute route
both have to use it, or the drawer shows one total and the position holds
another. Ten lines of 1.005 under a two-decimal rule are 10.10, the quantity
the position carries.

Run:
    cd backend
    python -m pytest tests/integration/test_measurement_row_decimals_api.py -v
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

import app.modules.boq.models  # noqa: F401
import app.modules.projects.models  # noqa: F401
import app.modules.teams.models  # noqa: F401
import app.modules.users.models  # noqa: F401

_LINES = [{"description": f"row {n}", "formula": "L", "variables": {"L": "1.005"}} for n in range(1, 11)]


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    fastapi_app = create_app()
    async with fastapi_app.router.lifespan_context(fastapi_app):
        from app.database import Base, engine

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield fastapi_app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture(scope="module")
async def auth_headers(http_client) -> dict[str, str]:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    email = f"measure-{uuid.uuid4().hex[:8]}@row-decimals.io"
    password = f"Measure{uuid.uuid4().hex[:6]}9"
    reg = await http_client.post(
        "/api/v1/users/auth/register", json={"email": email, "password": password, "full_name": "Measure"}
    )
    assert reg.status_code in (200, 201), reg.text[:300]
    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(is_active=True, role="admin"))
        await s.commit()
    login = await http_client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text[:300]
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _position(http_client, auth_headers, measurement: dict, quantity: str) -> str:
    project = await http_client.post(
        "/api/v1/projects/",
        json={"name": f"Misure {uuid.uuid4().hex[:6]}", "region": "IT", "currency": "EUR"},
        headers=auth_headers,
    )
    assert project.status_code == 201, project.text[:300]
    boq = await http_client.post(
        "/api/v1/boq/boqs/", json={"project_id": project.json()["id"], "name": "Computo"}, headers=auth_headers
    )
    assert boq.status_code == 201, boq.text[:300]
    boq_id = boq.json()["id"]
    pos = await http_client.post(
        f"/api/v1/boq/boqs/{boq_id}/positions/",
        json={
            "boq_id": boq_id,
            "ordinal": "1",
            "description": "Intonaco",
            "unit": "m2",
            "quantity": quantity,
            "unit_rate": "10",
            "metadata": {"measurement": measurement},
        },
        headers=auth_headers,
    )
    assert pos.status_code == 201, pos.text[:300]
    return pos.json()["id"]


@pytest.mark.asyncio
async def test_a_stored_sheet_is_read_and_reconciled_with_its_line_rounding(http_client, auth_headers) -> None:
    pid = await _position(http_client, auth_headers, {"unit": "m2", "lines": _LINES, "row_decimals": 2}, "10.10")
    resp = await http_client.get(f"/api/v1/boq/positions/{pid}/measurement/", headers=auth_headers)
    assert resp.status_code == 200, resp.text[:300]
    body = resp.json()
    assert Decimal(body["total_quantity"]) == Decimal("10.10")
    assert body["row_decimals"] == 2
    assert body["reconciliation"]["matches"] is True
    assert body["lines"][0]["formula"] == "L"
    assert Decimal(body["lines"][0]["quantity"]) == Decimal("1.01")


@pytest.mark.asyncio
async def test_a_stored_sheet_without_the_rule_totals_as_before(http_client, auth_headers) -> None:
    pid = await _position(http_client, auth_headers, {"unit": "m2", "lines": _LINES}, "10.05")
    body = (await http_client.get(f"/api/v1/boq/positions/{pid}/measurement/", headers=auth_headers)).json()
    assert Decimal(body["total_quantity"]) == Decimal("10.050")
    assert body["reconciliation"]["matches"] is True


@pytest.mark.asyncio
async def test_the_compute_route_applies_the_rule_it_is_sent(http_client, auth_headers) -> None:
    pid = await _position(http_client, auth_headers, {"unit": "m2", "lines": _LINES, "row_decimals": 2}, "10.10")
    resp = await http_client.post(
        f"/api/v1/boq/positions/{pid}/measurement/compute/",
        json={"lines": _LINES, "row_decimals": 2, "strict": False},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text[:300]
    assert Decimal(resp.json()["total_quantity"]) == Decimal("10.10")
    assert resp.json()["reconciliation"]["matches"] is True


@pytest.mark.asyncio
async def test_the_csv_download_shows_the_rounded_lines(http_client, auth_headers) -> None:
    pid = await _position(http_client, auth_headers, {"unit": "m2", "lines": _LINES, "row_decimals": 2}, "10.10")
    resp = await http_client.get(f"/api/v1/boq/positions/{pid}/measurement/?format=csv", headers=auth_headers)
    assert resp.status_code == 200, resp.text[:300]
    assert ",10.100," in resp.text
