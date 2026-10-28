"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Integration tests for the 6D Phase 2 whole-life endpoints.

Drives the full HTTP stack against ``create_app()`` so routing, permission
gating and the project-access (IDOR) check are exercised. BIM elements are
seeded directly via ORM (the upload pipeline is out of scope here); the EPD,
the inventory and every whole-life action go through the public API. Covers the
operational-carbon (B6) compute, the ISO 15686-5 whole-life cost compute, the
draft/confirm workflow, the combined whole-life rollup and an IDOR denial.

CI only: this needs the full app plus PostgreSQL, so it runs on Python 3.12 in
CI, not on the local 3.11 runner. The discounting / replacement-cycle /
service-life / rollup math is covered DB-free in
``tests/unit/test_carbon_whole_life.py``.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update as sa_update

from app.database import async_session_factory
from app.main import create_app
from app.modules.bim_hub.models import BIMElement, BIMModel
from app.modules.users.models import User

# Grid factor for DE/2023 in the built-in catalogue is 0.38 kgCO2e/kWh.
_GRID_FACTOR = Decimal("0.38")
_ANNUAL_KWH = Decimal("10000")
_STUDY_PERIOD = 60
# B6 = annual energy x grid factor x study period.
_EXPECTED_B6 = _ANNUAL_KWH * _GRID_FACTOR * _STUDY_PERIOD  # 228000
_HVAC_CAPEX = Decimal("50000")
_MANUAL_CAPEX = Decimal("200000")


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


async def _register(client: AsyncClient, prefix: str, role: str) -> dict[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"{prefix}-{unique}@test.io"
    password = f"WLife{unique}9!"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "Whole-Life Tester"},
    )
    assert reg.status_code in (200, 201), f"register failed: {reg.text}"
    async with async_session_factory() as session:
        await session.execute(
            sa_update(User).where(User.email == email.lower()).values(role=role, is_active=True),
        )
        await session.commit()
    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, f"login failed: {login.text}"
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest_asyncio.fixture(scope="module")
async def admin_headers(shared_client: AsyncClient) -> dict[str, str]:
    return await _register(shared_client, "wlife-admin", "admin")


async def _create_project(client: AsyncClient, headers: dict[str, str]) -> str:
    resp = await client.post(
        "/api/v1/projects/",
        json={"name": "Whole-Life Project", "region": "DACH", "currency": "EUR"},
        headers=headers,
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


async def _seed_bim(project_id: str) -> str:
    """Seed one HVAC asset (energy + capex + service life) and one bare wall.

    Returns the HVAC element id so the tests can assert the derived operational
    and cost entries link back to it.
    """
    async with async_session_factory() as session:
        model = BIMModel(project_id=uuid.UUID(project_id), name="MEP.ifc", status="ready")
        session.add(model)
        await session.flush()
        hvac = BIMElement(
            model_id=model.id,
            stable_id="AHU-01",
            element_type="AirHandlingUnit",
            name="AHU 01",
            properties={"material": "steel"},
            quantities={"area_m2": "2.0"},
            asset_info={
                "annual_energy_kwh": str(_ANNUAL_KWH),
                "service_life_years": "20",
                "capex": str(_HVAC_CAPEX),
            },
            is_tracked_asset=True,
        )
        wall = BIMElement(
            model_id=model.id,
            stable_id="WALL-01",
            element_type="Wall",
            name="Plain Wall",
            properties={"material": "concrete"},
            quantities={"volume_m3": "9"},
        )
        session.add_all([hvac, wall])
        await session.flush()
        hvac_id = str(hvac.id)
        await session.commit()
    return hvac_id


async def _create_inventory(client: AsyncClient, headers: dict[str, str], project_id: str) -> str:
    resp = await client.post(
        "/api/v1/carbon/inventories",
        json={"project_id": project_id, "name": "Whole-Life Inventory", "scope": "cradle_to_grave"},
        headers=headers,
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_operational_carbon_compute_and_rollup(
    shared_client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    """B6: dry-run, persist, fold into totals, idempotent re-run."""
    project_id = await _create_project(shared_client, admin_headers)
    hvac_id = await _seed_bim(project_id)
    inventory_id = await _create_inventory(shared_client, admin_headers, project_id)
    url = f"/api/v1/carbon/inventories/{inventory_id}/operational-carbon/compute"
    body = {"grid_country": "DE", "grid_year": 2023, "study_period_years": _STUDY_PERIOD}

    # 1) Dry-run proposes the HVAC line, persists nothing, skips the bare wall.
    dry = await shared_client.post(f"{url}?dry_run=true", json=body, headers=admin_headers)
    assert dry.status_code == 200, dry.text
    dry_body = dry.json()
    assert dry_body["dry_run"] is True
    assert dry_body["created"] == 0
    assert dry_body["skipped_no_energy"] >= 1
    assert Decimal(str(dry_body["grid_factor_kg_co2e_per_kwh"])) == _GRID_FACTOR
    assert len(dry_body["entries"]) == 1
    proposal = dry_body["entries"][0]
    assert proposal["element_id"] == hvac_id
    assert proposal["match_confidence"] == "high"
    assert proposal["stage"] == "b6"
    assert Decimal(str(proposal["carbon_kg"])) == _EXPECTED_B6

    listed = await shared_client.get(
        f"/api/v1/carbon/inventories/{inventory_id}/operational-carbon",
        headers=admin_headers,
    )
    assert listed.json() == []

    # 2) Real run persists exactly one draft, needs-review entry.
    real = await shared_client.post(url, json=body, headers=admin_headers)
    assert real.status_code == 200, real.text
    assert real.json()["created"] == 1

    rows = (
        await shared_client.get(
            f"/api/v1/carbon/inventories/{inventory_id}/operational-carbon",
            headers=admin_headers,
        )
    ).json()
    assert len(rows) == 1
    assert rows[0]["status"] == "draft"
    assert rows[0]["element_id"] == hvac_id
    assert Decimal(str(rows[0]["carbon_kg"])) == _EXPECTED_B6

    # 3) B6 folds into the EN 15978 B stage of the inventory totals.
    totals = (
        await shared_client.get(
            f"/api/v1/carbon/inventories/{inventory_id}/totals",
            headers=admin_headers,
        )
    ).json()
    assert Decimal(str(totals["b6_operational"])) == _EXPECTED_B6
    assert Decimal(str(totals["embodied_b"])) == _EXPECTED_B6
    assert Decimal(str(totals["total"])) == _EXPECTED_B6

    # 4) Idempotent: re-running never double-counts the already-linked asset.
    again = await shared_client.post(url, json=body, headers=admin_headers)
    assert again.json()["created"] == 0
    assert again.json()["skipped_existing"] == 1


@pytest.mark.asyncio
async def test_life_cycle_cost_compute_confirm_and_whole_life(
    shared_client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    """ISO 15686-5: BIM-derived + manual lines, confirm, whole-life rollup."""
    project_id = await _create_project(shared_client, admin_headers)
    hvac_id = await _seed_bim(project_id)
    inventory_id = await _create_inventory(shared_client, admin_headers, project_id)

    # Operational carbon first, so the whole-life rollup has a B6 figure.
    await shared_client.post(
        f"/api/v1/carbon/inventories/{inventory_id}/operational-carbon/compute",
        json={"grid_country": "DE", "grid_year": 2023, "study_period_years": _STUDY_PERIOD},
        headers=admin_headers,
    )

    lcc_url = f"/api/v1/carbon/inventories/{inventory_id}/life-cycle-cost/compute"
    lcc_body = {
        "discount_rate": "0.035",
        "study_period_years": _STUDY_PERIOD,
        "currency": "EUR",
        "lines": [
            {
                "description": "Facade system",
                "category": "envelope",
                "capex": str(_MANUAL_CAPEX),
                "service_life_years": 30,
            },
        ],
    }

    # BIM-derived line (HVAC has capex + service life on its asset register) plus
    # the explicit manual facade line. The bare wall carries no cost -> skipped.
    real = await shared_client.post(lcc_url, json=lcc_body, headers=admin_headers)
    assert real.status_code == 200, real.text
    real_body = real.json()
    assert real_body["created"] == 2
    assert real_body["skipped_no_cost"] >= 1

    rows = (
        await shared_client.get(
            f"/api/v1/carbon/inventories/{inventory_id}/life-cycle-cost",
            headers=admin_headers,
        )
    ).json()
    assert len(rows) == 2
    by_element = {r["element_id"]: r for r in rows}
    hvac_row = by_element[hvac_id]
    assert hvac_row["confidence"] == "high"
    assert Decimal(str(hvac_row["capex"])) == _HVAC_CAPEX
    # Service life 20 over a 60-year study -> replacements at 20 and 40.
    assert hvac_row["replacement_count"] == 2
    assert Decimal(str(hvac_row["whole_life_cost"])) > _HVAC_CAPEX
    assert hvac_row["status"] == "draft"
    manual_row = by_element[None]
    assert manual_row["source"] == "manual"
    assert Decimal(str(manual_row["capex"])) == _MANUAL_CAPEX

    # Human confirmation: flip the HVAC line to 'confirmed'.
    confirm = await shared_client.post(
        f"/api/v1/carbon/life-cycle-cost/{hvac_row['id']}/confirm",
        headers=admin_headers,
    )
    assert confirm.status_code == 200, confirm.text
    assert confirm.json()["status"] == "confirmed"

    # Whole-life rollup: carbon and cost side by side, with coverage.
    wl = await shared_client.get(
        f"/api/v1/carbon/inventories/{inventory_id}/whole-life?carbon_price_per_tonne=50",
        headers=admin_headers,
    )
    assert wl.status_code == 200, wl.text
    wl_body = wl.json()
    assert Decimal(str(wl_body["carbon"]["b6_operational"])) == _EXPECTED_B6
    assert Decimal(str(wl_body["carbon"]["b_total"])) == _EXPECTED_B6
    assert Decimal(str(wl_body["cost"]["capex"])) == _HVAC_CAPEX + _MANUAL_CAPEX
    assert Decimal(str(wl_body["cost"]["whole_life_cost"])) > Decimal("0")
    assert wl_body["cost"]["currency"] == "EUR"
    assert wl_body["coverage"]["bim_element_count"] == 2
    assert wl_body["coverage"]["lcc_linked_count"] == 1
    assert wl_body["coverage"]["operational_linked_count"] == 1
    # Monetised whole-life carbon = whole_life_total / 1000 x price.
    expected_carbon_cost = Decimal(str(wl_body["carbon"]["whole_life_total"])) / Decimal("1000") * Decimal("50")
    assert Decimal(str(wl_body["cost_of_whole_life_carbon"])) == expected_carbon_cost


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_whole_life_denies_foreign_project(
    shared_client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    """A non-owner cannot compute or read whole-life data for a foreign project."""
    project_id = await _create_project(shared_client, admin_headers)
    inventory_id = await _create_inventory(shared_client, admin_headers, project_id)
    attacker = await _register(shared_client, "wlife-mgr", "manager")

    compute = await shared_client.post(
        f"/api/v1/carbon/inventories/{inventory_id}/operational-carbon/compute",
        json={"grid_country": "DE", "grid_year": 2023},
        headers=attacker,
    )
    assert compute.status_code in (403, 404), compute.text

    rollup = await shared_client.get(
        f"/api/v1/carbon/inventories/{inventory_id}/whole-life",
        headers=attacker,
    )
    assert rollup.status_code in (403, 404), rollup.text
