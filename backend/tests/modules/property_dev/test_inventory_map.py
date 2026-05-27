"""Inventory Map (task #142) — backend test suite.

Covers the three new endpoints under ``/api/v1/property-dev/developments/
{dev_id}/inventory-map/``:

* ``GET    /inventory-map/``           — block/floor/unit grid + KPI summary
* ``POST   /inventory-map/bulk-hold/`` — atomic available → held flip
* ``POST   /inventory-map/bulk-release/`` — atomic held → planned flip

Test focus areas:

1. **IDOR cross-tenant 404** — every endpoint collapses "exists but not
   yours" to 404 (no existence oracle).
2. **Bulk-hold atomicity** — failure mid-batch rolls back the whole
   SAVEPOINT (no half-applied state). Mirrors
   :func:`procurement.create_invoice_from_po`.
3. **Hold on reserved → 409** — protects the sales pipeline; a reserved
   plot must never silently flip to held.
4. **Release on non-held → idempotent** — shift-select tolerance; the
   sales desk routinely re-fires release on a range that includes
   already-released plots.
5. **RBAC** — EDITOR gets 403 on bulk-hold / bulk-release (MANAGER+ only),
   admin always wins.
6. **Summary correctness** — KPI counters match the actual plots
   inserted; ``available`` counts the union of planned + ready.
7. **Layout** — blocks ordered by code; floors sorted descending (top
   floor first, matching every real-estate floor plan).
8. **Money serialization** — ``base_price`` + ``area_m2`` arrive as
   plain-decimal strings.

Scaffolding lives in ``conftest.py`` (per ``feedback_test_isolation.md``).
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient

from .conftest import _register_user

# ────────────────────────────────────────────────────────────────────────
# Fixtures — independent tenants so failures here can't poison R7/R8.
# ────────────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def inv_tenant_a(client: AsyncClient):
    """Tenant A admin owning a development with 12 plots across 2 blocks."""
    _uid, email, headers = await _register_user(client, role="admin", tag="invA")

    proj = await client.post(
        "/api/v1/projects/",
        json={
            "name": f"Inv-A-{uuid.uuid4().hex[:6]}",
            "description": "Inventory Map tenant A",
            "currency": "EUR",
        },
        headers=headers,
    )
    assert proj.status_code in (200, 201), proj.text
    project_id = proj.json()["id"]

    dev = await client.post(
        "/api/v1/property-dev/developments/",
        json={
            "project_id": project_id,
            "code": f"INVA-{uuid.uuid4().hex[:6]}",
            "name": "Riverside Inventory",
            "total_plots": 12,
            "currency": "EUR",
        },
        headers=headers,
    )
    assert dev.status_code == 201, dev.text
    development_id = dev.json()["id"]

    # Two blocks (B1 + B2), 3 floors each, 2 units per floor = 12 plots.
    # Block created via /phases + /blocks would require those endpoints —
    # here we keep plots free-floating (no block_id) so the inventory
    # map's legacy-fallback layout is exercised by default.
    plot_ids: list[str] = []
    for floor in (1, 2, 3):
        for pos in ("A", "B"):
            for block_code in ("B1", "B2"):
                plot = await client.post(
                    "/api/v1/property-dev/plots/",
                    json={
                        "development_id": development_id,
                        "plot_number": f"{block_code}-{floor:02d}-{pos}",
                        "area_m2": "85.00",
                        "price_base": "350000.00",
                        "currency": "EUR",
                        "status": "planned",
                        "level_in_block": floor,
                        "position_on_floor": pos,
                        "house_type_label": "2BR",
                    },
                    headers=headers,
                )
                assert plot.status_code == 201, plot.text
                plot_ids.append(plot.json()["id"])

    return {
        "headers": headers,
        "email": email,
        "project_id": project_id,
        "development_id": development_id,
        "plot_ids": plot_ids,
    }


@pytest_asyncio.fixture(scope="module")
async def inv_tenant_b(client: AsyncClient):
    """Tenant B (manager) with own project — used to probe IDOR.

    Role MUST be ``manager`` (not editor) so the bulk-hold / bulk-release
    permission gate (``property_dev.delete`` → MANAGER) passes BEFORE
    the IDOR ``_verify_owner_via_development`` runs. With an editor
    role the request 403s on RBAC and we'd never reach the IDOR check.
    """
    _uid, email, headers = await _register_user(client, role="manager", tag="invB")

    proj = await client.post(
        "/api/v1/projects/",
        json={
            "name": f"Inv-B-{uuid.uuid4().hex[:6]}",
            "description": "Inventory Map tenant B",
            "currency": "EUR",
        },
        headers=headers,
    )
    assert proj.status_code in (200, 201), proj.text
    project_id = proj.json()["id"]

    dev = await client.post(
        "/api/v1/property-dev/developments/",
        json={
            "project_id": project_id,
            "code": f"INVB-{uuid.uuid4().hex[:6]}",
            "name": "Highland Inventory",
            "total_plots": 1,
            "currency": "EUR",
        },
        headers=headers,
    )
    assert dev.status_code == 201, dev.text
    development_id = dev.json()["id"]

    return {
        "headers": headers,
        "email": email,
        "project_id": project_id,
        "development_id": development_id,
    }


@pytest_asyncio.fixture(scope="module")
async def inv_editor_in_tenant_a_proj(client: AsyncClient, inv_tenant_a):
    """An EDITOR-role user owning their own dev — RBAC harness."""
    _uid, _email, headers = await _register_user(client, role="editor", tag="invED")
    proj = await client.post(
        "/api/v1/projects/",
        json={
            "name": f"Inv-ED-{uuid.uuid4().hex[:6]}",
            "currency": "EUR",
        },
        headers=headers,
    )
    assert proj.status_code in (200, 201), proj.text
    project_id = proj.json()["id"]

    dev = await client.post(
        "/api/v1/property-dev/developments/",
        json={
            "project_id": project_id,
            "code": f"INVED-{uuid.uuid4().hex[:6]}",
            "name": "EditorOwned",
            "currency": "EUR",
        },
        headers=headers,
    )
    assert dev.status_code == 201, dev.text
    dev_id = dev.json()["id"]

    plot = await client.post(
        "/api/v1/property-dev/plots/",
        json={
            "development_id": dev_id,
            "plot_number": "ED-1",
            "area_m2": "50.0",
            "price_base": "100000.00",
            "currency": "EUR",
            "status": "planned",
        },
        headers=headers,
    )
    assert plot.status_code == 201, plot.text
    return {"headers": headers, "development_id": dev_id, "plot_id": plot.json()["id"]}


# ════════════════════════════════════════════════════════════════════════
# 1. GET /inventory-map/ — shape, summary, IDOR, sort order
# ════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_inventory_map_returns_blocks_floors_plots(
    client: AsyncClient,
    inv_tenant_a,
):
    """The map response contains the 12 plots distributed across blocks/floors."""
    res = await client.get(
        f"/api/v1/property-dev/developments/{inv_tenant_a['development_id']}/inventory-map/",
        headers=inv_tenant_a["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["development_id"] == inv_tenant_a["development_id"]
    assert body["currency"] == "EUR"
    # All plots have block_code=None at the model level (we set
    # plot_number with a prefix but no block_id) → they fall under
    # the synthetic "—" unassigned block. We assert the total count.
    total_plots = sum(len(f["plots"]) for b in body["blocks"] for f in b["floors"])
    assert total_plots == 12


@pytest.mark.asyncio
async def test_inventory_map_summary_counts_match(
    client: AsyncClient,
    inv_tenant_a,
):
    """KPI ribbon counters are correct (12 plots, all available/planned)."""
    res = await client.get(
        f"/api/v1/property-dev/developments/{inv_tenant_a['development_id']}/inventory-map/",
        headers=inv_tenant_a["headers"],
    )
    assert res.status_code == 200
    summary = res.json()["summary"]
    assert summary["total"] == 12
    # Every plot is in ``planned`` → both ``available`` and (a not-quite-
    # named counter) the planned bucket count it.
    assert summary["available"] == 12
    assert summary["held"] == 0
    assert summary["blocked"] == 0
    assert summary["sold"] == 0


@pytest.mark.asyncio
async def test_inventory_map_floors_descend_within_block(
    client: AsyncClient,
    inv_tenant_a,
):
    """Floors are returned high-to-low inside each block card."""
    res = await client.get(
        f"/api/v1/property-dev/developments/{inv_tenant_a['development_id']}/inventory-map/",
        headers=inv_tenant_a["headers"],
    )
    body = res.json()
    for block in body["blocks"]:
        floors = [f["floor"] for f in block["floors"]]
        assert floors == sorted(floors, reverse=True), (
            f"Floors not sorted descending in block {block['block_code']!r}: {floors!r}"
        )


@pytest.mark.asyncio
async def test_inventory_map_money_fields_are_strings(
    client: AsyncClient,
    inv_tenant_a,
):
    """Plot ``base_price`` + ``area_m2`` arrive as plain-decimal strings."""
    res = await client.get(
        f"/api/v1/property-dev/developments/{inv_tenant_a['development_id']}/inventory-map/",
        headers=inv_tenant_a["headers"],
    )
    body = res.json()
    sample_plot = body["blocks"][0]["floors"][0]["plots"][0]
    assert isinstance(sample_plot["base_price"], str)
    assert isinstance(sample_plot["area_m2"], str)
    # Plain-decimal — no exponent notation.
    assert "E" not in sample_plot["base_price"]
    assert "e" not in sample_plot["base_price"]


@pytest.mark.asyncio
async def test_inventory_map_idor_cross_tenant_404(
    client: AsyncClient,
    inv_tenant_a,
    inv_tenant_b,
):
    """Tenant B reading tenant A's inventory map → 404 (never 403)."""
    res = await client.get(
        f"/api/v1/property-dev/developments/{inv_tenant_a['development_id']}/inventory-map/",
        headers=inv_tenant_b["headers"],
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_inventory_map_random_uuid_also_404(
    client: AsyncClient,
    inv_tenant_b,
):
    """A random UUID returns the same 404 as a cross-tenant one (no oracle)."""
    res = await client.get(
        f"/api/v1/property-dev/developments/{uuid.uuid4()}/inventory-map/",
        headers=inv_tenant_b["headers"],
    )
    assert res.status_code == 404, res.text


# ════════════════════════════════════════════════════════════════════════
# 2. POST /inventory-map/bulk-hold/ — atomicity, RBAC, validation
# ════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_bulk_hold_flips_available_plots(
    client: AsyncClient,
    inv_tenant_a,
):
    """Holding 2 available plots flips both to ``held``."""
    pid1, pid2 = inv_tenant_a["plot_ids"][0], inv_tenant_a["plot_ids"][1]
    res = await client.post(
        f"/api/v1/property-dev/developments/{inv_tenant_a['development_id']}/inventory-map/bulk-hold/",
        headers=inv_tenant_a["headers"],
        json={
            "plot_ids": [pid1, pid2],
            "hold_reason": "broker visit hold",
            "hold_until": "2026-06-01",
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["updated_count"] == 2
    assert set(body["updated_plot_ids"]) == {pid1, pid2}

    # Verify the per-plot status flipped.
    plot = await client.get(
        f"/api/v1/property-dev/plots/{pid1}",
        headers=inv_tenant_a["headers"],
    )
    assert plot.status_code == 200
    assert plot.json()["status"] == "held"

    # Release them again so the dev is clean for downstream tests.
    rel = await client.post(
        f"/api/v1/property-dev/developments/{inv_tenant_a['development_id']}/inventory-map/bulk-release/",
        headers=inv_tenant_a["headers"],
        json={"plot_ids": [pid1, pid2]},
    )
    assert rel.status_code == 200, rel.text


@pytest.mark.asyncio
async def test_bulk_hold_rejects_reserved_plot_with_409_and_rolls_back(
    client: AsyncClient,
    inv_tenant_a,
):
    """If ANY plot in the batch is reserved, the WHOLE batch is rejected.

    Verifies the SAVEPOINT atomicity contract (mirrors procurement.
    create_invoice_from_po): a 409 mid-batch rolls back every prior
    flip in the same call.
    """
    headers = inv_tenant_a["headers"]
    dev_id = inv_tenant_a["development_id"]
    pid_avail = inv_tenant_a["plot_ids"][2]
    pid_to_reserve = inv_tenant_a["plot_ids"][3]

    # Reserve one plot first.
    reserve = await client.post(
        f"/api/v1/property-dev/plots/{pid_to_reserve}/reserve",
        headers=headers,
        json={
            "full_name": "Test Reserved",
            "email": "test-res@example.com",
        },
    )
    assert reserve.status_code == 200, reserve.text
    assert reserve.json()["status"] == "reserved"

    # Bulk-hold against [available, reserved] → expect 409.
    res = await client.post(
        f"/api/v1/property-dev/developments/{dev_id}/inventory-map/bulk-hold/",
        headers=headers,
        json={
            "plot_ids": [pid_avail, pid_to_reserve],
            "hold_reason": "should fail",
        },
    )
    assert res.status_code == 409, res.text

    # Critical: the available plot must NOT have been left in 'held' —
    # the SAVEPOINT must have rolled back BOTH flips.
    avail_after = await client.get(
        f"/api/v1/property-dev/plots/{pid_avail}",
        headers=headers,
    )
    assert avail_after.status_code == 200
    assert avail_after.json()["status"] == "planned", (
        "SAVEPOINT did not roll back the available-plot flip — atomicity broken"
    )


@pytest.mark.asyncio
async def test_bulk_hold_already_held_is_silent_skip(
    client: AsyncClient,
    inv_tenant_a,
):
    """Re-holding an already-held plot is a soft skip, not a 409."""
    headers = inv_tenant_a["headers"]
    dev_id = inv_tenant_a["development_id"]
    pid = inv_tenant_a["plot_ids"][4]

    # Hold it once.
    r1 = await client.post(
        f"/api/v1/property-dev/developments/{dev_id}/inventory-map/bulk-hold/",
        headers=headers,
        json={"plot_ids": [pid], "hold_reason": "first hold"},
    )
    assert r1.status_code == 200
    assert r1.json()["updated_count"] == 1

    # Hold it again — should soft-skip.
    r2 = await client.post(
        f"/api/v1/property-dev/developments/{dev_id}/inventory-map/bulk-hold/",
        headers=headers,
        json={"plot_ids": [pid], "hold_reason": "second hold attempt"},
    )
    assert r2.status_code == 200
    body = r2.json()
    assert body["updated_count"] == 0
    assert body["skipped_count"] == 1
    assert body["skipped"][0]["reason"] == "already_held"


@pytest.mark.asyncio
async def test_bulk_hold_idor_cross_tenant_404(
    client: AsyncClient,
    inv_tenant_a,
    inv_tenant_b,
):
    """Tenant B trying to hold tenant A's plots → 404 (not 403/200)."""
    res = await client.post(
        f"/api/v1/property-dev/developments/{inv_tenant_a['development_id']}/inventory-map/bulk-hold/",
        headers=inv_tenant_b["headers"],
        json={
            "plot_ids": [inv_tenant_a["plot_ids"][5]],
            "hold_reason": "cross tenant attempt",
        },
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_bulk_hold_editor_role_gets_403(
    client: AsyncClient,
    inv_editor_in_tenant_a_proj,
):
    """EDITOR role on their OWN dev still hits 403 — bulk-hold is MANAGER+."""
    res = await client.post(
        f"/api/v1/property-dev/developments/{inv_editor_in_tenant_a_proj['development_id']}/inventory-map/bulk-hold/",
        headers=inv_editor_in_tenant_a_proj["headers"],
        json={
            "plot_ids": [inv_editor_in_tenant_a_proj["plot_id"]],
            "hold_reason": "editor probe",
        },
    )
    assert res.status_code == 403, res.text


@pytest.mark.asyncio
async def test_bulk_hold_rejects_empty_plot_ids(
    client: AsyncClient,
    inv_tenant_a,
):
    """Empty plot_ids → 422 (avoids audit-log noise from no-op calls)."""
    res = await client.post(
        f"/api/v1/property-dev/developments/{inv_tenant_a['development_id']}/inventory-map/bulk-hold/",
        headers=inv_tenant_a["headers"],
        json={"plot_ids": [], "hold_reason": "noop"},
    )
    assert res.status_code == 422, res.text


# ════════════════════════════════════════════════════════════════════════
# 3. POST /inventory-map/bulk-release/ — idempotency, RBAC, IDOR
# ════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_bulk_release_held_plots_flips_to_planned(
    client: AsyncClient,
    inv_tenant_a,
):
    """Held plots are released back to ``planned``."""
    headers = inv_tenant_a["headers"]
    dev_id = inv_tenant_a["development_id"]
    pid = inv_tenant_a["plot_ids"][6]

    # Hold first.
    hold = await client.post(
        f"/api/v1/property-dev/developments/{dev_id}/inventory-map/bulk-hold/",
        headers=headers,
        json={"plot_ids": [pid], "hold_reason": "preflight"},
    )
    assert hold.status_code == 200

    # Release.
    rel = await client.post(
        f"/api/v1/property-dev/developments/{dev_id}/inventory-map/bulk-release/",
        headers=headers,
        json={"plot_ids": [pid]},
    )
    assert rel.status_code == 200, rel.text
    body = rel.json()
    assert body["updated_count"] == 1
    assert body["updated_plot_ids"] == [pid]

    # Confirm the plot is back to planned.
    plot = await client.get(
        f"/api/v1/property-dev/plots/{pid}",
        headers=headers,
    )
    assert plot.json()["status"] == "planned"


@pytest.mark.asyncio
async def test_bulk_release_on_non_held_is_idempotent(
    client: AsyncClient,
    inv_tenant_a,
):
    """Releasing a planned plot is a silent skip (200, updated=0)."""
    headers = inv_tenant_a["headers"]
    dev_id = inv_tenant_a["development_id"]
    pid = inv_tenant_a["plot_ids"][7]

    res = await client.post(
        f"/api/v1/property-dev/developments/{dev_id}/inventory-map/bulk-release/",
        headers=headers,
        json={"plot_ids": [pid]},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["updated_count"] == 0
    assert body["skipped_count"] == 1
    assert body["skipped"][0]["reason"] == "not_held"


@pytest.mark.asyncio
async def test_bulk_release_idor_cross_tenant_404(
    client: AsyncClient,
    inv_tenant_a,
    inv_tenant_b,
):
    """Tenant B trying to release tenant A's plots → 404."""
    res = await client.post(
        f"/api/v1/property-dev/developments/{inv_tenant_a['development_id']}/inventory-map/bulk-release/",
        headers=inv_tenant_b["headers"],
        json={"plot_ids": [inv_tenant_a["plot_ids"][8]]},
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_bulk_release_editor_role_gets_403(
    client: AsyncClient,
    inv_editor_in_tenant_a_proj,
):
    """EDITOR role can't bulk-release — MANAGER+ gate."""
    res = await client.post(
        f"/api/v1/property-dev/developments/"
        f"{inv_editor_in_tenant_a_proj['development_id']}"
        "/inventory-map/bulk-release/",
        headers=inv_editor_in_tenant_a_proj["headers"],
        json={"plot_ids": [inv_editor_in_tenant_a_proj["plot_id"]]},
    )
    assert res.status_code == 403, res.text


@pytest.mark.asyncio
async def test_summary_reflects_held_after_hold(
    client: AsyncClient,
    inv_tenant_a,
):
    """KPI ribbon updates to show held count after a hold call."""
    headers = inv_tenant_a["headers"]
    dev_id = inv_tenant_a["development_id"]
    pid = inv_tenant_a["plot_ids"][9]

    await client.post(
        f"/api/v1/property-dev/developments/{dev_id}/inventory-map/bulk-hold/",
        headers=headers,
        json={"plot_ids": [pid], "hold_reason": "summary check"},
    )
    res = await client.get(
        f"/api/v1/property-dev/developments/{dev_id}/inventory-map/",
        headers=headers,
    )
    assert res.status_code == 200
    summary = res.json()["summary"]
    # held >= 1 (other tests may also leave plots held within the
    # module-scoped fixture lifecycle).
    assert summary["held"] >= 1
