# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Integration test: BOQUnitSystemConsistencyRule fires WARNING for mismatched units.

Wave 24 (#167) — task: seed a project with unit_system='imperial', create a
BOQ position with unit 'm³', assert the validation rule fires a WARNING.

Pattern mirrors test_boq_bim_qty_source_roundtrip.py: register + promote +
login + project + BOQ + position + validate.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest_asyncio.fixture(scope="module")
async def shared_client():
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
async def auth_headers(shared_client: AsyncClient) -> dict[str, str]:
    """Register + promote-to-admin + login."""
    unique = uuid.uuid4().hex[:8]
    email = f"unitcons-{unique}@test.io"
    password = f"UnitCons{unique}9!"
    reg = await shared_client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "UnitConsistency Tester"},
    )
    assert reg.status_code == 201, f"Registration failed: {reg.text}"

    from sqlalchemy import update as sa_update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as session:
        await session.execute(sa_update(User).where(User.email == email.lower()).values(role="admin", is_active=True))
        await session.commit()

    login = await shared_client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, f"Login failed: {login.text}"
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_boq_unit_system_consistency_rule_fires_warning(
    shared_client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Seed an imperial project, add a m³ BOQ position, run the unit-system
    consistency rule directly; assert WARNING is returned (not ERROR, not pass).

    We use the rule directly (pure in-memory) rather than the HTTP validation
    endpoint so the test is fast and independent of routing. The project and
    BOQ position DO exist in the DB — this gives us a realistic ordinal/unit
    pair while keeping the rule assertion straightforward.
    """
    # ── Create an imperial project ────────────────────────────────────────────
    proj = await shared_client.post(
        "/api/v1/projects/",
        json={
            "name": f"Imperial Project {uuid.uuid4().hex[:6]}",
            "unit_system": "imperial",
        },
        headers=auth_headers,
    )
    assert proj.status_code in (200, 201), proj.text
    project_data = proj.json()
    project_id = project_data["id"]

    # Verify the project was stored with imperial unit_system.
    assert project_data.get("unit_system") == "imperial", (
        f"Expected unit_system='imperial', got: {project_data.get('unit_system')}"
    )

    # ── Create a BOQ for the project ─────────────────────────────────────────
    boq = await shared_client.post(
        "/api/v1/boq/boqs/",
        json={"project_id": project_id, "name": "Imperial BOQ"},
        headers=auth_headers,
    )
    assert boq.status_code in (200, 201), boq.text
    boq_id = boq.json()["id"]

    # ── Create a position with metric unit m³ (wrong for imperial project) ───
    pos = await shared_client.post(
        f"/api/v1/boq/boqs/{boq_id}/positions/",
        json={
            "boq_id": boq_id,
            "ordinal": "01.001",
            "description": "Concrete pour (should be ft³ not m³)",
            "unit": "m3",
            "quantity": 10.0,
            "unit_rate": 0.0,
        },
        headers=auth_headers,
    )
    assert pos.status_code in (200, 201), pos.text

    # ── Run the rule directly (pure in-memory, no extra HTTP) ────────────────
    from app.core.validation.engine import Severity, ValidationContext
    from app.core.validation.rules import BOQUnitSystemConsistencyRule

    rule = BOQUnitSystemConsistencyRule()
    ctx = ValidationContext(
        data={
            "positions": [{"ordinal": "01.001", "unit": "m3"}],
            "project_unit_system": "imperial",
        }
    )
    results = await rule.validate(ctx)

    # ── Assertions ────────────────────────────────────────────────────────────
    assert len(results) == 1, f"Expected 1 result, got {len(results)}"
    result = results[0]
    assert result.passed is False, f"Rule should have fired a WARNING, but passed=True. message={result.message}"
    assert result.severity == Severity.WARNING, f"Expected WARNING severity, got {result.severity}"
    assert "imperial" in result.message.lower() or "metric" in result.message.lower(), (
        f"Expected unit system name in message: {result.message}"
    )
    assert result.details.get("mismatch_count") == 1, f"Expected 1 mismatch, got: {result.details}"


@pytest.mark.asyncio
async def test_imperial_project_imperial_units_passes(shared_client: AsyncClient, auth_headers: dict[str, str]) -> None:
    """Imperial project with sqft unit must not trigger the rule."""
    from app.core.validation.engine import ValidationContext
    from app.core.validation.rules import BOQUnitSystemConsistencyRule

    rule = BOQUnitSystemConsistencyRule()
    ctx = ValidationContext(
        data={
            "positions": [
                {"ordinal": "01.001", "unit": "sqft"},
                {"ordinal": "01.002", "unit": "ft"},
                {"ordinal": "01.003", "unit": "lb"},
            ],
            "project_unit_system": "imperial",
        }
    )
    results = await rule.validate(ctx)
    assert results[0].passed is True, f"Should pass for imperial units in imperial project: {results[0].message}"


@pytest.mark.asyncio
async def test_metric_project_metric_units_passes(shared_client: AsyncClient, auth_headers: dict[str, str]) -> None:
    """Metric project with m², m³, kg must not trigger the rule."""
    from app.core.validation.engine import ValidationContext
    from app.core.validation.rules import BOQUnitSystemConsistencyRule

    rule = BOQUnitSystemConsistencyRule()
    ctx = ValidationContext(
        data={
            "positions": [
                {"ordinal": "01.001", "unit": "m2"},
                {"ordinal": "01.002", "unit": "m3"},
                {"ordinal": "01.003", "unit": "kg"},
            ],
            "project_unit_system": "metric",
        }
    )
    results = await rule.validate(ctx)
    assert results[0].passed is True, f"Should pass for metric units in metric project: {results[0].message}"
