"""CWICR abstract-resource variant flow on BOQ positions.

Covers the production-quality variant pipeline:

* Creating a position with ``metadata.variant`` stamps an immutable
  ``variant_snapshot`` carrying the rate, currency, label, source, and
  a UTC capture timestamp.
* Creating a position with ``metadata.variant_default = 'mean'`` stamps the
  same snapshot with ``source = 'default_mean'`` so the auto-applied price
  is also frozen.
* Updating a position to switch from a default to a specific variant
  re-stamps the snapshot (new label, new rate, new source) — older
  snapshot is replaced.
* A pure metadata patch that does not alter ``variant`` /
  ``variant_default`` does NOT advance ``captured_at`` (idempotency).
* A patch that only changes an unrelated field (e.g. quantity) preserves
  the existing snapshot bit-for-bit.

Run:
    cd backend
    python -m pytest tests/integration/test_boq_variants.py -v --tb=short
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app

# ── Shared fixtures (same pattern as other BOQ integration tests) ────────


@pytest_asyncio.fixture(scope="module")
async def shared_client() -> AsyncClient:
    """Module-scoped client with full app lifecycle."""
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


@pytest_asyncio.fixture(scope="module")
async def shared_auth(shared_client: AsyncClient) -> dict[str, str]:
    """Module-scoped auth: register + force-promote-to-admin + login."""
    unique = uuid.uuid4().hex[:8]
    email = f"boqvar-{unique}@test.io"
    password = f"BoqVar{unique}9!"

    reg = await shared_client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": "BOQ Variant Tester",
            "role": "admin",
        },
    )
    assert reg.status_code == 201, f"Registration failed: {reg.text}"

    from sqlalchemy import update as sa_update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as session:
        await session.execute(sa_update(User).where(User.email == email.lower()).values(role="admin", is_active=True))
        await session.commit()

    token = ""
    for attempt in range(3):
        resp = await shared_client.post(
            "/api/v1/users/auth/login",
            json={"email": email, "password": password},
        )
        data = resp.json()
        token = data.get("access_token", "")
        if token:
            break
        if "Too many login attempts" in data.get("detail", ""):
            await asyncio.sleep(5 * (attempt + 1))
            continue
        break
    assert token, f"Login failed: {data}"
    return {"Authorization": f"Bearer {token}"}


# ── Per-module helpers ────────────────────────────────────────────────────


async def _create_project(client: AsyncClient, auth: dict[str, str]) -> str:
    resp = await client.post(
        "/api/v1/projects/",
        json={
            "name": f"VariantTest {uuid.uuid4().hex[:6]}",
            "description": "Variant integration",
            "region": "DACH",
            "classification_standard": "din276",
            "currency": "EUR",
        },
        headers=auth,
    )
    assert resp.status_code == 201, f"Create project failed: {resp.text}"
    return resp.json()["id"]


async def _create_boq(client: AsyncClient, auth: dict[str, str], project_id: str) -> str:
    resp = await client.post(
        "/api/v1/boq/boqs/",
        json={
            "project_id": project_id,
            "name": f"VariantBOQ {uuid.uuid4().hex[:6]}",
            "description": "Variant integration",
        },
        headers=auth,
    )
    assert resp.status_code == 201, f"Create BOQ failed: {resp.text}"
    return resp.json()["id"]


# ═══════════════════════════════════════════════════════════════════════════
#  Variant snapshot creation
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_create_with_variant_stamps_snapshot(shared_client: AsyncClient, shared_auth: dict[str, str]) -> None:
    """POST a position with metadata.variant must emit variant_snapshot."""
    client, auth = shared_client, shared_auth
    project_id = await _create_project(client, auth)
    boq_id = await _create_boq(client, auth, project_id)

    resp = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/positions/",
        json={
            "boq_id": boq_id,
            "ordinal": "VAR.001",
            "description": "Concrete C30/37, ready-mix",
            "unit": "m3",
            "quantity": 12.5,
            "unit_rate": 185.00,
            "source": "cost_database",
            "metadata": {
                "currency": "EUR",
                "variant": {"label": "ready-mix delivered", "price": 185.00, "index": 0},
            },
        },
        headers=auth,
    )
    assert resp.status_code == 201, f"Create failed: {resp.text}"
    pos = resp.json()
    snap = pos["metadata"].get("variant_snapshot")
    assert snap is not None, f"variant_snapshot missing in {pos['metadata']}"
    assert snap["label"] == "ready-mix delivered"
    assert snap["rate"] == 185.00
    assert snap["currency"] == "EUR"
    assert snap["source"] == "user_pick"
    # captured_at must be a parseable ISO-8601 timestamp.
    parsed = datetime.fromisoformat(snap["captured_at"].replace("Z", "+00:00"))
    assert parsed.tzinfo is not None


@pytest.mark.asyncio
async def test_create_with_variant_default_mean_stamps_snapshot(
    shared_client: AsyncClient, shared_auth: dict[str, str]
) -> None:
    """A 'use average' apply (variant_default='mean') still freezes the rate."""
    client, auth = shared_client, shared_auth
    project_id = await _create_project(client, auth)
    boq_id = await _create_boq(client, auth, project_id)

    resp = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/positions/",
        json={
            "boq_id": boq_id,
            "ordinal": "VAR.002",
            "description": "Concrete C30/37, average across 5 quotes",
            "unit": "m3",
            "quantity": 1.0,
            "unit_rate": 167.50,
            "source": "cost_database",
            "metadata": {
                "currency": "EUR",
                "variant_default": "mean",
            },
        },
        headers=auth,
    )
    assert resp.status_code == 201, f"Create failed: {resp.text}"
    pos = resp.json()
    snap = pos["metadata"].get("variant_snapshot")
    assert snap is not None
    assert snap["label"] == "average"
    assert snap["rate"] == 167.50
    assert snap["source"] == "default_mean"
    assert snap["currency"] == "EUR"


@pytest.mark.asyncio
async def test_create_without_variant_does_not_stamp_snapshot(
    shared_client: AsyncClient, shared_auth: dict[str, str]
) -> None:
    """Plain manual positions must NOT receive a variant_snapshot."""
    client, auth = shared_client, shared_auth
    project_id = await _create_project(client, auth)
    boq_id = await _create_boq(client, auth, project_id)

    resp = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/positions/",
        json={
            "boq_id": boq_id,
            "ordinal": "VAR.003",
            "description": "Manual line",
            "unit": "m3",
            "quantity": 1.0,
            "unit_rate": 100.0,
            "source": "manual",
        },
        headers=auth,
    )
    assert resp.status_code == 201, f"Create failed: {resp.text}"
    assert "variant_snapshot" not in resp.json()["metadata"]


# ═══════════════════════════════════════════════════════════════════════════
#  Variant snapshot lifecycle on update
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_patch_default_to_specific_variant_restamps_snapshot(
    shared_client: AsyncClient, shared_auth: dict[str, str]
) -> None:
    """User refines a default → snapshot must update to the explicit pick."""
    client, auth = shared_client, shared_auth
    project_id = await _create_project(client, auth)
    boq_id = await _create_boq(client, auth, project_id)

    create_resp = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/positions/",
        json={
            "boq_id": boq_id,
            "ordinal": "VAR.004",
            "description": "Concrete C30/37, default mean",
            "unit": "m3",
            "quantity": 1.0,
            "unit_rate": 167.50,
            "source": "cost_database",
            "metadata": {"currency": "EUR", "variant_default": "mean"},
        },
        headers=auth,
    )
    assert create_resp.status_code == 201, create_resp.text
    pos_id = create_resp.json()["id"]
    initial_snap = create_resp.json()["metadata"]["variant_snapshot"]
    assert initial_snap["source"] == "default_mean"

    # User picks a specific variant — patch with new metadata + new rate.
    patch_resp = await client.patch(
        f"/api/v1/boq/positions/{pos_id}",
        json={
            "unit_rate": 195.0,
            "metadata": {
                "currency": "EUR",
                "variant": {"label": "premium ready-mix", "price": 195.0, "index": 4},
            },
        },
        headers=auth,
    )
    assert patch_resp.status_code == 200, patch_resp.text
    patched = patch_resp.json()
    new_snap = patched["metadata"]["variant_snapshot"]
    assert new_snap["label"] == "premium ready-mix"
    assert new_snap["rate"] == 195.0
    assert new_snap["source"] == "user_pick"
    # variant_default should be gone now (we replaced metadata wholesale).
    assert "variant_default" not in patched["metadata"]
    # captured_at must be at-or-after the original (clock can be at the same
    # second on fast hardware so >= is the safe assertion).
    assert new_snap["captured_at"] >= initial_snap["captured_at"]


@pytest.mark.asyncio
async def test_quantity_only_patch_preserves_snapshot(shared_client: AsyncClient, shared_auth: dict[str, str]) -> None:
    """Editing quantity must not touch a previously-stamped variant_snapshot."""
    client, auth = shared_client, shared_auth
    project_id = await _create_project(client, auth)
    boq_id = await _create_boq(client, auth, project_id)

    create_resp = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/positions/",
        json={
            "boq_id": boq_id,
            "ordinal": "VAR.005",
            "description": "Concrete C30/37 — locked rate",
            "unit": "m3",
            "quantity": 1.0,
            "unit_rate": 185.0,
            "source": "cost_database",
            "metadata": {
                "currency": "EUR",
                "variant": {"label": "ready-mix delivered", "price": 185.0, "index": 0},
            },
        },
        headers=auth,
    )
    assert create_resp.status_code == 201, create_resp.text
    pos_id = create_resp.json()["id"]
    original_snap = create_resp.json()["metadata"]["variant_snapshot"]

    # Edit only the quantity — metadata + unit_rate are untouched.
    patch_resp = await client.patch(
        f"/api/v1/boq/positions/{pos_id}",
        json={"quantity": 25.0},
        headers=auth,
    )
    assert patch_resp.status_code == 200, patch_resp.text
    patched = patch_resp.json()
    assert patched["quantity"] == 25.0
    # Total must scale: 25 * 185 = 4625
    assert float(patched["total"]) == pytest.approx(4625.0)
    # Snapshot must be byte-identical (stable label, rate, captured_at, source).
    new_snap = patched["metadata"].get("variant_snapshot")
    assert new_snap == original_snap, (
        f"variant_snapshot drifted on a quantity-only edit:\n  before={original_snap}\n  after ={new_snap}"
    )


@pytest.mark.asyncio
async def test_idempotent_metadata_patch_does_not_advance_captured_at(
    shared_client: AsyncClient, shared_auth: dict[str, str]
) -> None:
    """Re-sending the same variant payload must keep captured_at stable."""
    client, auth = shared_client, shared_auth
    project_id = await _create_project(client, auth)
    boq_id = await _create_boq(client, auth, project_id)

    create_resp = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/positions/",
        json={
            "boq_id": boq_id,
            "ordinal": "VAR.006",
            "description": "Concrete C30/37 — idempotent",
            "unit": "m3",
            "quantity": 1.0,
            "unit_rate": 185.0,
            "source": "cost_database",
            "metadata": {
                "currency": "EUR",
                "variant": {"label": "ready-mix delivered", "price": 185.0, "index": 0},
            },
        },
        headers=auth,
    )
    assert create_resp.status_code == 201, create_resp.text
    pos_id = create_resp.json()["id"]
    original_snap = create_resp.json()["metadata"]["variant_snapshot"]

    # No-op patch — same metadata payload.
    patch_resp = await client.patch(
        f"/api/v1/boq/positions/{pos_id}",
        json={
            "metadata": {
                "currency": "EUR",
                "variant": {"label": "ready-mix delivered", "price": 185.0, "index": 0},
            },
        },
        headers=auth,
    )
    assert patch_resp.status_code == 200, patch_resp.text
    new_snap = patch_resp.json()["metadata"]["variant_snapshot"]
    assert new_snap["captured_at"] == original_snap["captured_at"], (
        "Idempotent metadata patch advanced captured_at — snapshot is not stable."
    )


# ═══════════════════════════════════════════════════════════════════════════
#  Per-resource variant snapshots — multi-resource positions
# ═══════════════════════════════════════════════════════════════════════════
#
# When a single position is composed of multiple variant-bearing resources
# (e.g. concrete C30 + rebar 8mm), each resource entry must carry its own
# immutable ``variant_snapshot`` so a later cost-database re-import cannot
# silently rewrite any one of them.
#
# These tests cover:
#  * create-with-resources stamps per-resource snapshots
#  * mixed bag (one resource picks variant, one picks default-mean, one is
#    plain) stamps only the two that have variant markers
#  * idempotent metadata patch preserves each resource's captured_at
#  * switching one resource's variant re-stamps only that resource


@pytest.mark.asyncio
async def test_create_with_per_resource_variants_stamps_each(
    shared_client: AsyncClient, shared_auth: dict[str, str]
) -> None:
    """Position with 2+ variant-bearing resources gets a snapshot per resource."""
    client, auth = shared_client, shared_auth
    project_id = await _create_project(client, auth)
    boq_id = await _create_boq(client, auth, project_id)

    resp = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/positions/",
        json={
            "boq_id": boq_id,
            "ordinal": "MR.001",
            "description": "Reinforced concrete wall — multi-resource",
            "unit": "m3",
            "quantity": 1.0,
            "unit_rate": 320.0,
            "source": "cost_database",
            "metadata": {
                "currency": "EUR",
                "resources": [
                    {
                        "name": "Concrete C30/37",
                        "code": "BET.C30",
                        "type": "material",
                        "unit": "m3",
                        "quantity": 1.0,
                        "unit_rate": 185.0,
                        "total": 185.0,
                        "variant": {"label": "C30/37 ready-mix", "price": 185.0, "index": 1},
                    },
                    {
                        "name": "Reinforcement steel 8mm",
                        "code": "REB.8MM",
                        "type": "material",
                        "unit": "kg",
                        "quantity": 90.0,
                        "unit_rate": 1.50,
                        "total": 135.0,
                        "variant": {"label": "8mm BSt500", "price": 1.50, "index": 0},
                    },
                ],
            },
        },
        headers=auth,
    )
    assert resp.status_code == 201, f"Create failed: {resp.text}"
    pos = resp.json()
    resources = pos["metadata"].get("resources", [])
    assert len(resources) == 2, f"Resources missing: {pos['metadata']}"

    snap0 = resources[0].get("variant_snapshot")
    assert snap0 is not None, f"Resource 0 snapshot missing: {resources[0]}"
    assert snap0["label"] == "C30/37 ready-mix"
    assert snap0["rate"] == 185.0
    assert snap0["currency"] == "EUR"
    assert snap0["source"] == "user_pick"
    parsed = datetime.fromisoformat(snap0["captured_at"].replace("Z", "+00:00"))
    assert parsed.tzinfo is not None

    snap1 = resources[1].get("variant_snapshot")
    assert snap1 is not None, f"Resource 1 snapshot missing: {resources[1]}"
    assert snap1["label"] == "8mm BSt500"
    assert snap1["rate"] == 1.50
    assert snap1["source"] == "user_pick"


@pytest.mark.asyncio
async def test_per_resource_mixed_variant_default_and_plain(
    shared_client: AsyncClient, shared_auth: dict[str, str]
) -> None:
    """Snapshots only attach to resources with a variant or variant_default marker."""
    client, auth = shared_client, shared_auth
    project_id = await _create_project(client, auth)
    boq_id = await _create_boq(client, auth, project_id)

    resp = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/positions/",
        json={
            "boq_id": boq_id,
            "ordinal": "MR.002",
            "description": "Mixed-variant assembly",
            "unit": "m3",
            "quantity": 1.0,
            "unit_rate": 250.0,
            "source": "cost_database",
            "metadata": {
                "currency": "EUR",
                "resources": [
                    {
                        "name": "Concrete C30/37",
                        "code": "BET.C30",
                        "unit": "m3",
                        "quantity": 1.0,
                        "unit_rate": 185.0,
                        "variant": {"label": "C30/37", "price": 185.0, "index": 1},
                    },
                    {
                        "name": "Rebar — average",
                        "code": "REB.AVG",
                        "unit": "kg",
                        "quantity": 90.0,
                        "unit_rate": 1.40,
                        "variant_default": "mean",
                    },
                    {
                        "name": "Formwork labour",
                        "code": "LAB.FW",
                        "unit": "h",
                        "quantity": 4.0,
                        "unit_rate": 32.50,
                    },
                ],
            },
        },
        headers=auth,
    )
    assert resp.status_code == 201, resp.text
    resources = resp.json()["metadata"]["resources"]
    assert len(resources) == 3
    assert resources[0]["variant_snapshot"]["source"] == "user_pick"
    assert resources[0]["variant_snapshot"]["label"] == "C30/37"
    assert resources[1]["variant_snapshot"]["source"] == "default_mean"
    assert resources[1]["variant_snapshot"]["label"] == "average"
    assert resources[1]["variant_snapshot"]["rate"] == 1.40
    assert "variant_snapshot" not in resources[2], (
        "Plain resource should not carry a snapshot"
    )


@pytest.mark.asyncio
async def test_per_resource_snapshot_is_idempotent(
    shared_client: AsyncClient, shared_auth: dict[str, str]
) -> None:
    """A no-op metadata patch must preserve each resource's captured_at."""
    client, auth = shared_client, shared_auth
    project_id = await _create_project(client, auth)
    boq_id = await _create_boq(client, auth, project_id)

    create_resp = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/positions/",
        json={
            "boq_id": boq_id,
            "ordinal": "MR.003",
            "description": "Idempotency check",
            "unit": "m3",
            "quantity": 1.0,
            "unit_rate": 100.0,
            "source": "cost_database",
            "metadata": {
                "currency": "EUR",
                "resources": [
                    {
                        "name": "Resource A",
                        "code": "RA",
                        "unit": "m3",
                        "quantity": 1.0,
                        "unit_rate": 60.0,
                        "variant": {"label": "RA-v1", "price": 60.0, "index": 0},
                    },
                    {
                        "name": "Resource B",
                        "code": "RB",
                        "unit": "kg",
                        "quantity": 10.0,
                        "unit_rate": 4.0,
                        "variant": {"label": "RB-v2", "price": 4.0, "index": 1},
                    },
                ],
            },
        },
        headers=auth,
    )
    assert create_resp.status_code == 201, create_resp.text
    pos_id = create_resp.json()["id"]
    orig0 = create_resp.json()["metadata"]["resources"][0]["variant_snapshot"]
    orig1 = create_resp.json()["metadata"]["resources"][1]["variant_snapshot"]

    # Sleep at least 1s so any timestamp drift would be visible (timespec=seconds).
    await asyncio.sleep(1.1)

    patch_resp = await client.patch(
        f"/api/v1/boq/positions/{pos_id}",
        json={
            "metadata": {
                "currency": "EUR",
                "resources": [
                    {
                        "name": "Resource A",
                        "code": "RA",
                        "unit": "m3",
                        "quantity": 1.0,
                        "unit_rate": 60.0,
                        "variant": {"label": "RA-v1", "price": 60.0, "index": 0},
                    },
                    {
                        "name": "Resource B",
                        "code": "RB",
                        "unit": "kg",
                        "quantity": 10.0,
                        "unit_rate": 4.0,
                        "variant": {"label": "RB-v2", "price": 4.0, "index": 1},
                    },
                ],
            },
        },
        headers=auth,
    )
    assert patch_resp.status_code == 200, patch_resp.text
    new_resources = patch_resp.json()["metadata"]["resources"]
    assert new_resources[0]["variant_snapshot"]["captured_at"] == orig0["captured_at"], (
        "Resource 0 captured_at drifted on no-op patch"
    )
    assert new_resources[1]["variant_snapshot"]["captured_at"] == orig1["captured_at"], (
        "Resource 1 captured_at drifted on no-op patch"
    )


@pytest.mark.asyncio
async def test_per_resource_switch_restamps_only_changed_resource(
    shared_client: AsyncClient, shared_auth: dict[str, str]
) -> None:
    """Switching one resource's variant must update only that resource's snapshot."""
    client, auth = shared_client, shared_auth
    project_id = await _create_project(client, auth)
    boq_id = await _create_boq(client, auth, project_id)

    create_resp = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/positions/",
        json={
            "boq_id": boq_id,
            "ordinal": "MR.004",
            "description": "Selective re-stamp",
            "unit": "m3",
            "quantity": 1.0,
            "unit_rate": 100.0,
            "source": "cost_database",
            "metadata": {
                "currency": "EUR",
                "resources": [
                    {
                        "name": "Resource A",
                        "code": "RA",
                        "unit": "m3",
                        "quantity": 1.0,
                        "unit_rate": 60.0,
                        "variant": {"label": "RA-v1", "price": 60.0, "index": 0},
                    },
                    {
                        "name": "Resource B",
                        "code": "RB",
                        "unit": "kg",
                        "quantity": 10.0,
                        "unit_rate": 4.0,
                        "variant": {"label": "RB-v1", "price": 4.0, "index": 0},
                    },
                ],
            },
        },
        headers=auth,
    )
    assert create_resp.status_code == 201, create_resp.text
    pos_id = create_resp.json()["id"]
    orig_a = create_resp.json()["metadata"]["resources"][0]["variant_snapshot"]
    orig_b = create_resp.json()["metadata"]["resources"][1]["variant_snapshot"]

    await asyncio.sleep(1.1)

    # Switch Resource B's variant only.
    patch_resp = await client.patch(
        f"/api/v1/boq/positions/{pos_id}",
        json={
            "metadata": {
                "currency": "EUR",
                "resources": [
                    {
                        "name": "Resource A",
                        "code": "RA",
                        "unit": "m3",
                        "quantity": 1.0,
                        "unit_rate": 60.0,
                        "variant": {"label": "RA-v1", "price": 60.0, "index": 0},
                    },
                    {
                        "name": "Resource B",
                        "code": "RB",
                        "unit": "kg",
                        "quantity": 10.0,
                        "unit_rate": 5.5,
                        "variant": {"label": "RB-v3", "price": 5.5, "index": 2},
                    },
                ],
            },
        },
        headers=auth,
    )
    assert patch_resp.status_code == 200, patch_resp.text
    new_resources = patch_resp.json()["metadata"]["resources"]
    assert new_resources[0]["variant_snapshot"]["captured_at"] == orig_a["captured_at"], (
        "Resource A captured_at must not move when its variant is unchanged"
    )
    assert new_resources[1]["variant_snapshot"]["label"] == "RB-v3"
    assert new_resources[1]["variant_snapshot"]["rate"] == 5.5
    assert new_resources[1]["variant_snapshot"]["captured_at"] != orig_b["captured_at"], (
        "Resource B captured_at must advance when its variant changed"
    )
