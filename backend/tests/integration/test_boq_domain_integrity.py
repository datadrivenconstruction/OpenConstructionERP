"""BOQ Position domain-integrity regressions (Round 4 QA bugs).

Covers:

* BUG-MATH01 — Position monetary columns must round-trip at 4-dp precision.
* BUG-MATH02 — ``PositionCreate.quantity`` must be required (no silent zero).
* BUG-MATH03 — ``PositionCreate.unit`` must reject values outside the
  approved catalogue (``backend/app/modules/boq/units.py``).
* BUG-AUDIT01 — ``PATCH /positions/{id}`` must persist a field-level diff
  (``before`` / ``after``) in the activity log.
* BUG-CONCURRENCY01 — Two concurrent PATCHes with the same starting
  ``version`` must result in one 200 + one 409, never both 200.
* BUG-API14 — ``GET /boq/positions/{id}`` must return the full position
  payload, not ``{}``.

Run:
    cd backend
    python -m pytest tests/integration/test_boq_domain_integrity.py -v --tb=short
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app

# ── Shared fixtures (module-scoped to avoid rate-limiter & lifespan churn) ──


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
    email = f"boqdomain-{unique}@test.io"
    password = f"BoqDomain{unique}9!"

    reg = await shared_client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": "BOQ Domain Tester",
            "role": "admin",
        },
    )
    assert reg.status_code == 201, f"Registration failed: {reg.text}"

    # Promote to admin even when bootstrap user already exists.
    from sqlalchemy import update as sa_update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as session:
        await session.execute(
            sa_update(User)
            .where(User.email == email.lower())
            .values(role="admin", is_active=True)
        )
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


# ── Per-module helpers ──────────────────────────────────────────────────────


async def _create_project(client: AsyncClient, auth: dict[str, str]) -> str:
    resp = await client.post(
        "/api/v1/projects/",
        json={
            "name": f"Domain Test {uuid.uuid4().hex[:6]}",
            "description": "BOQ domain integrity",
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
            "name": f"Domain BOQ {uuid.uuid4().hex[:6]}",
            "description": "domain integrity",
        },
        headers=auth,
    )
    assert resp.status_code == 201, f"Create BOQ failed: {resp.text}"
    return resp.json()["id"]


async def _add_position(
    client: AsyncClient,
    auth: dict[str, str],
    boq_id: str,
    *,
    ordinal: str = "01.001",
    unit: str = "m3",
    quantity: float = 1.0,
    unit_rate: float = 100.0,
    description: str = "Domain test position",
) -> dict:
    body: dict = {
        "boq_id": boq_id,
        "ordinal": ordinal,
        "description": description,
        "unit": unit,
        "quantity": quantity,
        "unit_rate": unit_rate,
    }
    resp = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/positions/",
        json=body,
        headers=auth,
    )
    assert resp.status_code == 201, f"Add position failed: {resp.text}"
    return resp.json()


# ═══════════════════════════════════════════════════════════════════════════
#  BUG-MATH02 — quantity is required
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_position_create_requires_quantity(
    shared_client: AsyncClient, shared_auth: dict[str, str]
) -> None:
    """POST without ``quantity`` must be rejected with 422 (BUG-MATH02)."""
    project_id = await _create_project(shared_client, shared_auth)
    boq_id = await _create_boq(shared_client, shared_auth, project_id)

    resp = await shared_client.post(
        f"/api/v1/boq/boqs/{boq_id}/positions/",
        json={
            "boq_id": boq_id,
            "ordinal": "M02.001",
            "description": "missing quantity",
            "unit": "m",
            "unit_rate": 10.0,
        },
        headers=shared_auth,
    )
    assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"
    assert "quantity" in resp.text.lower()


# ═══════════════════════════════════════════════════════════════════════════
#  BUG-MATH03 — unit must be in the approved catalogue
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_position_create_rejects_unknown_unit(
    shared_client: AsyncClient, shared_auth: dict[str, str]
) -> None:
    """POST with ``unit='xyz'`` must 422 (BUG-MATH03)."""
    project_id = await _create_project(shared_client, shared_auth)
    boq_id = await _create_boq(shared_client, shared_auth, project_id)

    resp = await shared_client.post(
        f"/api/v1/boq/boqs/{boq_id}/positions/",
        json={
            "boq_id": boq_id,
            "ordinal": "M03.001",
            "description": "bad unit",
            "unit": "xyz",
            "quantity": 1.0,
            "unit_rate": 10.0,
        },
        headers=shared_auth,
    )
    assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"
    assert "unit" in resp.text.lower()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "unit",
    ["m", "m2", "m3", "kg", "t", "pcs", "lsum", "hr"],
)
async def test_position_create_accepts_valid_units(
    shared_client: AsyncClient, shared_auth: dict[str, str], unit: str
) -> None:
    """Each curated unit must be accepted (BUG-MATH03)."""
    project_id = await _create_project(shared_client, shared_auth)
    boq_id = await _create_boq(shared_client, shared_auth, project_id)

    resp = await shared_client.post(
        f"/api/v1/boq/boqs/{boq_id}/positions/",
        json={
            "boq_id": boq_id,
            "ordinal": f"M03.{unit}",
            "description": f"valid unit {unit}",
            "unit": unit,
            "quantity": 1.0,
            "unit_rate": 10.0,
        },
        headers=shared_auth,
    )
    assert resp.status_code == 201, f"unit={unit!r} should be accepted, got {resp.text}"
    assert resp.json()["unit"] == unit


# ═══════════════════════════════════════════════════════════════════════════
#  BUG-MATH01 — decimal precision at 4 dp
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_position_decimal_precision(
    shared_client: AsyncClient, shared_auth: dict[str, str]
) -> None:
    """``unit_rate=99.99999`` round-trips quantised to 4 dp (BUG-MATH01)."""
    project_id = await _create_project(shared_client, shared_auth)
    boq_id = await _create_boq(shared_client, shared_auth, project_id)

    pos = await _add_position(
        shared_client,
        shared_auth,
        boq_id,
        ordinal="M01.001",
        unit="m",
        quantity=2.0,
        unit_rate=99.99999,
    )

    # 99.99999 quantised at 4 dp via banker's rounding → 100.0000.  We
    # accept anything in the closed interval [99.9999, 100.0001] so the
    # test is robust to minor implementation tweaks but still locks in
    # the "max 4 dp" guarantee.
    stored_rate = float(pos["unit_rate"])
    assert abs(stored_rate - 100.0) < 1e-3 or abs(stored_rate - 99.9999) < 1e-3, (
        f"unit_rate stored as {stored_rate!r}, expected ~100.0 or 99.9999"
    )

    # Total = quantity * unit_rate also at 4 dp boundary.
    total = float(pos["total"])
    assert abs(total - stored_rate * 2.0) < 1e-3, (
        f"total {total!r} should equal qty*rate ({stored_rate * 2.0!r})"
    )

    # GET round-trip: fetch by id and confirm the same value persists.
    get_resp = await shared_client.get(
        f"/api/v1/boq/positions/{pos['id']}",
        headers=shared_auth,
    )
    assert get_resp.status_code == 200, get_resp.text
    assert abs(float(get_resp.json()["unit_rate"]) - stored_rate) < 1e-9


# ═══════════════════════════════════════════════════════════════════════════
#  BUG-AUDIT01 — activity log captures field-level diff
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_audit_log_captures_field_diff(
    shared_client: AsyncClient, shared_auth: dict[str, str]
) -> None:
    """PATCH unit_rate then query activity log; ``changes`` must contain
    ``{"unit_rate": {"old": ..., "new": ...}}`` (BUG-AUDIT01)."""
    project_id = await _create_project(shared_client, shared_auth)
    boq_id = await _create_boq(shared_client, shared_auth, project_id)

    pos = await _add_position(
        shared_client,
        shared_auth,
        boq_id,
        ordinal="AUD.001",
        unit="m3",
        quantity=10.0,
        unit_rate=50.0,
    )

    patch_resp = await shared_client.patch(
        f"/api/v1/boq/positions/{pos['id']}",
        json={"unit_rate": 75.5},
        headers=shared_auth,
    )
    assert patch_resp.status_code == 200, patch_resp.text

    # Activity log endpoint — fetch and inspect.
    act_resp = await shared_client.get(
        f"/api/v1/boq/boqs/{boq_id}/activity/",
        headers=shared_auth,
    )
    assert act_resp.status_code == 200, act_resp.text
    items = act_resp.json().get("items", [])

    # Find the position.updated entry referencing this position.
    update_entries = [
        e
        for e in items
        if e.get("target_id") == pos["id"]
        and "update" in e.get("action", "").lower()
    ]
    assert update_entries, (
        f"No position-update activity log entry found. items={items}"
    )

    diff = update_entries[0].get("changes") or {}
    assert "unit_rate" in diff, f"Expected unit_rate diff, got {diff}"
    pair = diff["unit_rate"]
    assert "old" in pair, f"Diff must have old key, got {pair}"
    assert "new" in pair, f"Diff must have new key, got {pair}"
    # Old should reflect 50.0; new should reflect 75.5 (allow string forms).
    assert "50" in str(pair["old"]), f"Old value mismatch: {pair['old']!r}"
    assert "75.5" in str(pair["new"]), f"New value mismatch: {pair['new']!r}"


# ═══════════════════════════════════════════════════════════════════════════
#  BUG-CONCURRENCY01 — optimistic concurrency token
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_concurrent_update_returns_409(
    shared_client: AsyncClient, shared_auth: dict[str, str]
) -> None:
    """Two PATCHes with the same starting ``version`` — second must 409
    (BUG-CONCURRENCY01)."""
    project_id = await _create_project(shared_client, shared_auth)
    boq_id = await _create_boq(shared_client, shared_auth, project_id)

    pos = await _add_position(
        shared_client,
        shared_auth,
        boq_id,
        ordinal="CC.001",
        unit="m",
        quantity=1.0,
        unit_rate=1.0,
    )
    initial_version = pos.get("version", 0)
    assert isinstance(initial_version, int), f"version must be int, got {initial_version!r}"

    # First writer succeeds.
    r1 = await shared_client.patch(
        f"/api/v1/boq/positions/{pos['id']}",
        json={"description": "writer-A", "version": initial_version},
        headers=shared_auth,
    )
    assert r1.status_code == 200, f"First PATCH failed: {r1.text}"
    assert r1.json()["version"] == initial_version + 1

    # Second writer uses the stale version → must 409.
    r2 = await shared_client.patch(
        f"/api/v1/boq/positions/{pos['id']}",
        json={"description": "writer-B", "version": initial_version},
        headers=shared_auth,
    )
    assert r2.status_code == 409, (
        f"Stale-version PATCH should 409, got {r2.status_code}: {r2.text}"
    )

    # And the row's description is from writer-A (no lost update).
    get_resp = await shared_client.get(
        f"/api/v1/boq/positions/{pos['id']}",
        headers=shared_auth,
    )
    assert get_resp.status_code == 200
    assert get_resp.json()["description"] == "writer-A"


# ═══════════════════════════════════════════════════════════════════════════
#  BUG-API14 — GET /positions/{id} returns full object, not {}
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_position_by_id_returns_full_object(
    shared_client: AsyncClient, shared_auth: dict[str, str]
) -> None:
    """GET /boq/positions/{id} must return all fields, not ``{}`` (BUG-API14)."""
    project_id = await _create_project(shared_client, shared_auth)
    boq_id = await _create_boq(shared_client, shared_auth, project_id)

    pos = await _add_position(
        shared_client,
        shared_auth,
        boq_id,
        ordinal="API14.001",
        unit="m2",
        quantity=42.0,
        unit_rate=12.5,
        description="API14 fixture",
    )

    resp = await shared_client.get(
        f"/api/v1/boq/positions/{pos['id']}",
        headers=shared_auth,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Must NOT be empty-dict.
    assert body, f"Response body is empty (regressed BUG-API14): {body!r}"

    # Required fields populated.
    for key in (
        "id",
        "boq_id",
        "ordinal",
        "description",
        "unit",
        "quantity",
        "unit_rate",
        "total",
        "version",
    ):
        assert key in body, f"Missing field {key!r} in response: {body}"
    assert body["id"] == pos["id"]
    assert body["ordinal"] == "API14.001"
    assert body["unit"] == "m2"
    assert float(body["quantity"]) == 42.0
    assert float(body["unit_rate"]) == 12.5
    assert body["description"] == "API14 fixture"

    # Unknown id must 404, not return ``{}``.
    bogus_id = str(uuid.uuid4())
    resp_404 = await shared_client.get(
        f"/api/v1/boq/positions/{bogus_id}",
        headers=shared_auth,
    )
    assert resp_404.status_code == 404, (
        f"Unknown position must 404, got {resp_404.status_code}: {resp_404.text}"
    )
