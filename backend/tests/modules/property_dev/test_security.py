"""R7 security regressions for the property_dev module.

Covers:

- IDOR fan-out: tenant B cannot read or mutate tenant A's plot, house
  type, escrow account, or price matrix; all responses collapse to 404
  (never 403 — no existence oracle).
- Money serialization: plot ``area_m2`` / ``price_base`` arrive on the
  wire as plain-decimal strings (not JS-rounded floats).
- Magic-byte upload rejection: a fake .jpg with PNG bytes is accepted;
  a script payload is rejected with 415.
- Member-denied PATCH: a non-owner editor in another tenant gets 404
  on PATCH /buyers/{b_id}.
- FSM rejection: an invalid plot transition (planned → handed_over,
  skipping reserved / sold) is rejected with 409.

Scaffolding lives in ``conftest.py`` per
``feedback_test_isolation.md``.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient

from .conftest import _register_user

# ── Fixtures (module scope — shared across tests) ───────────────────────


@pytest_asyncio.fixture(scope="module")
async def tenant_a(client: AsyncClient):
    """Tenant A: admin owning project + development + plot + house type +
    escrow account + price matrix."""
    _uid, email, headers = await _register_user(client, role="admin", tag="ta")

    proj = await client.post(
        "/api/v1/projects/",
        json={
            "name": f"R7-TenantA-{uuid.uuid4().hex[:6]}",
            "description": "R7 tenant A",
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
            "code": f"R7A-{uuid.uuid4().hex[:6]}",
            "name": "Riverside R7",
            "total_plots": 3,
            "currency": "EUR",
        },
        headers=headers,
    )
    assert dev.status_code == 201, dev.text
    development_id = dev.json()["id"]

    plot = await client.post(
        "/api/v1/property-dev/plots/",
        json={
            "development_id": development_id,
            "plot_number": "A-1",
            "area_m2": "123.45",  # send as string — Pydantic coerces
            "price_base": "987654.32",
            "currency": "EUR",
            "status": "planned",
        },
        headers=headers,
    )
    assert plot.status_code == 201, plot.text
    plot_id = plot.json()["id"]

    house = await client.post(
        "/api/v1/property-dev/house-types/",
        json={
            "development_id": development_id,
            "code": "HT-A",
            "name": "Type A",
            "base_price": "250000.00",
            "currency": "EUR",
        },
        headers=headers,
    )
    assert house.status_code == 201, house.text
    house_type_id = house.json()["id"]

    escrow = await client.post(
        "/api/v1/property-dev/escrow-accounts/",
        json={
            "development_id": development_id,
            "regulator_ref": "other",
            "currency": "EUR",
            "opened_at": "2026-01-01",
        },
        headers=headers,
    )
    assert escrow.status_code == 201, escrow.text
    escrow_id = escrow.json()["id"]

    matrix = await client.post(
        "/api/v1/property-dev/price-matrices/",
        json={
            "development_id": development_id,
            "name": "Matrix-A",
            "base_price_per_m2": "8000",
            "currency": "EUR",
            "effective_from": "2026-01-01",
            "rules": [],
        },
        headers=headers,
    )
    assert matrix.status_code == 201, matrix.text
    matrix_id = matrix.json()["id"]

    buyer = await client.post(
        "/api/v1/property-dev/buyers/",
        json={
            "development_id": development_id,
            "full_name": "Alice R7",
            "email": "alice-r7@test.io",
            "status": "lead",
        },
        headers=headers,
    )
    assert buyer.status_code == 201, buyer.text

    return {
        "headers": headers,
        "email": email,
        "project_id": project_id,
        "development_id": development_id,
        "plot_id": plot_id,
        "house_type_id": house_type_id,
        "escrow_id": escrow_id,
        "matrix_id": matrix_id,
        "buyer_id": buyer.json()["id"],
    }


@pytest_asyncio.fixture(scope="module")
async def tenant_b(client: AsyncClient):
    """Tenant B: editor (non-admin) owning a SEPARATE project + dev.

    Editor — admins bypass per-tenant gates by design. A real cross-tenant
    attacker would be a non-admin in their own org space trying to
    enumerate A's UUIDs.
    """
    _uid, email, headers = await _register_user(client, role="editor", tag="tb")

    proj = await client.post(
        "/api/v1/projects/",
        json={
            "name": f"R7-TenantB-{uuid.uuid4().hex[:6]}",
            "description": "R7 tenant B",
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
            "code": f"R7B-{uuid.uuid4().hex[:6]}",
            "name": "Highland R7",
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


# ── IDOR fan-out (5 endpoints) ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_idor_get_plot_collapses_to_404(
    client: AsyncClient,
    tenant_a,
    tenant_b,
):
    """Tenant B trying to read tenant A's plot must get 404, not 403."""
    res = await client.get(
        f"/api/v1/property-dev/plots/{tenant_a['plot_id']}",
        headers=tenant_b["headers"],
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_idor_patch_house_type_collapses_to_404(
    client: AsyncClient,
    tenant_a,
    tenant_b,
):
    """Tenant B trying to mutate tenant A's house type must get 404."""
    res = await client.patch(
        f"/api/v1/property-dev/house-types/{tenant_a['house_type_id']}",
        json={"name": "PWNED"},
        headers=tenant_b["headers"],
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_idor_get_escrow_account_collapses_to_404(
    client: AsyncClient,
    tenant_a,
    tenant_b,
):
    """Tenant B trying to read tenant A's escrow account must get 404.

    GET (not DELETE) because the editor role grants property_dev.read but
    not property_dev.delete; we want to test the IDOR gate not the RBAC
    permission gate (which fires first and would mask the IDOR with 403).
    """
    res = await client.get(
        f"/api/v1/property-dev/escrow-accounts/{tenant_a['escrow_id']}",
        headers=tenant_b["headers"],
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_idor_list_plots_blocks_cross_tenant_development(
    client: AsyncClient,
    tenant_a,
    tenant_b,
):
    """Listing plots with another tenant's development_id query → 404."""
    res = await client.get(
        f"/api/v1/property-dev/plots/?development_id={tenant_a['development_id']}",
        headers=tenant_b["headers"],
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_idor_get_random_uuid_also_404(
    client: AsyncClient,
    tenant_b,
):
    """Confirm a non-existent UUID returns the SAME 404 as a cross-tenant
    one — proves the gate doesn't act as an existence oracle."""
    random_id = uuid.uuid4()
    res = await client.get(
        f"/api/v1/property-dev/plots/{random_id}",
        headers=tenant_b["headers"],
    )
    assert res.status_code == 404, res.text


# ── Member-denied PATCH (RBAC + IDOR combo) ─────────────────────────────


@pytest.mark.asyncio
async def test_member_denied_patch_buyer(
    client: AsyncClient,
    tenant_a,
    tenant_b,
):
    """A non-owner editor in another tenant must NOT mutate tenant A's
    buyer; collapses to 404 instead of 403."""
    res = await client.patch(
        f"/api/v1/property-dev/buyers/{tenant_a['buyer_id']}",
        json={"full_name": "Hijacked"},
        headers=tenant_b["headers"],
    )
    assert res.status_code == 404, res.text


# ── Money serialization (R7 string-form) ────────────────────────────────


@pytest.mark.asyncio
async def test_money_fields_serialized_as_strings(
    client: AsyncClient,
    tenant_a,
):
    """Plot money fields must arrive as JSON strings — never floats.

    Float serialization is a precision-loss bug (JS rounds to float64 past
    ~15 digits). The contract is: every Decimal money column is rendered
    as a plain-decimal string ("123.45", not 123.45 or "1.23E+2").
    """
    res = await client.get(
        f"/api/v1/property-dev/plots/{tenant_a['plot_id']}",
        headers=tenant_a["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert isinstance(body["area_m2"], str), (
        f"area_m2 should be str, got {type(body['area_m2']).__name__}: {body['area_m2']!r}"
    )
    assert isinstance(body["price_base"], str), (
        f"price_base should be str, got {type(body['price_base']).__name__}: {body['price_base']!r}"
    )
    # Round-trip-safe parsing back into Decimal must equal what we sent.
    assert Decimal(body["area_m2"]) == Decimal("123.45")
    assert Decimal(body["price_base"]) == Decimal("987654.32")
    # Plain-decimal format — no scientific notation.
    assert "E" not in body["price_base"]
    assert "e" not in body["price_base"]


# ── Magic-byte upload rejection ─────────────────────────────────────────


async def _make_snag(client: AsyncClient, tenant_a, tag: str) -> str:
    """Create a fresh plot → handover → snag chain and return the snag id.

    Handover has a UNIQUE constraint on ``plot_id`` so each test needs its
    own plot, otherwise the second handover insert collides.
    """
    headers = tenant_a["headers"]
    plot = await client.post(
        "/api/v1/property-dev/plots/",
        json={
            "development_id": tenant_a["development_id"],
            "plot_number": f"A-SNG-{tag}-{uuid.uuid4().hex[:6]}",
            "area_m2": "80",
            "price_base": "1",
            "currency": "EUR",
            "status": "planned",
        },
        headers=headers,
    )
    assert plot.status_code == 201, plot.text
    plot_id = plot.json()["id"]

    handover = await client.post(
        "/api/v1/property-dev/handovers/",
        json={
            "plot_id": plot_id,
            "scheduled_at": "2026-12-31",
            "notes": f"R7 fixture {tag}",
        },
        headers=headers,
    )
    assert handover.status_code == 201, handover.text

    snag = await client.post(
        "/api/v1/property-dev/snags/",
        json={
            "handover_id": handover.json()["id"],
            "category": "general",
            "severity": "minor",
            "description": f"R7 snag {tag}",
        },
        headers=headers,
    )
    assert snag.status_code == 201, snag.text
    return snag.json()["id"]


@pytest.mark.asyncio
async def test_snag_photo_upload_rejects_non_image(
    client: AsyncClient,
    tenant_a,
):
    """A .jpg upload containing shell-script bytes must be rejected 415.

    Tests the magic-byte gate on POST /snags/{id}/photos/.
    """
    headers = tenant_a["headers"]
    snag_id = await _make_snag(client, tenant_a, "magic-evil")

    # Attempt to upload a shell-script payload disguised as .jpg.
    payload = b"#!/bin/sh\necho pwned\n"
    files = {"file": ("evil.jpg", payload, "image/jpeg")}
    res = await client.post(
        f"/api/v1/property-dev/snags/{snag_id}/photos/",
        files=files,
        headers=headers,
    )
    assert res.status_code == 415, res.text


@pytest.mark.asyncio
async def test_snag_photo_upload_accepts_valid_jpeg(
    client: AsyncClient,
    tenant_a,
):
    """The same endpoint must accept a minimal valid JPEG (FF D8 FF magic).

    Sanity: confirms the 415 above isn't blocking all uploads.
    """
    headers = tenant_a["headers"]
    snag_id = await _make_snag(client, tenant_a, "magic-valid")

    # The magic-byte gate sniffs the first 3 bytes (FF D8 FF). Any payload
    # starting with the SOI marker passes the gate; the route stores bytes
    # without decoding so a tiny fake-prefix payload is fine for testing
    # the gate itself.
    valid_jpeg_prefix = b"\xff\xd8\xff\xe0" + b"\x00" * 200
    files = {"file": ("valid.jpg", valid_jpeg_prefix, "image/jpeg")}
    res = await client.post(
        f"/api/v1/property-dev/snags/{snag_id}/photos/",
        files=files,
        headers=headers,
    )
    assert res.status_code == 200, res.text


# ── Root-create IDOR (audit 2026-06-22 #9) ──────────────────────────────
#
# create_development / create_lead / create_buyer accept a foreign parent
# id (project_id / development_id / plot_id) in the request body. Before
# the fix the handlers wrote the row with no project-access check, so
# tenant B could attach a development (and its plots/buyers/contracts) to
# tenant A's project, or a lead/buyer to tenant A's development. The gates
# mirror create_plot's ``_verify_owner_via_development`` / the new
# ``_verify_owner_via_project`` and must collapse to 404.


@pytest.mark.asyncio
async def test_idor_create_development_foreign_project_404(
    client: AsyncClient,
    tenant_a,
    tenant_b,
):
    """Tenant B cannot create a development under tenant A's project."""
    res = await client.post(
        "/api/v1/property-dev/developments/",
        json={
            "project_id": tenant_a["project_id"],
            "code": f"IDOR-{uuid.uuid4().hex[:6]}",
            "name": "Cross-tenant injection",
            "total_plots": 1,
            "currency": "EUR",
        },
        headers=tenant_b["headers"],
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_create_development_own_project_still_works(
    client: AsyncClient,
    tenant_b,
):
    """Sanity: the gate does not block creating under your OWN project."""
    res = await client.post(
        "/api/v1/property-dev/developments/",
        json={
            "project_id": tenant_b["project_id"],
            "code": f"OWN-{uuid.uuid4().hex[:6]}",
            "name": "Legit development",
            "total_plots": 1,
            "currency": "EUR",
        },
        headers=tenant_b["headers"],
    )
    assert res.status_code == 201, res.text


@pytest.mark.asyncio
async def test_idor_create_lead_foreign_development_404(
    client: AsyncClient,
    tenant_a,
    tenant_b,
):
    """Tenant B cannot attach a lead to tenant A's development."""
    res = await client.post(
        "/api/v1/property-dev/leads/",
        json={
            "development_id": tenant_a["development_id"],
            "full_name": "Mallory Lead",
            "email": f"mallory-{uuid.uuid4().hex[:6]}@evil.io",
        },
        headers=tenant_b["headers"],
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_idor_create_buyer_foreign_development_404(
    client: AsyncClient,
    tenant_a,
    tenant_b,
):
    """Tenant B cannot attach a buyer to tenant A's development."""
    res = await client.post(
        "/api/v1/property-dev/buyers/",
        json={
            "development_id": tenant_a["development_id"],
            "full_name": "Mallory Buyer",
            "email": f"mallory-buyer-{uuid.uuid4().hex[:6]}@evil.io",
            "status": "lead",
        },
        headers=tenant_b["headers"],
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_idor_create_buyer_foreign_plot_404(
    client: AsyncClient,
    tenant_a,
    tenant_b,
):
    """Tenant B cannot pin a buyer to tenant A's plot via plot_id, even if
    development_id points at their own development."""
    res = await client.post(
        "/api/v1/property-dev/buyers/",
        json={
            "development_id": tenant_b["development_id"],
            "plot_id": tenant_a["plot_id"],
            "full_name": "Mallory PlotBuyer",
            "email": f"mallory-plot-{uuid.uuid4().hex[:6]}@evil.io",
            "status": "lead",
        },
        headers=tenant_b["headers"],
    )
    assert res.status_code == 404, res.text


# ── FSM rejection ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fsm_rejects_invalid_plot_transition(
    client: AsyncClient,
    tenant_a,
):
    """planned → handed_over skips reserved/sold and must 409.

    Per service._PLOT_TRANSITIONS, planned ⊕ {reserved, under_construction,
    ready}. handed_over is only reachable from sold. Direct planned →
    handed_over must be rejected.
    """
    headers = tenant_a["headers"]
    res = await client.patch(
        f"/api/v1/property-dev/plots/{tenant_a['plot_id']}",
        json={"status": "handed_over"},
        headers=headers,
    )
    assert res.status_code == 409, res.text
    body = res.json()
    detail = (body.get("detail") or "").lower()
    assert "invalid" in detail, body
    assert "transition" in detail, body


@pytest.mark.asyncio
async def test_fsm_accepts_valid_plot_transition(
    client: AsyncClient,
    tenant_a,
):
    """planned → reserved is in the allowlist and must succeed.

    Note: this MUTATES the shared fixture's plot status. Tests downstream
    that depend on plot.status == "planned" would need a fresh plot.
    Tests here run alphabetically; this is the last FSM test.
    """
    headers = tenant_a["headers"]
    # Use a freshly-minted plot so we don't perturb tenant_a['plot_id'].
    plot = await client.post(
        "/api/v1/property-dev/plots/",
        json={
            "development_id": tenant_a["development_id"],
            "plot_number": f"A-FSM-{uuid.uuid4().hex[:6]}",
            "area_m2": "100",
            "price_base": "1",
            "currency": "EUR",
            "status": "planned",
        },
        headers=headers,
    )
    assert plot.status_code == 201, plot.text
    plot_id = plot.json()["id"]
    res = await client.patch(
        f"/api/v1/property-dev/plots/{plot_id}",
        json={"status": "reserved"},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "reserved"
