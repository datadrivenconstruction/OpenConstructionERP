# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Integration test: takeoff service raises 422 unit_system_mismatch.

Wave 24 (#167) — assert that persisting a metric takeoff measurement into
an imperial project raises HTTP 422 with code='unit_system_mismatch'.

The test calls TakeoffService.create_measurement() directly (not via HTTP)
so it gets a real DB-backed session but avoids routing concerns. The project
row's unit_system column is written directly via SA to keep the test concise
without depending on the project HTTP API.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest_asyncio.fixture(scope="module")
async def app_client():
    app = create_app()

    @asynccontextmanager
    async def lifespan_ctx():
        async with app.router.lifespan_context(app):
            yield

    async with lifespan_ctx():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest_asyncio.fixture(scope="module")
async def auth_headers(app_client: AsyncClient) -> dict[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"takeoff-mismatch-{unique}@test.io"
    password = f"Takeoff{unique}9!"
    reg = await app_client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "Takeoff Mismatch Tester"},
    )
    assert reg.status_code == 201, reg.text

    from sqlalchemy import update as sa_update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as session:
        await session.execute(sa_update(User).where(User.email == email.lower()).values(role="admin", is_active=True))
        await session.commit()

    login = await app_client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_metric_takeoff_in_imperial_project_raises_422(
    app_client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Persisting a metric measurement into an imperial project must raise 422
    with code='unit_system_mismatch'.
    """
    from fastapi import HTTPException

    from app.database import async_session_factory
    from app.modules.takeoff.schemas import TakeoffMeasurementCreate
    from app.modules.takeoff.service import TakeoffService

    # ── Create an imperial project via API ───────────────────────────────────
    proj_resp = await app_client.post(
        "/api/v1/projects/",
        json={
            "name": f"Imperial Project TakeoffTest {uuid.uuid4().hex[:6]}",
            "unit_system": "imperial",
        },
        headers=auth_headers,
    )
    assert proj_resp.status_code in (200, 201), proj_resp.text
    project_id = uuid.UUID(proj_resp.json()["id"])

    # ── Build a metric measurement payload ────────────────────────────────────
    data = TakeoffMeasurementCreate(
        project_id=project_id,
        type="area",
        measurement_unit="m2",
        group_name="General",
        points=[],
        measurement_value=25.0,
    )

    # ── Call TakeoffService with source_unit_system='metric' ─────────────────
    async with async_session_factory() as session:
        svc = TakeoffService(session)
        with pytest.raises(HTTPException) as exc_info:
            await svc.create_measurement(
                data,
                created_by="test",
                source_unit_system="metric",
            )

    # ── Assert 422 with correct code ──────────────────────────────────────────
    exc = exc_info.value
    assert exc.status_code == 422, f"Expected HTTP 422, got {exc.status_code}"
    detail = exc.detail
    assert isinstance(detail, dict), f"Expected dict detail, got: {type(detail)}"
    assert detail.get("code") == "unit_system_mismatch", f"Expected code='unit_system_mismatch', got: {detail}"
    assert detail.get("source_unit_system") == "metric", detail
    assert detail.get("project_unit_system") == "imperial", detail


@pytest.mark.asyncio
async def test_same_unit_system_does_not_raise(app_client: AsyncClient, auth_headers: dict[str, str]) -> None:
    """Metric measurement into a metric project must NOT raise."""
    from app.database import async_session_factory
    from app.modules.takeoff.schemas import TakeoffMeasurementCreate
    from app.modules.takeoff.service import TakeoffService

    proj_resp = await app_client.post(
        "/api/v1/projects/",
        json={
            "name": f"Metric Project TakeoffTest {uuid.uuid4().hex[:6]}",
            "unit_system": "metric",
        },
        headers=auth_headers,
    )
    assert proj_resp.status_code in (200, 201), proj_resp.text
    project_id = uuid.UUID(proj_resp.json()["id"])

    data = TakeoffMeasurementCreate(
        project_id=project_id,
        type="area",
        measurement_unit="m2",
        group_name="General",
        points=[],
        measurement_value=15.0,
    )

    async with async_session_factory() as session:
        svc = TakeoffService(session)
        # Should not raise — same system
        result = await svc.create_measurement(
            data,
            created_by="test",
            source_unit_system="metric",
        )
    assert result is not None


@pytest.mark.asyncio
async def test_no_source_unit_system_never_raises(app_client: AsyncClient, auth_headers: dict[str, str]) -> None:
    """When source_unit_system is not supplied the gate is skipped entirely."""
    from app.database import async_session_factory
    from app.modules.takeoff.schemas import TakeoffMeasurementCreate
    from app.modules.takeoff.service import TakeoffService

    proj_resp = await app_client.post(
        "/api/v1/projects/",
        json={
            "name": f"Imperial No-Source Test {uuid.uuid4().hex[:6]}",
            "unit_system": "imperial",
        },
        headers=auth_headers,
    )
    assert proj_resp.status_code in (200, 201), proj_resp.text
    project_id = uuid.UUID(proj_resp.json()["id"])

    data = TakeoffMeasurementCreate(
        project_id=project_id,
        type="area",
        measurement_unit="m2",
        group_name="General",
        points=[],
        measurement_value=10.0,
    )

    async with async_session_factory() as session:
        svc = TakeoffService(session)
        # No source_unit_system → gate is skipped → should not raise
        result = await svc.create_measurement(data, created_by="test")
    assert result is not None
