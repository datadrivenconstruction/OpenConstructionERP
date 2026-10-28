"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Integration tests for the 6D carbon auto-enrichment endpoint.

Drives the full HTTP stack against ``create_app()`` so routing, permission
gating and the project-access (IDOR) check are all exercised. BIM elements
are seeded directly via ORM (the BIM upload pipeline is heavy and out of
scope here); the EPD and the inventory are created through the public API,
then ``POST /api/v1/carbon/inventories/{id}/auto-enrich-bim`` is exercised
end to end - dry-run, real run, rollup and idempotency.

CI only: this needs the full app plus PostgreSQL, so it runs on Python 3.12
in CI, not on the local 3.11 runner. The pure matching / scoring / rollup
logic is covered DB-free in ``tests/unit/test_carbon_6d.py``.

A unique material class (``cx6dconc``) keeps the match isolated from any EPD
another test may have created in the shared database.
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

# Unique tokens so the match cannot collide with EPDs seeded by other tests.
_MATCH_MATERIAL = "cx6dconc"
_NOMATCH_MATERIAL = "cx6dnope"
# EPD is declared per m3; the matched element carries 9 m3 -> 9 * 100 = 900.
_GWP_A1A3 = Decimal("100")
_VOLUME_M3 = Decimal("9")
_EXPECTED_CARBON = _GWP_A1A3 * _VOLUME_M3  # 900 kgCO2e


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
    """Register a user, force ``role``, and return bearer auth headers."""
    unique = uuid.uuid4().hex[:8]
    email = f"{prefix}-{unique}@test.io"
    password = f"Carb6D{unique}9!"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "Carbon 6D Tester"},
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
    return await _register(shared_client, "carb6d-admin", "admin")


async def _create_project(client: AsyncClient, headers: dict[str, str]) -> str:
    resp = await client.post(
        "/api/v1/projects/",
        json={"name": "Carbon 6D Project", "region": "DACH", "currency": "EUR"},
        headers=headers,
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


async def _seed_bim(project_id: str) -> str:
    """Seed one model with a matchable concrete element + an unmatchable one.

    Returns the ``stable_id``-bearing concrete element's id (as a string) so
    the test can assert the created carbon entry links back to it.
    """
    async with async_session_factory() as session:
        model = BIMModel(project_id=uuid.UUID(project_id), name="Structure.ifc", status="ready")
        session.add(model)
        await session.flush()
        concrete = BIMElement(
            model_id=model.id,
            stable_id="WALL-6D-01",
            element_type="Wall",
            name="Concrete Wall 6D",
            properties={"material": _MATCH_MATERIAL},
            quantities={"volume_m3": str(_VOLUME_M3)},
        )
        session.add_all(
            [
                concrete,
                BIMElement(
                    model_id=model.id,
                    stable_id="WALL-6D-02",
                    element_type="Wall",
                    name="Unmatched Wall 6D",
                    properties={"material": _NOMATCH_MATERIAL},
                    quantities={"volume_m3": "3"},
                ),
            ],
        )
        await session.flush()
        element_id = str(concrete.id)
        await session.commit()
    return element_id


async def _create_epd(client: AsyncClient, headers: dict[str, str]) -> str:
    resp = await client.post(
        "/api/v1/carbon/epd",
        json={
            "epd_id": f"EPD-6D-{uuid.uuid4().hex[:8]}",
            "source": "custom",
            "material_class": _MATCH_MATERIAL,
            "product_name": "Test Concrete 6D",
            "declared_unit": "m3",
            "gwp_a1a3": str(_GWP_A1A3),
            "region": "",
        },
        headers=headers,
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


async def _create_inventory(client: AsyncClient, headers: dict[str, str], project_id: str) -> str:
    resp = await client.post(
        "/api/v1/carbon/inventories",
        json={"project_id": project_id, "name": "6D Test Inventory", "scope": "cradle_to_gate"},
        headers=headers,
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_auto_enrich_links_carbon_and_rolls_up(
    shared_client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    """End-to-end: dry-run, persist, rollup, idempotent re-run."""
    project_id = await _create_project(shared_client, admin_headers)
    concrete_id = await _seed_bim(project_id)
    await _create_epd(shared_client, admin_headers)
    inventory_id = await _create_inventory(shared_client, admin_headers, project_id)
    enrich_url = f"/api/v1/carbon/inventories/{inventory_id}/auto-enrich-bim"

    # 1) Dry-run proposes but persists nothing (AI suggests, human confirms).
    dry = await shared_client.post(f"{enrich_url}?dry_run=true", headers=admin_headers)
    assert dry.status_code == 200, dry.text
    dry_body = dry.json()
    assert dry_body["dry_run"] is True
    assert dry_body["created"] == 0
    assert dry_body["skipped_no_match"] >= 1  # the unmatchable element
    proposals = dry_body["entries"]
    assert len(proposals) == 1, dry_body
    proposal = proposals[0]
    assert proposal["element_id"] == concrete_id
    assert proposal["source"] == "auto_enriched"
    assert proposal["match_confidence"] == "high"
    assert proposal["stage"] == "a1a3"
    assert Decimal(str(proposal["carbon_kg"])) == _EXPECTED_CARBON

    # Nothing was written on the dry run.
    listed = await shared_client.get(
        f"/api/v1/carbon/inventories/{inventory_id}/embodied",
        headers=admin_headers,
    )
    assert listed.status_code == 200, listed.text
    assert listed.json() == []

    # 2) Real run persists exactly one linked, needs-review entry.
    real = await shared_client.post(enrich_url, headers=admin_headers)
    assert real.status_code == 200, real.text
    real_body = real.json()
    assert real_body["dry_run"] is False
    assert real_body["created"] == 1

    rows = (
        await shared_client.get(
            f"/api/v1/carbon/inventories/{inventory_id}/embodied",
            headers=admin_headers,
        )
    ).json()
    assert len(rows) == 1
    row = rows[0]
    assert row["element_id"] == concrete_id
    assert row["source"] == "auto_enriched"
    assert row["match_confidence"] == "high"
    assert row["stage"] == "a1a3"
    assert Decimal(str(row["carbon_kg"])) == _EXPECTED_CARBON

    # 3) EN 15978 rollup: the linked A1-A3 entry rolls into the inventory total.
    totals = await shared_client.get(
        f"/api/v1/carbon/inventories/{inventory_id}/totals",
        headers=admin_headers,
    )
    assert totals.status_code == 200, totals.text
    totals_body = totals.json()
    assert Decimal(str(totals_body["embodied_a1a3"])) == _EXPECTED_CARBON
    assert Decimal(str(totals_body["embodied_a1a5"])) == _EXPECTED_CARBON

    # 4) Idempotent: re-running never double-counts an already-linked element.
    again = await shared_client.post(enrich_url, headers=admin_headers)
    assert again.status_code == 200, again.text
    again_body = again.json()
    assert again_body["created"] == 0
    assert again_body["skipped_existing"] == 1
    rows_after = (
        await shared_client.get(
            f"/api/v1/carbon/inventories/{inventory_id}/embodied",
            headers=admin_headers,
        )
    ).json()
    assert len(rows_after) == 1, "re-enrichment must not duplicate the linked entry"


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_auto_enrich_denies_foreign_project(
    shared_client: AsyncClient,
    admin_headers: dict[str, str],
) -> None:
    """A non-admin who does not own the project cannot enrich its inventory."""
    project_id = await _create_project(shared_client, admin_headers)
    inventory_id = await _create_inventory(shared_client, admin_headers, project_id)

    # Manager: strongest non-admin role, may hold carbon.* yet must be denied
    # the foreign project. Denial is 404 (project-access IDOR guard) or 403
    # (missing permission) - either is a correct block.
    attacker = await _register(shared_client, "carb6d-mgr", "manager")
    resp = await shared_client.post(
        f"/api/v1/carbon/inventories/{inventory_id}/auto-enrich-bim",
        headers=attacker,
    )
    assert resp.status_code in (403, 404), (
        f"LEAK: non-owner enriched a foreign inventory (status {resp.status_code}): {resp.text!r}"
    )
