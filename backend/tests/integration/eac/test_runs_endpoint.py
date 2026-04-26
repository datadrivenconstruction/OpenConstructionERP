# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""HTTP integration tests for the EAC v2 run endpoints (RFC 35 §1.7).

Drives the real FastAPI app — covers:

* ``POST /api/v1/eac/rules:dry-run``
* ``POST /api/v1/eac/rulesets/{id}:run``
* ``GET  /api/v1/eac/runs/{id}``
* ``GET  /api/v1/eac/runs``
* ``GET  /api/v1/eac/runs/{id}/results``
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest_asyncio.fixture
async def client():
    app = create_app()

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan_ctx():
        async with app.router.lifespan_context(app):
            yield

    async with lifespan_ctx():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest_asyncio.fixture
async def auth_headers(client):
    unique = uuid.uuid4().hex[:8]
    email = f"eac-{unique}@runs.io"
    password = f"EacRuns{unique}9"

    await client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": "EAC Runs Tester",
        },
    )
    resp = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    token = resp.json().get("access_token", "")
    return {"Authorization": f"Bearer {token}"}


# ── Sample data ───────────────────────────────────────────────────────


def _walls() -> list[dict]:
    return [
        {
            "stable_id": "wall_001",
            "element_type": "Wall",
            "ifc_class": "IfcWall",
            "level": "Level 1",
            "discipline": "ARC",
            "properties": {"FireRating": "F90"},
            "quantities": {"area_m2": 25.0, "volume_m3": 6.0},
        },
        {
            "stable_id": "wall_002",
            "element_type": "Wall",
            "ifc_class": "IfcWall",
            "level": "Level 1",
            "discipline": "ARC",
            "properties": {"FireRating": "F30"},
            "quantities": {"area_m2": 12.5, "volume_m3": 3.0},
        },
    ]


def _boolean_rule() -> dict:
    return {
        "schema_version": "2.0",
        "name": "F90_check",
        "output_mode": "boolean",
        "selector": {"kind": "category", "values": ["Wall"]},
        "predicate": {
            "kind": "triplet",
            "attribute": {"kind": "exact", "name": "FireRating"},
            "constraint": {"operator": "eq", "value": "F90"},
        },
    }


# ── Dry-run endpoint ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dry_run_endpoint_boolean_mode(client, auth_headers) -> None:
    resp = await client.post(
        "/api/v1/eac/rules:dry-run",
        json={
            "definition_json": _boolean_rule(),
            "elements": _walls(),
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["output_mode"] == "boolean"
    assert data["elements_matched"] == 2
    assert data["elements_passed"] == 1
    assert len(data["boolean_results"]) == 2


@pytest.mark.asyncio
async def test_dry_run_endpoint_invalid_definition_returns_422(
    client, auth_headers
) -> None:
    resp = await client.post(
        "/api/v1/eac/rules:dry-run",
        json={
            "definition_json": {"schema_version": "2.0", "name": "bad"},
            "elements": [],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_dry_run_endpoint_clash_mode_returns_501(client, auth_headers) -> None:
    body = {
        "schema_version": "2.0",
        "name": "clash",
        "output_mode": "clash",
        "selector": {"kind": "category", "values": ["Wall"]},
        "clash_config": {
            "set_a": {"kind": "category", "values": ["Wall"]},
            "set_b": {"kind": "category", "values": ["Door"]},
            "method": "obb",
            "test": "intersection_volume",
        },
    }
    resp = await client.post(
        "/api/v1/eac/rules:dry-run",
        json={"definition_json": body, "elements": []},
        headers=auth_headers,
    )
    assert resp.status_code == 501


# ── Run-ruleset endpoint + GET /runs/* ────────────────────────────────


async def _create_ruleset_with_rule(client, auth_headers) -> tuple[str, str]:
    """Create a ruleset and one boolean-mode rule. Returns (ruleset_id, rule_id)."""
    rs_resp = await client.post(
        "/api/v1/eac/rulesets",
        json={"name": "test_runs", "kind": "validation"},
        headers=auth_headers,
    )
    assert rs_resp.status_code == 201, rs_resp.text
    ruleset_id = rs_resp.json()["id"]

    rule_resp = await client.post(
        "/api/v1/eac/rules",
        json={
            "ruleset_id": ruleset_id,
            "name": "F90_check",
            "output_mode": "boolean",
            "definition_json": _boolean_rule(),
        },
        headers=auth_headers,
    )
    assert rule_resp.status_code == 201, rule_resp.text
    return ruleset_id, rule_resp.json()["id"]


@pytest.mark.asyncio
async def test_run_ruleset_endpoint_persists_run(client, auth_headers) -> None:
    ruleset_id, _rule_id = await _create_ruleset_with_rule(client, auth_headers)

    resp = await client.post(
        f"/api/v1/eac/rulesets/{ruleset_id}:run",
        json={"elements": _walls(), "triggered_by": "manual"},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    run = resp.json()
    assert run["status"] == "success"
    assert run["elements_evaluated"] == 2
    assert run["elements_matched"] == 2

    # GET /runs/{id}
    run_id = run["id"]
    get_resp = await client.get(
        f"/api/v1/eac/runs/{run_id}",
        headers=auth_headers,
    )
    assert get_resp.status_code == 200, get_resp.text
    assert get_resp.json()["id"] == run_id

    # GET /runs?ruleset_id=...
    list_resp = await client.get(
        f"/api/v1/eac/runs?ruleset_id={ruleset_id}",
        headers=auth_headers,
    )
    assert list_resp.status_code == 200, list_resp.text
    runs = list_resp.json()
    assert len(runs) == 1
    assert runs[0]["id"] == run_id

    # GET /runs/{id}/results
    results_resp = await client.get(
        f"/api/v1/eac/runs/{run_id}/results",
        headers=auth_headers,
    )
    assert results_resp.status_code == 200, results_resp.text
    rows = results_resp.json()
    assert len(rows) == 2
    by_id = {r["element_id"]: r for r in rows}
    assert by_id["wall_001"]["pass_"] is True
    assert by_id["wall_002"]["pass_"] is False


@pytest.mark.asyncio
async def test_run_ruleset_endpoint_only_failures_filter(
    client, auth_headers
) -> None:
    ruleset_id, _ = await _create_ruleset_with_rule(client, auth_headers)
    run_resp = await client.post(
        f"/api/v1/eac/rulesets/{ruleset_id}:run",
        json={"elements": _walls()},
        headers=auth_headers,
    )
    run_id = run_resp.json()["id"]

    resp = await client.get(
        f"/api/v1/eac/runs/{run_id}/results?only_failures=true",
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["element_id"] == "wall_002"


@pytest.mark.asyncio
async def test_run_ruleset_requires_elements_or_model_id(
    client, auth_headers
) -> None:
    ruleset_id, _ = await _create_ruleset_with_rule(client, auth_headers)
    resp = await client.post(
        f"/api/v1/eac/rulesets/{ruleset_id}:run",
        json={},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_run_ruleset_unknown_id_returns_404(client, auth_headers) -> None:
    resp = await client.post(
        f"/api/v1/eac/rulesets/{uuid.uuid4()}:run",
        json={"elements": []},
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_run_ruleset_rejects_unknown_triggered_by(
    client, auth_headers
) -> None:
    """``triggered_by`` is a Literal — a typo must surface as 422."""
    ruleset_id, _ = await _create_ruleset_with_rule(client, auth_headers)
    resp = await client.post(
        f"/api/v1/eac/rulesets/{ruleset_id}:run",
        json={"elements": [], "triggered_by": "banana"},
        headers=auth_headers,
    )
    assert resp.status_code == 422
