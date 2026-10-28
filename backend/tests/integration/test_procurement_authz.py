# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠DB-backed integration tests for the procurement API.

Stands up the real FastAPI app over the ASGI transport (no network) and
drives the procurement router end-to-end against the test PostgreSQL the
shared conftest provisions. Three concerns:

1. **IDOR / cross-tenant 404** - every entity-scoped endpoint must resolve
   the parent project's access guard and answer 404 (never 403, never a
   leak) when an outsider who *holds* the procurement permission but does
   *not* own the project pokes at it. The procurement module grants
   ``procurement.read`` / ``procurement.create`` / ``procurement.confirm_receipt``
   down to VIEWER/EDITOR, so the outsider clears ``RequirePermission`` and
   is stopped purely by ``verify_project_access`` - exactly the gate we want
   to exercise.

2. **Happy path** - the full PO lifecycle the UI drives: create draft ->
   approve -> issue -> record goods receipt -> confirm -> PO rolls up to
   completed. Money stays Decimal-as-string on the wire throughout.

3. **Edge paths** - the FSM and over-receipt guards surface as the right
   HTTP status (create-as-non-draft 400, issue-before-approve 409, GR
   against a draft PO 400, cumulative over-receipt 400, retainage release
   over the held balance 400, missing PO 404).

Owner A is promoted to admin so they clear the MANAGER-gated approve / issue
steps and can create projects (``projects.create`` is EDITOR-gated). Outsider
B keeps the default ``viewer`` role.

This file is named ``*_authz`` deliberately: the PR-gating
"tenant-isolation + IDOR" CI job collects integration/module tests with
``-k "idor or isolation or tenant or authz"``, so the ``authz`` keyword in
this filename means the whole suite (IDOR + the happy / edge paths in the
same file) runs on every pull request, not only in the nightly full sweep.

Run:
    cd backend
    python -m pytest tests/integration/test_procurement_authz.py -v
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Eager-import the model namespaces this suite touches so Base.metadata sees a
# coherent table set when create_all runs (mirrors the boq IDOR baseline).
import app.modules.contacts.models  # noqa: F401
import app.modules.procurement.models  # noqa: F401
import app.modules.projects.models  # noqa: F401
import app.modules.users.models  # noqa: F401

# Statuses that count as "denied" for an outsider. 404 is what
# verify_project_access raises for an authenticated non-owner; 403 is accepted
# defensively in case a guard prefers it (the assertion's point is "not 2xx").
DENIED = (403, 404)


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    fastapi_app = create_app()

    async with fastapi_app.router.lifespan_context(fastapi_app):
        from app.database import Base, engine

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield fastapi_app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _register_login(
    client: AsyncClient,
    *,
    tenant: str,
    role: str | None = None,
) -> dict:
    """Register, activate, optionally promote, log in. Returns auth context."""
    email = f"{tenant}-{uuid.uuid4().hex[:8]}@proc-authz.io"
    password = f"ProcAuthz{uuid.uuid4().hex[:6]}9"

    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": f"Tenant {tenant}"},
    )
    assert reg.status_code in (200, 201), f"register failed for {tenant}: {reg.status_code} {reg.text}"
    user_id = reg.json()["id"]

    # Activate (+ optional promote) via a direct DB write - the HTTP register
    # surface intentionally demotes new users to viewer / may mark inactive.
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    values: dict = {"is_active": True}
    if role is not None:
        values["role"] = role
    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(**values))
        await s.commit()

    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, f"login failed for {tenant}: {login.text}"
    token = login.json()["access_token"]
    return {"user_id": user_id, "email": email, "headers": {"Authorization": f"Bearer {token}"}}


@pytest_asyncio.fixture(scope="module")
async def owner_a(http_client):
    """Owner A - admin so they can create projects and clear MANAGER gates."""
    return await _register_login(http_client, tenant="owner-a", role="admin")


@pytest_asyncio.fixture(scope="module")
async def outsider_b(http_client):
    """Outsider B - a default viewer with no relationship to A's project.

    A viewer holds procurement.read (granted to VIEWER), so B passes the
    RequirePermission gate and is rejected purely by the cross-tenant access
    gate on the read endpoints.
    """
    return await _register_login(http_client, tenant="outsider-b", role=None)


async def _create_project(client: AsyncClient, headers: dict[str, str]) -> str:
    resp = await client.post(
        "/api/v1/projects/",
        json={
            "name": f"ProcProj {uuid.uuid4().hex[:6]}",
            "description": "Procurement API regression",
            "region": "DACH",
            "classification_standard": "din276",
            "currency": "EUR",
        },
        headers=headers,
    )
    assert resp.status_code == 201, f"create project failed: {resp.text}"
    return resp.json()["id"]


async def _create_po(
    client: AsyncClient,
    headers: dict[str, str],
    project_id: str,
    *,
    quantity: str = "100",
    unit_rate: str = "120",
) -> dict:
    """Create a draft PO with a single line item; return the PO JSON.

    The vendor is set because approval runs the blocking ``procurement`` rule
    set, which refuses a commitment that names no party. It is an ad-hoc
    contact id rather than a registered subcontractor, so the vendor
    prequalification gate stays out of the way of these authorization tests.
    """
    resp = await client.post(
        "/api/v1/procurement/",
        json={
            "project_id": project_id,
            "po_type": "standard",
            "currency_code": "EUR",
            "vendor_contact_id": str(uuid.uuid4()),
            "status": "draft",
            "items": [
                {
                    "description": "Concrete C30/37",
                    "quantity": quantity,
                    "unit": "m3",
                    "unit_rate": unit_rate,
                    "amount": "0",
                },
            ],
        },
        headers=headers,
    )
    assert resp.status_code == 201, f"create PO failed: {resp.text}"
    return resp.json()


@pytest_asyncio.fixture(scope="module")
async def a_po(http_client, owner_a):
    """A project + one draft PO owned by A (read-only across the IDOR cases)."""
    project_id = await _create_project(http_client, owner_a["headers"])
    po = await _create_po(http_client, owner_a["headers"], project_id)
    return {"project_id": project_id, "po": po, "po_id": po["id"]}


# ── 1. IDOR / cross-tenant 404 ─────────────────────────────────────────────


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_outsider_cannot_read_po(http_client, a_po, outsider_b):
    """GET /{po_id} - outsider holding procurement.read must be 404'd."""
    resp = await http_client.get(
        f"/api/v1/procurement/{a_po['po_id']}",
        headers=outsider_b["headers"],
    )
    assert resp.status_code in DENIED, f"LEAK: outsider B read A's PO (status {resp.status_code}). Body: {resp.text!r}"


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_owner_can_read_po(http_client, a_po, owner_a):
    """Sanity: the legitimate owner gets their PO back (2xx)."""
    resp = await http_client.get(
        f"/api/v1/procurement/{a_po['po_id']}",
        headers=owner_a["headers"],
    )
    assert resp.status_code == 200, f"REGRESSION: owner A blocked on own PO: {resp.text}"
    assert resp.json()["id"] == a_po["po_id"]


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_outsider_cannot_list_pos_in_foreign_project(http_client, a_po, outsider_b):
    """GET /?project_id=A - outsider must not enumerate A's project POs."""
    resp = await http_client.get(
        f"/api/v1/procurement/?project_id={a_po['project_id']}",
        headers=outsider_b["headers"],
    )
    assert resp.status_code in DENIED, (
        f"LEAK: outsider B listed A's project POs (status {resp.status_code}). Body: {resp.text!r}"
    )


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_outsider_cannot_create_po_in_foreign_project(http_client, a_po, outsider_b):
    """POST / against A's project_id is an IDOR write - must be denied even
    though the outsider could hold procurement.create at a higher role."""
    resp = await http_client.post(
        "/api/v1/procurement/",
        json={
            "project_id": a_po["project_id"],
            "po_type": "standard",
            "currency_code": "EUR",
            "status": "draft",
        },
        headers=outsider_b["headers"],
    )
    # A viewer may be stopped at RequirePermission (403) OR the access gate
    # (404); both are non-leaking. The point: no PO is created.
    assert resp.status_code in DENIED, (
        f"LEAK: outsider B created a PO in A's project (status {resp.status_code}). Body: {resp.text!r}"
    )


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_outsider_cannot_read_match_status(http_client, a_po, outsider_b):
    resp = await http_client.get(
        f"/api/v1/procurement/{a_po['po_id']}/match-status/",
        headers=outsider_b["headers"],
    )
    assert resp.status_code in DENIED, (
        f"LEAK: outsider B read A's PO match status (status {resp.status_code}). Body: {resp.text!r}"
    )


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_outsider_cannot_list_retainage_releases(http_client, a_po, outsider_b):
    resp = await http_client.get(
        f"/api/v1/procurement/{a_po['po_id']}/retainage-releases/",
        headers=outsider_b["headers"],
    )
    assert resp.status_code in DENIED, (
        f"LEAK: outsider B read A's retainage log (status {resp.status_code}). Body: {resp.text!r}"
    )


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_get_missing_po_is_404(http_client, owner_a):
    """A non-existent PO id is 404, not 500 - even for an admin."""
    resp = await http_client.get(
        f"/api/v1/procurement/{uuid.uuid4()}",
        headers=owner_a["headers"],
    )
    assert resp.status_code == 404, f"expected 404 for missing PO, got {resp.status_code}: {resp.text}"


# ── 2. Happy path: full PO -> GR lifecycle ─────────────────────────────────


@pytest.mark.asyncio
async def test_full_po_lifecycle_to_completed(http_client, owner_a):
    """create draft -> approve -> issue -> record GR -> confirm -> completed.

    Also pins the Decimal-as-string money contract end-to-end: a 100 x 120.50
    line totals to exactly "12050.00" on the wire (no float drift), and the
    GR confirm rolls the PO up to ``completed`` once the full quantity lands.
    """
    project_id = await _create_project(http_client, owner_a["headers"])
    po = await _create_po(
        http_client,
        owner_a["headers"],
        project_id,
        quantity="100",
        unit_rate="120.50",
    )
    po_id = po["id"]

    # Money is a string, and the subtotal was re-aggregated from the line.
    from decimal import Decimal

    assert isinstance(po["amount_subtotal"], str)
    assert Decimal(po["amount_subtotal"]) == Decimal("12050.00")
    assert Decimal(po["amount_total"]) == Decimal("12050.00")
    po_item_id = po["items"][0]["id"]

    # Approve (MANAGER) -> approved.
    resp = await http_client.post(
        f"/api/v1/procurement/{po_id}/approve/",
        headers=owner_a["headers"],
    )
    assert resp.status_code == 200, f"approve failed: {resp.text}"
    assert resp.json()["status"] == "approved"

    # Issue (MANAGER) -> issued.
    resp = await http_client.post(
        f"/api/v1/procurement/{po_id}/issue/",
        headers=owner_a["headers"],
    )
    assert resp.status_code == 200, f"issue failed: {resp.text}"
    assert resp.json()["status"] == "issued"

    # Record a goods receipt for the full quantity (draft).
    resp = await http_client.post(
        "/api/v1/procurement/goods-receipts/",
        json={
            "po_id": po_id,
            "receipt_date": "2026-05-24",
            "items": [
                {"po_item_id": po_item_id, "quantity_received": "100"},
            ],
        },
        headers=owner_a["headers"],
    )
    assert resp.status_code == 201, f"create GR failed: {resp.text}"
    gr = resp.json()
    assert gr["status"] == "draft"
    gr_id = gr["id"]

    # Confirm the GR -> PO is fully received -> completed.
    resp = await http_client.post(
        f"/api/v1/procurement/goods-receipts/{gr_id}/confirm/",
        headers=owner_a["headers"],
    )
    assert resp.status_code == 200, f"confirm GR failed: {resp.text}"
    assert resp.json()["status"] == "confirmed"

    # The PO rolled up to completed.
    resp = await http_client.get(
        f"/api/v1/procurement/{po_id}",
        headers=owner_a["headers"],
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed", (
        f"PO should be completed after full receipt, got {resp.json()['status']!r}"
    )


@pytest.mark.asyncio
async def test_partial_receipt_sets_partially_received(http_client, owner_a):
    """A GR for less than the ordered quantity rolls the PO to
    partially_received, not completed."""
    project_id = await _create_project(http_client, owner_a["headers"])
    po = await _create_po(http_client, owner_a["headers"], project_id, quantity="100")
    po_id = po["id"]
    po_item_id = po["items"][0]["id"]

    await http_client.post(f"/api/v1/procurement/{po_id}/approve/", headers=owner_a["headers"])
    await http_client.post(f"/api/v1/procurement/{po_id}/issue/", headers=owner_a["headers"])

    resp = await http_client.post(
        "/api/v1/procurement/goods-receipts/",
        json={
            "po_id": po_id,
            "receipt_date": "2026-05-24",
            "items": [{"po_item_id": po_item_id, "quantity_received": "40"}],
        },
        headers=owner_a["headers"],
    )
    assert resp.status_code == 201, resp.text
    gr_id = resp.json()["id"]

    resp = await http_client.post(
        f"/api/v1/procurement/goods-receipts/{gr_id}/confirm/",
        headers=owner_a["headers"],
    )
    assert resp.status_code == 200, resp.text

    resp = await http_client.get(f"/api/v1/procurement/{po_id}", headers=owner_a["headers"])
    assert resp.json()["status"] == "partially_received"


@pytest.mark.asyncio
async def test_match_status_reflects_confirmed_receipt(http_client, owner_a):
    """After a partial confirmed receipt, the 3-way match overall status is
    ``partial`` (received < ordered, nothing invoiced)."""
    project_id = await _create_project(http_client, owner_a["headers"])
    po = await _create_po(http_client, owner_a["headers"], project_id, quantity="100")
    po_id = po["id"]
    po_item_id = po["items"][0]["id"]

    await http_client.post(f"/api/v1/procurement/{po_id}/approve/", headers=owner_a["headers"])
    await http_client.post(f"/api/v1/procurement/{po_id}/issue/", headers=owner_a["headers"])
    gr_resp = await http_client.post(
        "/api/v1/procurement/goods-receipts/",
        json={
            "po_id": po_id,
            "receipt_date": "2026-05-24",
            "items": [{"po_item_id": po_item_id, "quantity_received": "40"}],
        },
        headers=owner_a["headers"],
    )
    gr_id = gr_resp.json()["id"]
    await http_client.post(
        f"/api/v1/procurement/goods-receipts/{gr_id}/confirm/",
        headers=owner_a["headers"],
    )

    resp = await http_client.get(
        f"/api/v1/procurement/{po_id}/match-status/",
        headers=owner_a["headers"],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["overall_status"] == "partial"
    assert len(body["lines"]) == 1
    line = body["lines"][0]
    # Quantities render uniformly (no float "40.0").
    assert line["ordered_qty"] == "100"
    assert line["received_qty"] == "40"
    assert line["match_status"] == "partial"


@pytest.mark.asyncio
async def test_list_goods_receipts_by_project(http_client, owner_a):
    """The GR tab lists receipts by project_id and stamps the parent PO
    number on each row."""
    project_id = await _create_project(http_client, owner_a["headers"])
    po = await _create_po(http_client, owner_a["headers"], project_id, quantity="50")
    po_id = po["id"]
    po_item_id = po["items"][0]["id"]
    po_number = po["po_number"]

    await http_client.post(f"/api/v1/procurement/{po_id}/approve/", headers=owner_a["headers"])
    await http_client.post(f"/api/v1/procurement/{po_id}/issue/", headers=owner_a["headers"])
    await http_client.post(
        "/api/v1/procurement/goods-receipts/",
        json={
            "po_id": po_id,
            "receipt_date": "2026-05-24",
            "items": [{"po_item_id": po_item_id, "quantity_received": "50"}],
        },
        headers=owner_a["headers"],
    )

    resp = await http_client.get(
        f"/api/v1/procurement/goods-receipts/?project_id={project_id}",
        headers=owner_a["headers"],
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert len(items) >= 1
    assert all(gr["po_number"] == po_number for gr in items)


@pytest.mark.asyncio
async def test_goods_receipts_requires_a_scope(http_client, owner_a):
    """Neither po_id nor project_id -> a clear 400 (not a 422)."""
    resp = await http_client.get(
        "/api/v1/procurement/goods-receipts/",
        headers=owner_a["headers"],
    )
    assert resp.status_code == 400, resp.text


# ── 3. Edge paths: FSM + over-receipt + retainage guards ───────────────────


@pytest.mark.asyncio
async def test_create_po_with_non_draft_status_is_400(http_client, owner_a):
    """A PO must enter the FSM at draft - creating one already 'approved'
    bypasses the budget-commit gate and is rejected."""
    project_id = await _create_project(http_client, owner_a["headers"])
    resp = await http_client.post(
        "/api/v1/procurement/",
        json={
            "project_id": project_id,
            "po_type": "standard",
            "currency_code": "EUR",
            "status": "approved",  # illegal initial state
        },
        headers=owner_a["headers"],
    )
    assert resp.status_code == 400, resp.text


@pytest.mark.asyncio
async def test_issue_before_approve_is_409(http_client, owner_a):
    """Issuing a still-draft PO (skipping approval) is a 409."""
    project_id = await _create_project(http_client, owner_a["headers"])
    po = await _create_po(http_client, owner_a["headers"], project_id, quantity="10")
    resp = await http_client.post(
        f"/api/v1/procurement/{po['id']}/issue/",
        headers=owner_a["headers"],
    )
    assert resp.status_code == 409, resp.text


@pytest.mark.asyncio
async def test_goods_receipt_against_draft_po_is_400(http_client, owner_a):
    """Only issued / partially_received POs accept goods receipts."""
    project_id = await _create_project(http_client, owner_a["headers"])
    po = await _create_po(http_client, owner_a["headers"], project_id, quantity="10")
    po_item_id = po["items"][0]["id"]
    resp = await http_client.post(
        "/api/v1/procurement/goods-receipts/",
        json={
            "po_id": po["id"],
            "receipt_date": "2026-05-24",
            "items": [{"po_item_id": po_item_id, "quantity_received": "5"}],
        },
        headers=owner_a["headers"],
    )
    assert resp.status_code == 400, resp.text


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_cumulative_over_receipt_is_blocked(http_client, owner_a):
    """Two confirmed receipts cannot exceed the ordered quantity in total.

    Order 100; receive+confirm 80; then a further 30 (cumulative 110) must be
    rejected with 400 - the cap counts the prior confirmed receipt.
    """
    project_id = await _create_project(http_client, owner_a["headers"])
    po = await _create_po(http_client, owner_a["headers"], project_id, quantity="100")
    po_id = po["id"]
    po_item_id = po["items"][0]["id"]

    await http_client.post(f"/api/v1/procurement/{po_id}/approve/", headers=owner_a["headers"])
    await http_client.post(f"/api/v1/procurement/{po_id}/issue/", headers=owner_a["headers"])

    # First receipt: 80, confirmed.
    gr1 = await http_client.post(
        "/api/v1/procurement/goods-receipts/",
        json={
            "po_id": po_id,
            "receipt_date": "2026-05-24",
            "items": [{"po_item_id": po_item_id, "quantity_received": "80"}],
        },
        headers=owner_a["headers"],
    )
    assert gr1.status_code == 201, gr1.text
    confirm1 = await http_client.post(
        f"/api/v1/procurement/goods-receipts/{gr1.json()['id']}/confirm/",
        headers=owner_a["headers"],
    )
    assert confirm1.status_code == 200, confirm1.text

    # Second receipt: 30 more -> cumulative 110 > 100 -> blocked at create.
    gr2 = await http_client.post(
        "/api/v1/procurement/goods-receipts/",
        json={
            "po_id": po_id,
            "receipt_date": "2026-05-25",
            "items": [{"po_item_id": po_item_id, "quantity_received": "30"}],
        },
        headers=owner_a["headers"],
    )
    assert gr2.status_code == 400, f"cumulative over-receipt should be blocked, got {gr2.status_code}: {gr2.text}"
    assert "exceeds ordered" in gr2.text


@pytest.mark.asyncio
async def test_retainage_release_over_held_is_400(http_client, owner_a):
    """Releasing more retainage than is held is a 400.

    ``retention_percent`` is not exposed on POCreate / POUpdate, so a PO
    created via the API holds 0 retainage. Releasing any positive amount
    therefore exceeds the held balance and must be rejected with 400 (never
    a silent over-release). The held-balance cap itself is unit-pinned with a
    non-zero retention in ``test_procurement_service_logic``.
    """
    project_id = await _create_project(http_client, owner_a["headers"])
    po = await _create_po(http_client, owner_a["headers"], project_id, quantity="100")
    po_id = po["id"]
    await http_client.post(f"/api/v1/procurement/{po_id}/approve/", headers=owner_a["headers"])
    await http_client.post(f"/api/v1/procurement/{po_id}/issue/", headers=owner_a["headers"])

    resp = await http_client.post(
        f"/api/v1/procurement/{po_id}/release-retainage/",
        json={"amount": "5000", "reason": "too much"},
        headers=owner_a["headers"],
    )
    assert resp.status_code == 400, f"over-held retainage release should be 400, got {resp.status_code}: {resp.text}"


@pytest.mark.asyncio
async def test_create_po_rejects_negative_money_422(http_client, owner_a):
    """Schema-level money validation: a negative subtotal is a 422 at the
    request boundary, never a 500 deeper in."""
    project_id = await _create_project(http_client, owner_a["headers"])
    resp = await http_client.post(
        "/api/v1/procurement/",
        json={
            "project_id": project_id,
            "po_type": "standard",
            "currency_code": "EUR",
            "status": "draft",
            "amount_subtotal": "-100",
        },
        headers=owner_a["headers"],
    )
    assert resp.status_code == 422, resp.text
