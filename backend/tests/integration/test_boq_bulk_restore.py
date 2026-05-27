"""v3.12.0 Stream A — BOQ bulk-update + per-field restore endpoints.

Covers:

* ``PATCH /v1/boq/boqs/{id}/positions/bulk-update/`` with ``updates``,
  ``rate_factor``, and ``quantity_factor`` payloads.
* Validation rejections (mixed mutation styles, disallowed update keys).
* ``POST /v1/boq/boqs/{id}/positions/{pid}/restore-field/`` round-trip
  against a real prior :class:`BOQActivityLog` entry.
* Cross-position log-id mismatch -> 422.

Run:

    cd backend
    python -m pytest tests/integration/test_boq_bulk_restore.py -v --tb=short
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app

# ── Shared fixtures (module-scoped — same pattern as the cost-link test) ──


@pytest_asyncio.fixture(scope="module")
async def shared_client() -> AsyncClient:
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
    unique = uuid.uuid4().hex[:8]
    email = f"boqbulk-{unique}@test.io"
    password = f"BoqBulk{unique}9!"

    reg = await shared_client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": "BOQ Bulk Tester",
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


# ── Helpers ──────────────────────────────────────────────────────────────


async def _create_project_with_boq(client: AsyncClient, auth: dict[str, str]) -> tuple[str, str]:
    proj = await client.post(
        "/api/v1/projects/",
        json={
            "name": f"BulkRestore {uuid.uuid4().hex[:6]}",
            "description": "v3.12 Stream A integration",
            "region": "DACH",
            "classification_standard": "din276",
            "currency": "EUR",
        },
        headers=auth,
    )
    assert proj.status_code == 201, f"create project: {proj.text}"
    project_id = proj.json()["id"]
    boq = await client.post(
        "/api/v1/boq/boqs/",
        json={
            "project_id": project_id,
            "name": f"BulkRestore BOQ {uuid.uuid4().hex[:6]}",
            "description": "v3.12 Stream A",
        },
        headers=auth,
    )
    assert boq.status_code == 201, f"create boq: {boq.text}"
    return project_id, boq.json()["id"]


async def _add_position(
    client: AsyncClient,
    auth: dict[str, str],
    boq_id: str,
    *,
    ordinal: str,
    quantity: float = 10.0,
    unit_rate: float = 100.0,
    unit: str = "m3",
    description: str | None = None,
) -> str:
    resp = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/positions/",
        json={
            "boq_id": boq_id,
            "ordinal": ordinal,
            "description": description or f"BulkRestore line {ordinal}",
            "unit": unit,
            "quantity": quantity,
            "unit_rate": unit_rate,
        },
        headers=auth,
    )
    assert resp.status_code == 201, f"add position: {resp.text}"
    return resp.json()["id"]


# ═══════════════════════════════════════════════════════════════════════════
# Bulk update — happy paths
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_bulk_update_rate_factor_multiplies_unit_rate(
    shared_client: AsyncClient, shared_auth: dict[str, str]
) -> None:
    """``rate_factor`` multiplies each unit_rate and recomputes total."""
    client, auth = shared_client, shared_auth
    _, boq_id = await _create_project_with_boq(client, auth)

    p1 = await _add_position(client, auth, boq_id, ordinal="01", unit_rate=100.0, quantity=10.0)
    p2 = await _add_position(client, auth, boq_id, ordinal="02", unit_rate=50.0, quantity=4.0)

    resp = await client.patch(
        f"/api/v1/boq/boqs/{boq_id}/positions/bulk-update/",
        json={"ids": [p1, p2], "rate_factor": 1.10},
        headers=auth,
    )
    assert resp.status_code == 200, f"bulk-update: {resp.text}"
    body = resp.json()
    assert body["updated"] == 2
    assert body["skipped"] == 0
    assert body["failed_ids"] == []
    assert body["log_id"]  # umbrella audit row present

    # Verify the values landed.
    g1 = await client.get(f"/api/v1/boq/positions/{p1}", headers=auth)
    g2 = await client.get(f"/api/v1/boq/positions/{p2}", headers=auth)
    assert g1.status_code == 200
    assert g2.status_code == 200
    assert abs(float(g1.json()["unit_rate"]) - 110.0) < 0.01
    assert abs(float(g1.json()["total"]) - 1100.0) < 0.01
    assert abs(float(g2.json()["unit_rate"]) - 55.0) < 0.01
    assert abs(float(g2.json()["total"]) - 220.0) < 0.01


@pytest.mark.asyncio
async def test_bulk_update_quantity_factor_and_total_recompute(
    shared_client: AsyncClient, shared_auth: dict[str, str]
) -> None:
    """``quantity_factor`` multiplies each quantity and recomputes total."""
    client, auth = shared_client, shared_auth
    _, boq_id = await _create_project_with_boq(client, auth)

    p1 = await _add_position(client, auth, boq_id, ordinal="01", quantity=10.0, unit_rate=200.0)

    resp = await client.patch(
        f"/api/v1/boq/boqs/{boq_id}/positions/bulk-update/",
        json={"ids": [p1], "quantity_factor": 2.5},
        headers=auth,
    )
    assert resp.status_code == 200, f"bulk-update: {resp.text}"
    assert resp.json()["updated"] == 1

    g1 = await client.get(f"/api/v1/boq/positions/{p1}", headers=auth)
    assert g1.status_code == 200
    assert abs(float(g1.json()["quantity"]) - 25.0) < 0.01
    assert abs(float(g1.json()["total"]) - 5000.0) < 0.01


@pytest.mark.asyncio
async def test_bulk_update_set_unit_allowlist(shared_client: AsyncClient, shared_auth: dict[str, str]) -> None:
    """Direct field set works for the allow-listed keys (here: ``unit``)."""
    client, auth = shared_client, shared_auth
    _, boq_id = await _create_project_with_boq(client, auth)

    p1 = await _add_position(client, auth, boq_id, ordinal="01", unit="pcs")
    p2 = await _add_position(client, auth, boq_id, ordinal="02", unit="pcs")

    resp = await client.patch(
        f"/api/v1/boq/boqs/{boq_id}/positions/bulk-update/",
        json={"ids": [p1, p2], "updates": {"unit": "m"}},
        headers=auth,
    )
    assert resp.status_code == 200, f"bulk-update: {resp.text}"
    assert resp.json()["updated"] == 2

    for pid in (p1, p2):
        g = await client.get(f"/api/v1/boq/positions/{pid}", headers=auth)
        assert g.json()["unit"] == "m"


# ═══════════════════════════════════════════════════════════════════════════
# Bulk update — rejections
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_bulk_update_rejects_mixed_mutation_styles(
    shared_client: AsyncClient, shared_auth: dict[str, str]
) -> None:
    """Sending both ``rate_factor`` and ``quantity_factor`` returns 422."""
    client, auth = shared_client, shared_auth
    _, boq_id = await _create_project_with_boq(client, auth)
    p1 = await _add_position(client, auth, boq_id, ordinal="01")

    resp = await client.patch(
        f"/api/v1/boq/boqs/{boq_id}/positions/bulk-update/",
        json={"ids": [p1], "rate_factor": 1.10, "quantity_factor": 2.0},
        headers=auth,
    )
    assert resp.status_code == 422, f"expected 422, got {resp.status_code}: {resp.text}"


@pytest.mark.asyncio
async def test_bulk_update_rejects_disallowed_updates_key(
    shared_client: AsyncClient, shared_auth: dict[str, str]
) -> None:
    """``updates.quantity`` is not in the allowlist — must be rejected."""
    client, auth = shared_client, shared_auth
    _, boq_id = await _create_project_with_boq(client, auth)
    p1 = await _add_position(client, auth, boq_id, ordinal="01")

    resp = await client.patch(
        f"/api/v1/boq/boqs/{boq_id}/positions/bulk-update/",
        json={"ids": [p1], "updates": {"quantity": 99}},
        headers=auth,
    )
    assert resp.status_code == 422, f"expected 422, got {resp.status_code}: {resp.text}"


@pytest.mark.asyncio
async def test_bulk_update_404_on_cross_boq_id_smuggle(shared_client: AsyncClient, shared_auth: dict[str, str]) -> None:
    """Position id from a different BOQ must yield 404, never silent write."""
    client, auth = shared_client, shared_auth
    _, boq_a = await _create_project_with_boq(client, auth)
    _, boq_b = await _create_project_with_boq(client, auth)

    p_in_b = await _add_position(client, auth, boq_b, ordinal="01")

    resp = await client.patch(
        f"/api/v1/boq/boqs/{boq_a}/positions/bulk-update/",
        json={"ids": [p_in_b], "rate_factor": 1.10},
        headers=auth,
    )
    assert resp.status_code == 404, f"expected 404, got {resp.status_code}: {resp.text}"


# ═══════════════════════════════════════════════════════════════════════════
# Restore field
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_restore_field_round_trips_via_activity_log(
    shared_client: AsyncClient, shared_auth: dict[str, str]
) -> None:
    """Edit unit_rate -> read activity log -> restore old value via endpoint."""
    client, auth = shared_client, shared_auth
    _, boq_id = await _create_project_with_boq(client, auth)
    p1 = await _add_position(client, auth, boq_id, ordinal="01", unit_rate=100.0)

    # Mutation that the audit-log machinery will record.
    patch = await client.patch(
        f"/api/v1/boq/positions/{p1}",
        json={"unit_rate": 250.0},
        headers=auth,
    )
    assert patch.status_code == 200, f"patch: {patch.text}"

    # Pull the activity log and find the matching entry.
    act = await client.get(f"/api/v1/boq/boqs/{boq_id}/activity/", headers=auth)
    assert act.status_code == 200, f"activity: {act.text}"
    entries = act.json()["items"]
    candidate = next(
        (
            e
            for e in entries
            if e["action"] == "position.updated"
            and e.get("target_id") == p1
            and isinstance(e.get("changes"), dict)
            and "unit_rate" in e["changes"]
        ),
        None,
    )
    assert candidate is not None, f"no matching log entry in {entries!r}"
    old_value = candidate["changes"]["unit_rate"]["old"]

    # Restore the old unit_rate.
    rest = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/positions/{p1}/restore-field/",
        json={
            "field": "unit_rate",
            "value": old_value,
            "log_id": candidate["id"],
        },
        headers=auth,
    )
    assert rest.status_code == 200, f"restore: {rest.text}"
    body = rest.json()
    assert body["field"] == "unit_rate"
    assert body["source_log_id"] == candidate["id"]

    # Confirm the value reverted.
    g = await client.get(f"/api/v1/boq/positions/{p1}", headers=auth)
    assert abs(float(g.json()["unit_rate"]) - float(old_value)) < 0.01


@pytest.mark.asyncio
async def test_restore_field_rejects_log_targeting_another_position(
    shared_client: AsyncClient, shared_auth: dict[str, str]
) -> None:
    """Log entries from another position must be rejected with 422."""
    client, auth = shared_client, shared_auth
    _, boq_id = await _create_project_with_boq(client, auth)
    p1 = await _add_position(client, auth, boq_id, ordinal="01")
    p2 = await _add_position(client, auth, boq_id, ordinal="02")

    # Mutate p1 to create a log row for it.
    await client.patch(
        f"/api/v1/boq/positions/{p1}",
        json={"unit_rate": 999.0},
        headers=auth,
    )
    act = await client.get(f"/api/v1/boq/boqs/{boq_id}/activity/", headers=auth)
    candidate = next(e for e in act.json()["items"] if e["action"] == "position.updated" and e.get("target_id") == p1)

    # Try to restore p1's log onto p2 — must be rejected.
    rest = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/positions/{p2}/restore-field/",
        json={
            "field": "unit_rate",
            "value": 1.0,
            "log_id": candidate["id"],
        },
        headers=auth,
    )
    assert rest.status_code == 422, f"expected 422, got {rest.status_code}: {rest.text}"
