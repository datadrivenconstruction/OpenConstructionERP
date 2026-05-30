"""BOQ "refresh from model" over the canonical ``oe_bim_boq_link`` table.

Regression coverage for the two-table-divergence bug: a position bound
through the BIM viewer's ``BOQElementLink`` (``oe_bim_boq_link``) — NOT a
``QuantityLink`` — was invisible to "Refresh from model", which reported
"no model linked" even though it was. The refresh/apply path now surfaces
each such position as a pseudo-link whose ``link_id == position_id`` and
recomputes it through the shared dimensional engine.

Covers end-to-end through the router:

* Refresh sees a BOQElementLink-bound position (``checked`` > 0, so the
  "no model links" toast can no longer fire) and reports old→new→delta.
* Apply (link_id == position_id) re-syncs the quantity, recomputes
  ``total`` exactly, and records ``metadata.model_quantity_pull`` with
  ``source == "bim_element_link"``.
* A count-unit position takes the element *count*, never geometry
  (E-XMOD-003).

Test isolation matches ``test_boq_quantity_links_and_compare.py``: the
per-session temp SQLite redirect + synchronous event-bus shim come from
``backend/tests/conftest.py``; the temp DB gets every table from
``create_all`` so no alembic upgrade is needed.

Run:
    cd backend
    python -m pytest tests/integration/test_boq_bim_element_link_refresh.py -v --tb=short
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest_asyncio.fixture(scope="module")
async def client() -> AsyncClient:
    """Module-scoped client driving the full app lifecycle (creates tables)."""
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
async def auth(client: AsyncClient) -> dict[str, str]:
    """Register + force-promote-to-admin + login → bearer header."""
    unique = uuid.uuid4().hex[:8]
    email = f"belink-{unique}@test.io"
    password = f"BELink{unique}9!"

    reg = await client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": "BIM Element Link Tester",
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
    data: dict = {}
    for attempt in range(3):
        resp = await client.post(
            "/api/v1/users/auth/login",
            json={"email": email, "password": password},
        )
        data = resp.json()
        token = data.get("access_token", "")
        if token:
            break
        if "Too many login attempts" in str(data.get("detail", "")):
            await asyncio.sleep(2 * (attempt + 1))
            continue
        break
    assert token, f"Login failed: {data}"
    return {"Authorization": f"Bearer {token}"}


# ── Helpers ───────────────────────────────────────────────────────────────


async def _create_project(client: AsyncClient, auth: dict[str, str], **extra) -> str:
    body = {
        "name": f"BELink {uuid.uuid4().hex[:6]}",
        "description": "BOQElementLink refresh integration",
        "currency": "EUR",
    }
    body.update(extra)
    resp = await client.post("/api/v1/projects/", json=body, headers=auth)
    assert resp.status_code == 201, f"Create project failed: {resp.text}"
    return resp.json()["id"]


async def _create_boq(client: AsyncClient, auth: dict[str, str], project_id: str) -> str:
    resp = await client.post(
        "/api/v1/boq/boqs/",
        json={
            "project_id": project_id,
            "name": f"BELink BOQ {uuid.uuid4().hex[:6]}",
            "description": "BOQElementLink refresh",
        },
        headers=auth,
    )
    assert resp.status_code == 201, f"Create BOQ failed: {resp.text}"
    return resp.json()["id"]


async def _add_position(client: AsyncClient, auth: dict[str, str], boq_id: str, **body):
    payload = {"boq_id": boq_id, "unit": "m3", "quantity": 0.0}
    payload.update(body)
    resp = await client.post(f"/api/v1/boq/boqs/{boq_id}/positions/", json=payload, headers=auth)
    assert resp.status_code == 201, f"Add position failed: {resp.text}"
    return resp.json()


async def _create_model_with_elements(
    client: AsyncClient,
    auth: dict[str, str],
    project_id: str,
    *,
    version: str,
    elements: list[dict],
) -> tuple[str, dict[str, str]]:
    """Create a BIMModel + elements; return ``(model_id, {stable_id: db_id})``."""
    m = await client.post(
        "/api/v1/bim_hub/",
        json={
            "project_id": project_id,
            "name": f"Model v{version}",
            "version": version,
            "status": "ready",
        },
        headers=auth,
    )
    assert m.status_code == 201, f"Create model failed: {m.text}"
    model_id = m.json()["id"]

    e = await client.post(
        f"/api/v1/bim_hub/models/{model_id}/elements/",
        json={"elements": elements},
        headers=auth,
    )
    assert e.status_code == 201, f"Bulk import elements failed: {e.text}"
    id_by_stable = {item["stable_id"]: item["id"] for item in e.json()["items"]}
    return model_id, id_by_stable


async def _link_element(client: AsyncClient, auth: dict[str, str], position_id: str, element_id: str):
    """Create a canonical ``oe_bim_boq_link`` (BIM viewer link)."""
    resp = await client.post(
        "/api/v1/bim_hub/links/",
        json={"boq_position_id": position_id, "bim_element_id": element_id},
        headers=auth,
    )
    assert resp.status_code == 201, f"Create BIM link failed: {resp.text}"
    return resp.json()


# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_refresh_and_apply_surfaces_bim_element_link_position(
    client: AsyncClient, auth: dict[str, str]
) -> None:
    """A position linked via the BIM viewer is visible to refresh + applies."""
    project_id = await _create_project(client, auth)
    boq_id = await _create_boq(client, auth, project_id)
    pos = await _add_position(
        client,
        auth,
        boq_id,
        ordinal="01.001",
        description="RC slab via viewer",
        unit="m3",
        quantity=0.0,
        unit_rate=100.0,
    )
    pos_id = pos["id"]

    _model_id, ids = await _create_model_with_elements(
        client,
        auth,
        project_id,
        version="1",
        elements=[
            {"stable_id": "S1", "element_type": "slab", "quantities": {"volume_m3": 6.0}},
            {"stable_id": "S2", "element_type": "slab", "quantities": {"volume_m3": 4.0}},
        ],
    )

    # Link both elements through the BIM viewer table. Option C: binding
    # NEVER mutates the quantity — it stays 0 until the explicit refresh +
    # apply flow pulls it in (propose → human confirms).
    await _link_element(client, auth, pos_id, ids["S1"])
    await _link_element(client, auth, pos_id, ids["S2"])

    synced = await client.get(f"/api/v1/boq/boqs/{boq_id}", headers=auth)
    synced_qty = next(x["quantity"] for x in synced.json()["positions"] if x["id"] == pos_id)
    assert float(synced_qty) == 0.0

    # Refresh: no QuantityLink exists, but the BOQElementLink position must
    # still be checked (the bug: "no model linked" used to fire here).
    refresh = await client.post(f"/api/v1/boq/boqs/{boq_id}/quantity-links/refresh/", headers=auth)
    assert refresh.status_code == 200, refresh.text
    rbody = refresh.json()
    assert rbody["checked"] >= 1
    row = next(r for r in rbody["rows"] if r["position_id"] == pos_id)
    # Pseudo-link contract: link_id == position_id.
    assert row["link_id"] == pos_id
    assert row["changed"] is True
    assert row["status"] == "stale"
    assert float(row["old_quantity"]) == 0.0
    assert float(row["new_quantity"]) == 10.0
    assert float(row["delta"]) == 10.0
    assert sorted(row["contributing_elements"]) == ["S1", "S2"]

    # Refresh is read-only — quantity still 0.
    after = await client.get(f"/api/v1/boq/boqs/{boq_id}", headers=auth)
    after_qty = next(x["quantity"] for x in after.json()["positions"] if x["id"] == pos_id)
    assert float(after_qty) == 0.0

    # Apply the pseudo-link (link_id == position_id).
    apply = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/quantity-links/apply/",
        json={"link_ids": [pos_id]},
        headers=auth,
    )
    assert apply.status_code == 200, apply.text
    abody = apply.json()
    assert abody["applied"] == 1
    assert abody["skipped"] == 0
    assert abody["results"][0]["applied"] is True

    applied = await client.get(f"/api/v1/boq/boqs/{boq_id}", headers=auth)
    applied_pos = next(x for x in applied.json()["positions"] if x["id"] == pos_id)
    assert float(applied_pos["quantity"]) == 10.0
    assert float(applied_pos["total"]) == 10.0 * 100.0
    prov = applied_pos["metadata"]["model_quantity_pull"]
    assert prov["source"] == "bim_element_link"
    assert prov["new_quantity"] in ("10", "10.0", "10.0000")
    assert len(applied_pos["metadata"]["model_quantity_pull_history"]) == 1


@pytest.mark.asyncio
async def test_refresh_count_unit_position_takes_element_count(
    client: AsyncClient, auth: dict[str, str]
) -> None:
    """A count-unit position takes the element count, never geometry (E-XMOD-003)."""
    project_id = await _create_project(client, auth)
    boq_id = await _create_boq(client, auth, project_id)
    pos = await _add_position(
        client,
        auth,
        boq_id,
        ordinal="02.001",
        description="Doors (count)",
        unit="pcs",
        quantity=0.0,
        unit_rate=250.0,
    )
    pos_id = pos["id"]

    _model_id, ids = await _create_model_with_elements(
        client,
        auth,
        project_id,
        version="1",
        elements=[
            {"stable_id": "D1", "element_type": "door", "quantities": {"volume_m3": 0.3}},
            {"stable_id": "D2", "element_type": "door", "quantities": {"volume_m3": 0.3}},
            {"stable_id": "D3", "element_type": "door", "quantities": {"volume_m3": 0.3}},
        ],
    )
    for sid in ("D1", "D2", "D3"):
        await _link_element(client, auth, pos_id, ids[sid])

    # Option C: binding NEVER mutates the quantity — it stays 0 until the
    # explicit refresh + apply flow pulls it in (no auto-sync on link).
    synced = await client.get(f"/api/v1/boq/boqs/{boq_id}", headers=auth)
    synced_pos = next(x for x in synced.json()["positions"] if x["id"] == pos_id)
    assert float(synced_pos["quantity"]) == 0.0

    refresh = await client.post(f"/api/v1/boq/boqs/{boq_id}/quantity-links/refresh/", headers=auth)
    assert refresh.status_code == 200, refresh.text
    row = next(r for r in refresh.json()["rows"] if r["position_id"] == pos_id)
    assert row["aggregation"] == "count"
    # Count unit takes the element count (3), never the 0.9 m³ volume sum.
    assert float(row["new_quantity"]) == 3.0
    # Quantity was never synced (binding no longer auto-syncs) → stale: 0 → 3.
    assert float(row["old_quantity"]) == 0.0
    assert row["changed"] is True
