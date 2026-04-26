# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Integration tests for ``POST /api/v1/eac/rules:validate`` (EAC-1.3 §6).

Drives the real router against the FastAPI test client. Verifies that
the validator endpoint replaces the EAC-1.1/1.2 stub: malformed rules
get detailed semantic errors, well-formed rules pass.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app

FIXTURES_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "eac"


@pytest_asyncio.fixture
async def client():
    """Test client with full app lifecycle (so module loader runs)."""
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
    """Register + log in a unique user; return Bearer auth header."""
    unique = uuid.uuid4().hex[:8]
    email = f"eac-{unique}@validate.io"
    password = f"EacTest{unique}9"

    await client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": "EAC Validate Tester",
        },
    )
    resp = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    token = resp.json().get("access_token", "")
    return {"Authorization": f"Bearer {token}"}


# ── 1. Valid rule → valid=True ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_validate_endpoint_accepts_valid_rule(client, auth_headers) -> None:
    """A schema-valid + semantically-valid rule returns ``valid=True``."""
    body = {
        "schema_version": "2.0",
        "name": "ok",
        "output_mode": "aggregate",
        "result_unit": "m3",
        "selector": {"kind": "ifc_class", "values": ["IfcWall"]},
        "formula": "Volume * 2",
    }
    resp = await client.post(
        "/api/v1/eac/rules:validate",
        json={"definition_json": body},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["valid"] is True
    assert data["errors"] == []


# ── 2. Unknown alias → alias_not_found ─────────────────────────────────


@pytest.mark.asyncio
async def test_validate_endpoint_rejects_unknown_alias(client, auth_headers) -> None:
    body = {
        "schema_version": "2.0",
        "name": "bad_alias",
        "output_mode": "boolean",
        "selector": {"kind": "ifc_class", "values": ["IfcWall"]},
        "predicate": {
            "kind": "triplet",
            "attribute": {
                "kind": "alias",
                "alias_id": "alias_does_not_exist_xyz",
            },
            "constraint": {"operator": "exists"},
        },
    }
    resp = await client.post(
        "/api/v1/eac/rules:validate",
        json={"definition_json": body},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["valid"] is False
    codes = [e["code"] for e in data["errors"]]
    assert "alias_not_found" in codes


# ── 3. Cyclic local variables fixture → cyclic_local_var ───────────────


@pytest.mark.asyncio
async def test_validate_endpoint_rejects_cyclic_local_var_fixture(
    client, auth_headers
) -> None:
    fixture = FIXTURES_ROOT / "invalid_rules" / "02_invalid_cyclic_local_var.json"
    body = json.loads(fixture.read_text(encoding="utf-8"))
    body.pop("_invalid_reason", None)

    resp = await client.post(
        "/api/v1/eac/rules:validate",
        json={"definition_json": body},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["valid"] is False
    codes = [e["code"] for e in data["errors"]]
    assert "cyclic_local_var" in codes


# ── 4. ReDoS regex fixture → redos_regex ───────────────────────────────


@pytest.mark.asyncio
async def test_validate_endpoint_rejects_redos_regex_fixture(
    client, auth_headers
) -> None:
    fixture = FIXTURES_ROOT / "invalid_rules" / "13_invalid_redos_regex.json"
    body = json.loads(fixture.read_text(encoding="utf-8"))
    body.pop("_invalid_reason", None)

    resp = await client.post(
        "/api/v1/eac/rules:validate",
        json={"definition_json": body},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["valid"] is False
    codes = [e["code"] for e in data["errors"]]
    assert "redos_regex" in codes
