# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""IDOR (Insecure Direct Object Reference) integration tests for the EAC module.

Verifies that cross-tenant access to EAC resources returns HTTP 404 —
tenant isolation is enforced at the API boundary on every GET/POST/PUT/DELETE
endpoint that reads or mutates EAC objects.

Extends the contract established in
``tests/unit/test_eac_security.py`` (engine-layer IDOR) with the full
HTTP round-trip: two distinct registered users, each owning their own
ruleset/rule/run, must never see each other's objects.

Structure:
  - Tenant A: registers, creates a ruleset + rule, triggers a run.
  - Tenant B: registers separately; all B's requests against A's IDs → 404.
  - B's own IDs remain fully accessible to B.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# ── Shared fixture: FastAPI test client ──────────────────────────────────────


@pytest_asyncio.fixture
async def client():
    """Boot the real FastAPI app against the per-session PostgreSQL database."""
    from app.main import create_app

    app = create_app()

    @asynccontextmanager
    async def _lc():
        async with app.router.lifespan_context(app):
            yield

    async with _lc():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


# ── Auth helpers ─────────────────────────────────────────────────────────────


async def _register_and_login(client: AsyncClient, suffix: str) -> dict[str, str]:
    """Register a fresh user and return its Bearer auth header."""
    from tests.integration._auth_helpers import promote_to_admin

    email = f"idor-eac-{suffix}-{uuid.uuid4().hex[:6]}@test.io"
    password = f"IdorEac{suffix}9X"
    await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": f"IDOR {suffix}"},
    )
    # EAC writes/runs require EDITOR+ (finding #6). Promote each tenant's user
    # so it can seed its own entities; these tests exercise tenant isolation,
    # not role gating, and EAC has no admin tenant-bypass.
    await promote_to_admin(email)
    resp = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    token = resp.json().get("access_token", "")
    return {"Authorization": f"Bearer {token}"}


# ── Seed helpers ─────────────────────────────────────────────────────────────


async def _create_ruleset(client: AsyncClient, headers: dict[str, str], name: str) -> str:
    """Create a ruleset and return its ID string."""
    resp = await client.post(
        "/api/v1/eac/rulesets",
        json={"name": name, "kind": "validation"},
        headers=headers,
    )
    assert resp.status_code == 201, f"create_ruleset failed: {resp.text}"
    return resp.json()["id"]


async def _create_rule(client: AsyncClient, headers: dict[str, str], ruleset_id: str, name: str) -> str:
    """Create a boolean rule inside a ruleset and return its ID string."""
    resp = await client.post(
        "/api/v1/eac/rules",
        json={
            "ruleset_id": ruleset_id,
            "name": name,
            "output_mode": "boolean",
            "definition_json": {
                "schema_version": "2.0",
                "name": name,
                "output_mode": "boolean",
                "selector": {"kind": "category", "values": ["Wall"]},
                "predicate": {
                    "kind": "triplet",
                    "attribute": {"kind": "exact", "name": "FireRating"},
                    "constraint": {"operator": "exists"},
                },
            },
        },
        headers=headers,
    )
    assert resp.status_code == 201, f"create_rule failed: {resp.text}"
    return resp.json()["id"]


_WALLS: list[dict[str, Any]] = [
    {
        "stable_id": "w1",
        "element_type": "Wall",
        "ifc_class": "IfcWall",
        "level": "L0",
        "discipline": "ARC",
        "properties": {"FireRating": "F90"},
        "quantities": {"area_m2": 20.0},
    }
]


async def _trigger_run(client: AsyncClient, headers: dict[str, str], ruleset_id: str) -> str:
    """Trigger a ruleset run and return its ID string."""
    resp = await client.post(
        f"/api/v1/eac/rulesets/{ruleset_id}:run",
        json={"elements": _WALLS, "triggered_by": "manual"},
        headers=headers,
    )
    assert resp.status_code == 201, f"trigger_run failed: {resp.text}"
    return resp.json()["id"]


# ── Tests ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ruleset_cross_tenant_returns_404(client: AsyncClient) -> None:
    """GET /eac/rulesets/{id} owned by tenant A must return 404 to tenant B."""
    headers_a = await _register_and_login(client, "a1")
    headers_b = await _register_and_login(client, "b1")

    ruleset_id_a = await _create_ruleset(client, headers_a, "idor_rs_a")

    # Tenant B tries to fetch A's ruleset.
    resp = await client.get(f"/api/v1/eac/rulesets/{ruleset_id_a}", headers=headers_b)
    assert resp.status_code == 404, f"Expected 404 for cross-tenant ruleset access, got {resp.status_code}: {resp.text}"

    # Sanity: A can still access its own ruleset.
    own_resp = await client.get(f"/api/v1/eac/rulesets/{ruleset_id_a}", headers=headers_a)
    assert own_resp.status_code == 200


@pytest.mark.asyncio
async def test_rule_cross_tenant_returns_404(client: AsyncClient) -> None:
    """GET /eac/rules/{id} owned by tenant A must return 404 to tenant B."""
    headers_a = await _register_and_login(client, "a2")
    headers_b = await _register_and_login(client, "b2")

    ruleset_id_a = await _create_ruleset(client, headers_a, "idor_rule_rs")
    rule_id_a = await _create_rule(client, headers_a, ruleset_id_a, "idor_rule")

    resp = await client.get(f"/api/v1/eac/rules/{rule_id_a}", headers=headers_b)
    assert resp.status_code == 404, f"Expected 404 for cross-tenant rule access, got {resp.status_code}"

    # Sanity: owner can read it.
    own_resp = await client.get(f"/api/v1/eac/rules/{rule_id_a}", headers=headers_a)
    assert own_resp.status_code == 200


@pytest.mark.asyncio
async def test_run_cross_tenant_returns_404(client: AsyncClient) -> None:
    """GET /eac/runs/{id} owned by tenant A must return 404 to tenant B."""
    headers_a = await _register_and_login(client, "a3")
    headers_b = await _register_and_login(client, "b3")

    ruleset_id_a = await _create_ruleset(client, headers_a, "idor_run_rs")
    await _create_rule(client, headers_a, ruleset_id_a, "idor_run_rule")
    run_id_a = await _trigger_run(client, headers_a, ruleset_id_a)

    resp = await client.get(f"/api/v1/eac/runs/{run_id_a}", headers=headers_b)
    assert resp.status_code == 404, f"Expected 404 for cross-tenant run access, got {resp.status_code}"

    # Sanity: owner can read it.
    own_resp = await client.get(f"/api/v1/eac/runs/{run_id_a}", headers=headers_a)
    assert own_resp.status_code == 200


@pytest.mark.asyncio
async def test_run_results_cross_tenant_returns_404(client: AsyncClient) -> None:
    """GET /eac/runs/{id}/results owned by A must return 404 to tenant B."""
    headers_a = await _register_and_login(client, "a4")
    headers_b = await _register_and_login(client, "b4")

    ruleset_id_a = await _create_ruleset(client, headers_a, "idor_results_rs")
    await _create_rule(client, headers_a, ruleset_id_a, "idor_results_rule")
    run_id_a = await _trigger_run(client, headers_a, ruleset_id_a)

    resp = await client.get(f"/api/v1/eac/runs/{run_id_a}/results", headers=headers_b)
    assert resp.status_code == 404, f"Expected 404 for cross-tenant run-results access, got {resp.status_code}"

    # Sanity: owner can list results (may be empty list, still 200).
    own_resp = await client.get(f"/api/v1/eac/runs/{run_id_a}/results", headers=headers_a)
    assert own_resp.status_code == 200


@pytest.mark.asyncio
async def test_run_status_cross_tenant_returns_404(client: AsyncClient) -> None:
    """GET /eac/runs/{id}/status owned by A must return 404 to tenant B."""
    headers_a = await _register_and_login(client, "a5")
    headers_b = await _register_and_login(client, "b5")

    ruleset_id_a = await _create_ruleset(client, headers_a, "idor_status_rs")
    await _create_rule(client, headers_a, ruleset_id_a, "idor_status_rule")
    run_id_a = await _trigger_run(client, headers_a, ruleset_id_a)

    resp = await client.get(f"/api/v1/eac/runs/{run_id_a}/status", headers=headers_b)
    assert resp.status_code == 404, f"Expected 404 for cross-tenant run-status access, got {resp.status_code}"

    own_resp = await client.get(f"/api/v1/eac/runs/{run_id_a}/status", headers=headers_a)
    assert own_resp.status_code == 200


@pytest.mark.asyncio
async def test_cancel_run_cross_tenant_returns_404(client: AsyncClient) -> None:
    """POST /eac/runs/{id}:cancel owned by A must return 404 to tenant B."""
    headers_a = await _register_and_login(client, "a6")
    headers_b = await _register_and_login(client, "b6")

    ruleset_id_a = await _create_ruleset(client, headers_a, "idor_cancel_rs")
    await _create_rule(client, headers_a, ruleset_id_a, "idor_cancel_rule")
    run_id_a = await _trigger_run(client, headers_a, ruleset_id_a)

    resp = await client.post(f"/api/v1/eac/runs/{run_id_a}:cancel", headers=headers_b)
    assert resp.status_code == 404, f"Expected 404 for cross-tenant cancel, got {resp.status_code}"


@pytest.mark.asyncio
async def test_update_rule_cross_tenant_returns_404(client: AsyncClient) -> None:
    """PUT /eac/rules/{id} owned by A must return 404 to tenant B."""
    headers_a = await _register_and_login(client, "a7")
    headers_b = await _register_and_login(client, "b7")

    ruleset_id_a = await _create_ruleset(client, headers_a, "idor_upd_rs")
    rule_id_a = await _create_rule(client, headers_a, ruleset_id_a, "idor_upd_rule")

    resp = await client.put(
        f"/api/v1/eac/rules/{rule_id_a}",
        json={"name": "hacked_name"},
        headers=headers_b,
    )
    assert resp.status_code == 404, f"Expected 404 for cross-tenant rule update, got {resp.status_code}"


@pytest.mark.asyncio
async def test_delete_rule_cross_tenant_returns_404(client: AsyncClient) -> None:
    """DELETE /eac/rules/{id} owned by A must return 404 to tenant B."""
    headers_a = await _register_and_login(client, "a8")
    headers_b = await _register_and_login(client, "b8")

    ruleset_id_a = await _create_ruleset(client, headers_a, "idor_del_rs")
    rule_id_a = await _create_rule(client, headers_a, ruleset_id_a, "idor_del_rule")

    resp = await client.delete(f"/api/v1/eac/rules/{rule_id_a}", headers=headers_b)
    assert resp.status_code == 404, f"Expected 404 for cross-tenant rule delete, got {resp.status_code}"

    # Verify A's rule was NOT soft-deleted by B's request.
    own_resp = await client.get(f"/api/v1/eac/rules/{rule_id_a}", headers=headers_a)
    assert own_resp.status_code == 200
    assert own_resp.json()["is_active"] is True


@pytest.mark.asyncio
async def test_update_ruleset_cross_tenant_returns_404(client: AsyncClient) -> None:
    """PUT /eac/rulesets/{id} owned by A must return 404 to tenant B."""
    headers_a = await _register_and_login(client, "a9")
    headers_b = await _register_and_login(client, "b9")

    ruleset_id_a = await _create_ruleset(client, headers_a, "idor_updrs_rs")

    resp = await client.put(
        f"/api/v1/eac/rulesets/{ruleset_id_a}",
        json={"name": "hacked"},
        headers=headers_b,
    )
    assert resp.status_code == 404, f"Expected 404 for cross-tenant ruleset update, got {resp.status_code}"


@pytest.mark.asyncio
async def test_delete_ruleset_cross_tenant_returns_404(client: AsyncClient) -> None:
    """DELETE /eac/rulesets/{id} owned by A must return 404 to tenant B."""
    headers_a = await _register_and_login(client, "a10")
    headers_b = await _register_and_login(client, "b10")

    ruleset_id_a = await _create_ruleset(client, headers_a, "idor_delrs_rs")

    resp = await client.delete(f"/api/v1/eac/rulesets/{ruleset_id_a}", headers=headers_b)
    assert resp.status_code == 404, f"Expected 404 for cross-tenant ruleset delete, got {resp.status_code}"

    # Still accessible to A.
    own_resp = await client.get(f"/api/v1/eac/rulesets/{ruleset_id_a}", headers=headers_a)
    assert own_resp.status_code == 200


@pytest.mark.asyncio
async def test_fabricated_uuid_returns_404(client: AsyncClient) -> None:
    """A guessed/fabricated UUID that doesn't exist must return 404.

    This guards against object-exists-but-wrong-tenant confusion. Even if
    the UUID lookup returns None, the router must return 404 (not 500).
    """
    headers = await _register_and_login(client, "fab")
    fake_id = str(uuid.uuid4())

    for path in [
        f"/api/v1/eac/rulesets/{fake_id}",
        f"/api/v1/eac/rules/{fake_id}",
        f"/api/v1/eac/runs/{fake_id}",
        f"/api/v1/eac/runs/{fake_id}/status",
        f"/api/v1/eac/runs/{fake_id}/results",
    ]:
        resp = await client.get(path, headers=headers)
        assert resp.status_code == 404, f"Fabricated UUID at {path} should return 404, got {resp.status_code}"


@pytest.mark.asyncio
async def test_list_runs_does_not_leak_other_tenant(client: AsyncClient) -> None:
    """GET /eac/runs must only return runs owned by the authenticated tenant."""
    headers_a = await _register_and_login(client, "la")
    headers_b = await _register_and_login(client, "lb")

    # Tenant A creates a run.
    ruleset_id_a = await _create_ruleset(client, headers_a, "leak_rs_a")
    await _create_rule(client, headers_a, ruleset_id_a, "leak_rule_a")
    run_id_a = await _trigger_run(client, headers_a, ruleset_id_a)

    # Tenant B lists runs — must not see A's run.
    resp = await client.get("/api/v1/eac/runs", headers=headers_b)
    assert resp.status_code == 200
    ids_visible_to_b = {r["id"] for r in resp.json()}
    assert run_id_a not in ids_visible_to_b, (
        f"Tenant B should not see tenant A's run {run_id_a}. Visible to B: {ids_visible_to_b}"
    )


@pytest.mark.asyncio
async def test_list_rulesets_does_not_leak_other_tenant(client: AsyncClient) -> None:
    """GET /eac/rulesets must only return rulesets owned by the authenticated tenant."""
    headers_a = await _register_and_login(client, "lra")
    headers_b = await _register_and_login(client, "lrb")

    ruleset_id_a = await _create_ruleset(client, headers_a, "leak_ruleset_a")

    resp = await client.get("/api/v1/eac/rulesets", headers=headers_b)
    assert resp.status_code == 200
    ids_visible_to_b = {r["id"] for r in resp.json()}
    assert ruleset_id_a not in ids_visible_to_b, (
        f"Tenant B should not see tenant A's ruleset. Visible: {ids_visible_to_b}"
    )
