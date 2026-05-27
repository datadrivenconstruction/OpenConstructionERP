"""Feature 1+2 — model→BOQ quantity links + line-level BOQ compare.

Covers end-to-end through the router:

Feature 1 (live model→BOQ quantity binding):
* Create a quantity link binding a position to BIM elements (no quantity
  mutation on create — propose-only, CLAUDE.md §7).
* Refresh detects a model-version change and flips the link to ``stale``,
  returning a review payload with old/new/delta.
* Confirm/apply writes the re-pulled quantity, recomputes ``total``
  exactly, and records provenance into ``metadata.model_quantity_pull``.
* Apply is gated to the explicitly-listed link ids only.

Feature 2 (estimate baseline / line-level compare):
* compare classifies added / removed / qty_changed / rate_changed.
* multi-currency: foreign-currency totals rebase into the project base
  currency before the direct-cost delta is summed.

Test isolation (``feedback_test_isolation.md``): the per-session temp
SQLite redirect, eager model registration and the synchronous event-bus
shim are all provided by ``backend/tests/conftest.py`` — the production
``openestimate.db`` is never touched. The fresh temp DB gets the new
``oe_boq_quantity_link`` table from ``create_all`` (the model is the
source of truth on a clean SQLite DB), so no ``alembic upgrade`` is
needed for the test.

Run:
    cd backend
    python -m pytest tests/integration/test_boq_quantity_links_and_compare.py -v --tb=short
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
    email = f"qlink-{unique}@test.io"
    password = f"QLink{unique}9!"

    reg = await client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": "Quantity Link Tester",
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
        "name": f"QLink {uuid.uuid4().hex[:6]}",
        "description": "Feature 1+2 integration",
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
            "name": f"QLink BOQ {uuid.uuid4().hex[:6]}",
            "description": "F1/F2",
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
    parent_model_id: str | None = None,
) -> str:
    """Create a BIMModel + elements via the BIM Hub HTTP API.

    Goes through the public ``POST /api/v1/bim_hub/`` +
    ``POST /api/v1/bim_hub/models/{id}/elements/`` endpoints (same client
    + event loop as the rest of the test) instead of the heavyweight
    file-upload/DDC path — the link feature only needs persisted
    BIMModel/BIMElement rows.
    """
    body: dict = {
        "project_id": project_id,
        "name": f"Model v{version}",
        "version": version,
        "status": "ready",
    }
    if parent_model_id:
        body["parent_model_id"] = parent_model_id
    m = await client.post("/api/v1/bim_hub/", json=body, headers=auth)
    assert m.status_code == 201, f"Create model failed: {m.text}"
    model_id = m.json()["id"]

    e = await client.post(
        f"/api/v1/bim_hub/models/{model_id}/elements/",
        json={"elements": elements},
        headers=auth,
    )
    assert e.status_code == 201, f"Bulk import elements failed: {e.text}"
    return model_id


# ═══════════════════════════════════════════════════════════════════════════
# Feature 1 — model→BOQ quantity links
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_quantity_link_create_refresh_stale_apply_provenance(client: AsyncClient, auth: dict[str, str]) -> None:
    """Full lifecycle: bind → revise model → refresh→stale → confirm→apply."""
    project_id = await _create_project(client, auth)
    boq_id = await _create_boq(client, auth, project_id)
    pos = await _add_position(
        client,
        auth,
        boq_id,
        ordinal="01.001",
        description="RC slab from model",
        unit="m3",
        quantity=10.0,
        unit_rate=185.0,
    )
    pos_id = pos["id"]

    # v1 model: two slabs, area_m2 30 + 20 → sum 50
    model_v1 = await _create_model_with_elements(
        client,
        auth,
        project_id,
        version="1",
        elements=[
            {"stable_id": "S1", "element_type": "slab", "quantities": {"area_m2": 30.0, "volume_m3": 6.0}},
            {"stable_id": "S2", "element_type": "slab", "quantities": {"area_m2": 20.0, "volume_m3": 4.0}},
        ],
    )

    # Bind: area_m2 sum → quantity. Create must NOT mutate the quantity.
    link_r = await client.post(
        f"/api/v1/boq/positions/{pos_id}/quantity-links/",
        json={
            "model_id": model_v1,
            "element_stable_ids": ["S1", "S2"],
            "quantity_field": "area_m2",
            "aggregation": "sum",
        },
        headers=auth,
    )
    assert link_r.status_code == 201, link_r.text
    link = link_r.json()
    assert link["status"] == "active"
    assert link["quantity_field"] == "area_m2"
    link_id = link["id"]

    # Quantity unchanged on create (propose-only).
    p = await client.get(f"/api/v1/boq/boqs/{boq_id}", headers=auth)
    cur_qty = next(x["quantity"] for x in p.json()["positions"] if x["id"] == pos_id)
    assert str(cur_qty) in ("10", "10.0", "10.0000")

    # List links for the position.
    listed = await client.get(f"/api/v1/boq/positions/{pos_id}/quantity-links/", headers=auth)
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    # Revise the model: new version (chained via parent_model_id) where
    # S1 grew to 35 and S2 to 25 → sum 60.
    await _create_model_with_elements(
        client,
        auth,
        project_id,
        version="2",
        parent_model_id=model_v1,
        elements=[
            {"stable_id": "S1", "element_type": "slab", "quantities": {"area_m2": 35.0, "volume_m3": 7.0}},
            {"stable_id": "S2", "element_type": "slab", "quantities": {"area_m2": 25.0, "volume_m3": 5.0}},
        ],
    )

    # Refresh — must resolve the latest version and flag stale.
    refresh = await client.post(f"/api/v1/boq/boqs/{boq_id}/quantity-links/refresh/", headers=auth)
    assert refresh.status_code == 200, refresh.text
    rbody = refresh.json()
    assert rbody["checked"] == 1
    assert rbody["stale"] == 1
    row = rbody["rows"][0]
    assert row["status"] == "stale"
    assert row["changed"] is True
    assert float(row["old_quantity"]) == 10.0
    assert float(row["new_quantity"]) == 60.0
    assert float(row["delta"]) == 50.0
    assert sorted(row["contributing_elements"]) == ["S1", "S2"]

    # Refresh again is read-only (no mutation) — still stale, qty still 10.
    p2 = await client.get(f"/api/v1/boq/boqs/{boq_id}", headers=auth)
    cur_qty2 = next(x["quantity"] for x in p2.json()["positions"] if x["id"] == pos_id)
    assert float(cur_qty2) == 10.0

    # Confirm/apply only the chosen link.
    apply = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/quantity-links/apply/",
        json={"link_ids": [link_id]},
        headers=auth,
    )
    assert apply.status_code == 200, apply.text
    abody = apply.json()
    assert abody["applied"] == 1
    assert abody["skipped"] == 0
    assert abody["results"][0]["applied"] is True

    # Position quantity now 60, total recomputed exactly (60 * 185 = 11100).
    p3 = await client.get(f"/api/v1/boq/boqs/{boq_id}", headers=auth)
    applied_pos = next(x for x in p3.json()["positions"] if x["id"] == pos_id)
    assert float(applied_pos["quantity"]) == 60.0
    assert float(applied_pos["total"]) == 60.0 * 185.0
    prov = applied_pos["metadata"]["model_quantity_pull"]
    assert prov["quantity_field"] == "area_m2"
    assert prov["new_quantity"] in ("60", "60.0", "60.0000")
    assert prov["model_version"] == "2"
    assert len(applied_pos["metadata"]["model_quantity_pull_history"]) == 1


@pytest.mark.asyncio
async def test_apply_is_gated_to_listed_links_only(client: AsyncClient, auth: dict[str, str]) -> None:
    """Only links named in the confirm payload are written."""
    project_id = await _create_project(client, auth)
    boq_id = await _create_boq(client, auth, project_id)
    pos_a = await _add_position(
        client,
        auth,
        boq_id,
        ordinal="A",
        description="A",
        unit="m2",
        quantity=1.0,
        unit_rate=10.0,
    )
    pos_b = await _add_position(
        client,
        auth,
        boq_id,
        ordinal="B",
        description="B",
        unit="m2",
        quantity=1.0,
        unit_rate=10.0,
    )
    model = await _create_model_with_elements(
        client,
        auth,
        project_id,
        version="1",
        elements=[
            {"stable_id": "EA", "quantities": {"area_m2": 7.0}},
            {"stable_id": "EB", "quantities": {"area_m2": 9.0}},
        ],
    )
    la = (
        await client.post(
            f"/api/v1/boq/positions/{pos_a['id']}/quantity-links/",
            json={"model_id": model, "element_stable_ids": ["EA"], "quantity_field": "area_m2"},
            headers=auth,
        )
    ).json()
    await client.post(
        f"/api/v1/boq/positions/{pos_b['id']}/quantity-links/",
        json={"model_id": model, "element_stable_ids": ["EB"], "quantity_field": "area_m2"},
        headers=auth,
    )

    # Apply only link A.
    apply = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/quantity-links/apply/",
        json={"link_ids": [la["id"]]},
        headers=auth,
    )
    assert apply.status_code == 200
    assert apply.json()["applied"] == 1

    p = await client.get(f"/api/v1/boq/boqs/{boq_id}", headers=auth)
    by_ord = {x["ordinal"]: x for x in p.json()["positions"]}
    assert float(by_ord["A"]["quantity"]) == 7.0  # applied
    assert float(by_ord["B"]["quantity"]) == 1.0  # untouched


@pytest.mark.asyncio
async def test_delete_quantity_link_keeps_position_quantity(client: AsyncClient, auth: dict[str, str]) -> None:
    """Deleting a link stops tracking but never reverts the quantity."""
    project_id = await _create_project(client, auth)
    boq_id = await _create_boq(client, auth, project_id)
    pos = await _add_position(
        client,
        auth,
        boq_id,
        ordinal="01",
        description="d",
        unit="m3",
        quantity=42.0,
        unit_rate=5.0,
    )
    model = await _create_model_with_elements(
        client,
        auth,
        project_id,
        version="1",
        elements=[{"stable_id": "X", "quantities": {"volume_m3": 99.0}}],
    )
    link = (
        await client.post(
            f"/api/v1/boq/positions/{pos['id']}/quantity-links/",
            json={"model_id": model, "element_stable_ids": ["X"], "quantity_field": "volume_m3"},
            headers=auth,
        )
    ).json()

    d = await client.delete(
        f"/api/v1/boq/positions/{pos['id']}/quantity-links/{link['id']}",
        headers=auth,
    )
    assert d.status_code == 204
    listed = await client.get(f"/api/v1/boq/positions/{pos['id']}/quantity-links/", headers=auth)
    assert listed.json() == []
    p = await client.get(f"/api/v1/boq/boqs/{boq_id}", headers=auth)
    q = next(x["quantity"] for x in p.json()["positions"] if x["id"] == pos["id"])
    assert float(q) == 42.0


@pytest.mark.asyncio
async def test_quantity_link_count_aggregation(client: AsyncClient, auth: dict[str, str]) -> None:
    """``count`` aggregation returns the number of resolved elements."""
    project_id = await _create_project(client, auth)
    boq_id = await _create_boq(client, auth, project_id)
    pos = await _add_position(
        client,
        auth,
        boq_id,
        ordinal="D",
        description="Doors",
        unit="pcs",
        quantity=0.0,
        unit_rate=350.0,
    )
    model = await _create_model_with_elements(
        client,
        auth,
        project_id,
        version="1",
        elements=[
            {"stable_id": "D1", "element_type": "door", "quantities": {}},
            {"stable_id": "D2", "element_type": "door", "quantities": {}},
            {"stable_id": "D3", "element_type": "door", "quantities": {}},
        ],
    )
    link = (
        await client.post(
            f"/api/v1/boq/positions/{pos['id']}/quantity-links/",
            json={
                "model_id": model,
                "element_stable_ids": ["D1", "D2", "D3"],
                "quantity_field": "count",
                "aggregation": "count",
            },
            headers=auth,
        )
    ).json()
    apply = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/quantity-links/apply/",
        json={"link_ids": [link["id"]]},
        headers=auth,
    )
    assert apply.status_code == 200
    p = await client.get(f"/api/v1/boq/boqs/{boq_id}", headers=auth)
    q = next(x["quantity"] for x in p.json()["positions"] if x["id"] == pos["id"])
    assert float(q) == 3.0


# ═══════════════════════════════════════════════════════════════════════════
# Feature 2 — line-level BOQ compare
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_compare_classifies_added_removed_qty_rate(client: AsyncClient, auth: dict[str, str]) -> None:
    """Compare a baseline to a revision and classify every line."""
    project_id = await _create_project(client, auth)
    base = await _create_boq(client, auth, project_id)

    # Baseline lines, paired by reference_code.
    await _add_position(
        client,
        auth,
        base,
        ordinal="01",
        reference_code="R-100",
        description="Concrete",
        unit="m3",
        quantity=10.0,
        unit_rate=185.0,
    )
    await _add_position(
        client,
        auth,
        base,
        ordinal="02",
        reference_code="R-200",
        description="Formwork",
        unit="m2",
        quantity=100.0,
        unit_rate=42.0,
    )
    await _add_position(
        client,
        auth,
        base,
        ordinal="03",
        reference_code="R-300",
        description="Rebar (removed in revision)",
        unit="kg",
        quantity=3000.0,
        unit_rate=1.85,
    )

    # Revision: clone via create-revision then mutate.
    rev_r = await client.post(f"/api/v1/boq/boqs/{base}/create-revision/", headers=auth)
    assert rev_r.status_code == 201, rev_r.text
    rev = rev_r.json()["id"]

    rev_boq = (await client.get(f"/api/v1/boq/boqs/{rev}", headers=auth)).json()
    by_rc = {p["reference_code"]: p for p in rev_boq["positions"]}

    # qty change on R-100
    await client.patch(
        f"/api/v1/boq/positions/{by_rc['R-100']['id']}",
        json={"quantity": 12.5},
        headers=auth,
    )
    # rate change on R-200
    await client.patch(
        f"/api/v1/boq/positions/{by_rc['R-200']['id']}",
        json={"unit_rate": 47.0},
        headers=auth,
    )
    # remove R-300 from revision
    await client.delete(f"/api/v1/boq/positions/{by_rc['R-300']['id']}", headers=auth)
    # add a brand-new line to the revision
    await _add_position(
        client,
        auth,
        rev,
        ordinal="04",
        reference_code="R-400",
        description="New scope",
        unit="m2",
        quantity=50.0,
        unit_rate=20.0,
    )

    cmp_r = await client.get(f"/api/v1/boq/boqs/{base}/compare/{rev}", headers=auth)
    assert cmp_r.status_code == 200, cmp_r.text
    body = cmp_r.json()
    by_key = {r["match_key"]: r for r in body["rows"]}

    assert by_key["rc:R-100"]["change_type"] == "qty_changed"
    assert float(by_key["rc:R-100"]["old_quantity"]) == 10.0
    assert float(by_key["rc:R-100"]["new_quantity"]) == 12.5

    assert by_key["rc:R-200"]["change_type"] == "rate_changed"
    assert float(by_key["rc:R-200"]["old_unit_rate"]) == 42.0
    assert float(by_key["rc:R-200"]["new_unit_rate"]) == 47.0

    assert by_key["rc:R-300"]["change_type"] == "removed"
    assert by_key["rc:R-400"]["change_type"] == "added"

    s = body["summary"]
    assert s["qty_changed"] == 1
    assert s["rate_changed"] == 1
    assert s["removed"] == 1
    assert s["added"] == 1
    assert s["base_currency"] == "EUR"


@pytest.mark.asyncio
async def test_compare_multicurrency_rebases_into_base(client: AsyncClient, auth: dict[str, str]) -> None:
    """Foreign-currency position totals rebase to base before the delta.

    Project base = EUR with a USD FX rate of 0.90 (0.90 EUR per 1 USD).
    A USD-priced line's total must contribute ``total * 0.90`` to the
    base-currency direct-cost delta — never the raw USD figure.
    """
    project_id = await _create_project(
        client,
        auth,
        currency="EUR",
        fx_rates=[{"code": "USD", "rate": "0.90"}],
    )
    base = await _create_boq(client, auth, project_id)

    # Base BOQ: one EUR line (1000) + one USD line (1000 USD).
    await _add_position(
        client,
        auth,
        base,
        ordinal="01",
        reference_code="R-EUR",
        description="EUR line",
        unit="m2",
        quantity=10.0,
        unit_rate=100.0,
        metadata={"currency": "EUR"},
    )
    await _add_position(
        client,
        auth,
        base,
        ordinal="02",
        reference_code="R-USD",
        description="USD line",
        unit="m2",
        quantity=10.0,
        unit_rate=100.0,
        metadata={"currency": "USD"},
    )

    rev = (await client.post(f"/api/v1/boq/boqs/{base}/create-revision/", headers=auth)).json()["id"]
    rev_boq = (await client.get(f"/api/v1/boq/boqs/{rev}", headers=auth)).json()
    by_rc = {p["reference_code"]: p for p in rev_boq["positions"]}

    # Bump the USD line qty 10 → 20 (total 1000 USD → 2000 USD).
    await client.patch(
        f"/api/v1/boq/positions/{by_rc['R-USD']['id']}",
        json={"quantity": 20.0},
        headers=auth,
    )

    cmp_r = await client.get(f"/api/v1/boq/boqs/{base}/compare/{rev}", headers=auth)
    assert cmp_r.status_code == 200, cmp_r.text
    body = cmp_r.json()
    s = body["summary"]
    assert s["base_currency"] == "EUR"

    # Base direct cost = 1000 EUR + 1000 USD*0.90 = 1900 EUR
    assert float(s["old_direct_cost_base"]) == pytest.approx(1900.0)
    # New direct cost = 1000 EUR + 2000 USD*0.90 = 2800 EUR
    assert float(s["new_direct_cost_base"]) == pytest.approx(2800.0)
    # Delta = +900 EUR (the 1000-USD bump rebased), NOT +1000.
    assert float(s["direct_cost_delta_base"]) == pytest.approx(900.0)

    usd_row = next(r for r in body["rows"] if r["match_key"] == "rc:R-USD")
    assert usd_row["change_type"] == "qty_changed"
    assert usd_row["currency"] == "USD"
    # Per-row base delta also rebased: (2000-1000) * 0.90 = 900
    assert float(usd_row["total_delta_base"]) == pytest.approx(900.0)


@pytest.mark.asyncio
async def test_compare_404_on_unknown_boq(client: AsyncClient, auth: dict[str, str]) -> None:
    """Comparing against a non-existent BOQ is a clean 404."""
    project_id = await _create_project(client, auth)
    base = await _create_boq(client, auth, project_id)
    missing = uuid.uuid4()
    r = await client.get(f"/api/v1/boq/boqs/{base}/compare/{missing}", headers=auth)
    assert r.status_code == 404
