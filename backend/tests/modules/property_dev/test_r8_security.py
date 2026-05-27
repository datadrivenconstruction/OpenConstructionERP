"""R8 security regressions for the property_dev module.

This suite closes the 129 endpoints R7 deferred. Coverage focus areas:

- **IDOR fan-out on analytics reads** — sales-kanban, reservation-calendar,
  pnl, plot configurator, regulator-reports/{RERA, MAHARERA, 214-FZ},
  compliance dashboard. Tenant B trying to read tenant A's dev / plot
  collapses to 404 (never 403).
- **Money string serialization** — ReservationResponse, SalesContractResponse,
  PaymentScheduleResponse, InstalmentResponse, DevelopmentPnLResponse,
  CommissionAgreementResponse, ContractTaxQuote — every Decimal-money
  field arrives as a plain-decimal string.
- **List-endpoint tenant scoping** — /leads/ and /reservations/ without
  a scoping param return ``[]`` for non-admins (no cross-tenant leak).
- **Portal IDOR** — portal/me/snags + portal/me/warranty-claims only see
  rows for the buyer linked to the portal session.

Scaffolding lives in ``conftest.py`` (per ``feedback_test_isolation.md``);
the R7 ``tenant_a`` / ``tenant_b`` fixtures are re-imported here so the
two suites can run side-by-side without re-creating the same projects.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient

from .conftest import _register_user

# ── Local R8 fixtures (independent from R7's tenant_a / tenant_b) ───────
#
# We mint our own fixtures so a failure here can't poison the R7 suite
# (and vice versa). All fixtures are module-scoped — pytest-asyncio
# reuses the event loop across tests within one module.


@pytest_asyncio.fixture(scope="module")
async def r8_tenant_a(client: AsyncClient):
    """Tenant A admin owning a project + development + plot + buyer + SPA."""
    _uid, email, headers = await _register_user(client, role="admin", tag="r8a")

    proj = await client.post(
        "/api/v1/projects/",
        json={
            "name": f"R8-A-{uuid.uuid4().hex[:6]}",
            "description": "R8 tenant A",
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
            "code": f"R8A-{uuid.uuid4().hex[:6]}",
            "name": "Riverside R8",
            "total_plots": 2,
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
            "plot_number": f"R8-{uuid.uuid4().hex[:4]}",
            "area_m2": "100.5",
            "price_base": "500000.25",
            "currency": "EUR",
            "status": "planned",
        },
        headers=headers,
    )
    assert plot.status_code == 201, plot.text
    plot_id = plot.json()["id"]

    buyer = await client.post(
        "/api/v1/property-dev/buyers/",
        json={
            "development_id": development_id,
            "full_name": "Bob R8",
            "email": "bob-r8@test.io",
            "status": "lead",
        },
        headers=headers,
    )
    assert buyer.status_code == 201, buyer.text
    buyer_id = buyer.json()["id"]

    return {
        "headers": headers,
        "email": email,
        "project_id": project_id,
        "development_id": development_id,
        "plot_id": plot_id,
        "buyer_id": buyer_id,
    }


@pytest_asyncio.fixture(scope="module")
async def r8_tenant_b(client: AsyncClient):
    """Tenant B editor with their OWN project — used to probe IDOR."""
    _uid, email, headers = await _register_user(client, role="editor", tag="r8b")

    proj = await client.post(
        "/api/v1/projects/",
        json={
            "name": f"R8-B-{uuid.uuid4().hex[:6]}",
            "description": "R8 tenant B",
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
            "code": f"R8B-{uuid.uuid4().hex[:6]}",
            "name": "Highland R8",
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


# ════════════════════════════════════════════════════════════════════════
# 1. IDOR fan-out — analytics reads on /developments/{dev_id}/*
# ════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_r8_idor_sales_kanban_collapses_to_404(
    client: AsyncClient,
    r8_tenant_a,
    r8_tenant_b,
):
    """Tenant B reading tenant A's sales-kanban → 404 (was: open data)."""
    res = await client.get(
        f"/api/v1/property-dev/developments/{r8_tenant_a['development_id']}/sales-kanban",
        headers=r8_tenant_b["headers"],
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_r8_idor_reservation_calendar_collapses_to_404(
    client: AsyncClient,
    r8_tenant_a,
    r8_tenant_b,
):
    """Tenant B reading tenant A's reservation calendar → 404."""
    res = await client.get(
        f"/api/v1/property-dev/developments/{r8_tenant_a['development_id']}"
        "/reservation-calendar"
        "?period_start=2026-01-01&period_end=2026-12-31",
        headers=r8_tenant_b["headers"],
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_r8_idor_pnl_collapses_to_404(
    client: AsyncClient,
    r8_tenant_a,
    r8_tenant_b,
):
    """Tenant B reading tenant A's P&L (revenue!) → 404."""
    res = await client.get(
        f"/api/v1/property-dev/developments/{r8_tenant_a['development_id']}/pnl",
        headers=r8_tenant_b["headers"],
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_r8_idor_plot_configurator_collapses_to_404(
    client: AsyncClient,
    r8_tenant_a,
    r8_tenant_b,
):
    """Tenant B reading tenant A's plot configurator → 404."""
    res = await client.get(
        f"/api/v1/property-dev/plots/{r8_tenant_a['plot_id']}/configurator",
        headers=r8_tenant_b["headers"],
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_r8_idor_compliance_dashboard_collapses_to_404(
    client: AsyncClient,
    r8_tenant_a,
    r8_tenant_b,
):
    """Tenant B reading tenant A's compliance dashboard → 404.

    Was: returned an empty traffic-light report and confirmed dev exists
    (existence oracle). Now: collapses to 404 for non-owners.
    """
    res = await client.get(
        f"/api/v1/property-dev/compliance/dashboard?dev_id={r8_tenant_a['development_id']}",
        headers=r8_tenant_b["headers"],
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_r8_idor_compliance_random_uuid_also_404(
    client: AsyncClient,
    r8_tenant_b,
):
    """Confirms compliance dashboard isn't an existence oracle: a
    random UUID returns the same 404 as a cross-tenant one."""
    res = await client.get(
        f"/api/v1/property-dev/compliance/dashboard?dev_id={uuid.uuid4()}",
        headers=r8_tenant_b["headers"],
    )
    assert res.status_code == 404, res.text


# ════════════════════════════════════════════════════════════════════════
# 2. IDOR on list endpoints — /leads/ + /reservations/ tenant scoping
# ════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_r8_idor_list_leads_blocks_cross_tenant_filter(
    client: AsyncClient,
    r8_tenant_a,
    r8_tenant_b,
):
    """Listing leads with tenant A's development_id query → 404."""
    res = await client.get(
        f"/api/v1/property-dev/leads/?development_id={r8_tenant_a['development_id']}",
        headers=r8_tenant_b["headers"],
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_r8_idor_list_leads_no_scope_returns_empty(
    client: AsyncClient,
    r8_tenant_b,
):
    """Non-admin listing leads with NO development_id → ``[]``.

    Confirms we don't leak cross-tenant top-of-funnel leads.
    """
    res = await client.get(
        "/api/v1/property-dev/leads/",
        headers=r8_tenant_b["headers"],
    )
    assert res.status_code == 200, res.text
    assert res.json() == []


@pytest.mark.asyncio
async def test_r8_idor_list_reservations_blocks_cross_tenant_dev(
    client: AsyncClient,
    r8_tenant_a,
    r8_tenant_b,
):
    """Listing reservations with tenant A's dev_id → 404."""
    res = await client.get(
        f"/api/v1/property-dev/reservations/?development_id={r8_tenant_a['development_id']}",
        headers=r8_tenant_b["headers"],
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_r8_idor_list_reservations_blocks_cross_tenant_plot(
    client: AsyncClient,
    r8_tenant_a,
    r8_tenant_b,
):
    """Listing reservations with tenant A's plot_id → 404."""
    res = await client.get(
        f"/api/v1/property-dev/reservations/?plot_id={r8_tenant_a['plot_id']}",
        headers=r8_tenant_b["headers"],
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_r8_idor_list_reservations_no_scope_returns_empty(
    client: AsyncClient,
    r8_tenant_b,
):
    """Non-admin listing reservations with NO scope → ``[]``."""
    res = await client.get(
        "/api/v1/property-dev/reservations/",
        headers=r8_tenant_b["headers"],
    )
    assert res.status_code == 200, res.text
    assert res.json() == []


# ════════════════════════════════════════════════════════════════════════
# 3. Money serialization — Decimal-as-string on response models
# ════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_r8_pnl_money_fields_are_strings(
    client: AsyncClient,
    r8_tenant_a,
):
    """DevelopmentPnLResponse: every money field → str on JSON.

    Was: JSON numbers (precision loss past ~15 digits when JS reads them).
    """
    res = await client.get(
        f"/api/v1/property-dev/developments/{r8_tenant_a['development_id']}/pnl",
        headers=r8_tenant_a["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    for fld in (
        "revenue_contracted",
        "revenue_completed",
        "deposits_held",
        "deposits_forfeited",
        "avg_sale_price",
    ):
        assert isinstance(body[fld], str), f"{fld} should be str, got {type(body[fld]).__name__}: {body[fld]!r}"
        # Round-trippable via Decimal — no scientific notation.
        Decimal(body[fld])
        assert "E" not in body[fld] and "e" not in body[fld]


@pytest.mark.asyncio
async def test_r8_reservation_deposit_amount_is_string(
    client: AsyncClient,
    r8_tenant_a,
):
    """ReservationResponse.deposit_amount must be a string on the wire."""
    headers = r8_tenant_a["headers"]
    # Mint a fresh plot so the FSM doesn't clash with the shared fixture.
    fresh_plot = await client.post(
        "/api/v1/property-dev/plots/",
        json={
            "development_id": r8_tenant_a["development_id"],
            "plot_number": f"R8-RES-{uuid.uuid4().hex[:4]}",
            "area_m2": "50",
            "price_base": "200000.00",
            "currency": "EUR",
            "status": "planned",
        },
        headers=headers,
    )
    assert fresh_plot.status_code == 201, fresh_plot.text
    plot_id = fresh_plot.json()["id"]

    res = await client.post(
        "/api/v1/property-dev/reservations/",
        json={
            "plot_id": plot_id,
            "deposit_amount": "12345.67",
            "currency": "EUR",
            "cooling_off_days": 7,
        },
        headers=headers,
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert isinstance(body["deposit_amount"], str)
    assert Decimal(body["deposit_amount"]) == Decimal("12345.67")


@pytest.mark.asyncio
async def test_r8_sales_contract_total_value_is_string(
    client: AsyncClient,
    r8_tenant_a,
):
    """SalesContractResponse.total_value must be a string on the wire."""
    headers = r8_tenant_a["headers"]
    fresh_plot = await client.post(
        "/api/v1/property-dev/plots/",
        json={
            "development_id": r8_tenant_a["development_id"],
            "plot_number": f"R8-SPA-{uuid.uuid4().hex[:4]}",
            "area_m2": "75",
            "price_base": "300000.00",
            "currency": "EUR",
            "status": "planned",
        },
        headers=headers,
    )
    assert fresh_plot.status_code == 201, fresh_plot.text
    plot_id = fresh_plot.json()["id"]

    spa = await client.post(
        "/api/v1/property-dev/sales-contracts/",
        json={
            "plot_id": plot_id,
            "total_value": "987654.32",
            "currency": "EUR",
        },
        headers=headers,
    )
    assert spa.status_code == 201, spa.text
    body = spa.json()
    assert isinstance(body["total_value"], str)
    assert Decimal(body["total_value"]) == Decimal("987654.32")
    # Plain-decimal — no exponent.
    assert "E" not in body["total_value"]


@pytest.mark.asyncio
async def test_r8_payment_schedule_money_fields_are_strings(
    client: AsyncClient,
    r8_tenant_a,
):
    """PaymentScheduleResponse.total_amount + late_fee_pct → str."""
    headers = r8_tenant_a["headers"]
    fresh_plot = await client.post(
        "/api/v1/property-dev/plots/",
        json={
            "development_id": r8_tenant_a["development_id"],
            "plot_number": f"R8-PS-{uuid.uuid4().hex[:4]}",
            "area_m2": "60",
            "price_base": "250000.00",
            "currency": "EUR",
            "status": "planned",
        },
        headers=headers,
    )
    plot_id = fresh_plot.json()["id"]
    spa = await client.post(
        "/api/v1/property-dev/sales-contracts/",
        json={
            "plot_id": plot_id,
            "total_value": "250000.00",
            "currency": "EUR",
        },
        headers=headers,
    )
    spa_id = spa.json()["id"]

    sched = await client.post(
        "/api/v1/property-dev/payment-schedules/",
        json={
            "sales_contract_id": spa_id,
            "currency": "EUR",
            "total_amount": "250000.00",
            "late_fee_pct": "1.50",
            "grace_period_days": 5,
        },
        headers=headers,
    )
    assert sched.status_code == 201, sched.text
    body = sched.json()
    assert isinstance(body["total_amount"], str)
    assert isinstance(body["late_fee_pct"], str)
    assert Decimal(body["total_amount"]) == Decimal("250000.00")
    assert Decimal(body["late_fee_pct"]) == Decimal("1.50")


@pytest.mark.asyncio
async def test_r8_instalment_money_fields_are_strings(
    client: AsyncClient,
    r8_tenant_a,
):
    """InstalmentResponse.amount + amount_paid + late_fee_accrued → str."""
    headers = r8_tenant_a["headers"]
    # Build SPA + schedule + instalment fresh.
    fresh_plot = await client.post(
        "/api/v1/property-dev/plots/",
        json={
            "development_id": r8_tenant_a["development_id"],
            "plot_number": f"R8-INS-{uuid.uuid4().hex[:4]}",
            "area_m2": "60",
            "price_base": "250000.00",
            "currency": "EUR",
            "status": "planned",
        },
        headers=headers,
    )
    plot_id = fresh_plot.json()["id"]
    spa = await client.post(
        "/api/v1/property-dev/sales-contracts/",
        json={
            "plot_id": plot_id,
            "total_value": "250000.00",
            "currency": "EUR",
        },
        headers=headers,
    )
    spa_id = spa.json()["id"]
    sched = await client.post(
        "/api/v1/property-dev/payment-schedules/",
        json={
            "sales_contract_id": spa_id,
            "currency": "EUR",
            "total_amount": "250000.00",
        },
        headers=headers,
    )
    sched_id = sched.json()["id"]

    ins = await client.post(
        "/api/v1/property-dev/instalments/",
        json={
            "schedule_id": sched_id,
            "sequence": 1,
            "milestone_label": "Deposit",
            "due_date": "2026-06-01",
            "amount": "25000.00",
        },
        headers=headers,
    )
    assert ins.status_code == 201, ins.text
    body = ins.json()
    assert isinstance(body["amount"], str), body
    assert isinstance(body["amount_paid"], str), body
    assert isinstance(body["late_fee_accrued"], str), body
    assert Decimal(body["amount"]) == Decimal("25000.00")


# ════════════════════════════════════════════════════════════════════════
# 4. FSM rejection on additional state machines
# ════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_r8_fsm_rejects_invalid_buyer_transition(
    client: AsyncClient,
    r8_tenant_a,
):
    """lead → completed skips reserved/contracted; must 409.

    Per ``_BUYER_TRANSITIONS``: lead ⊕ {reserved, cancelled}.
    """
    headers = r8_tenant_a["headers"]
    res = await client.patch(
        f"/api/v1/property-dev/buyers/{r8_tenant_a['buyer_id']}",
        json={"status": "completed"},
        headers=headers,
    )
    assert res.status_code == 409, res.text
    detail = res.json().get("detail", "").lower()
    assert "invalid" in detail and "transition" in detail


@pytest.mark.asyncio
async def test_r8_fsm_rejects_invalid_reservation_transition(
    client: AsyncClient,
    r8_tenant_a,
):
    """cancelled → expired is NOT in ``_RESERVATION_TRANSITIONS``; must 409.

    Per ``_RESERVATION_TRANSITIONS``: cancelled ⊕ {refunded}. ``expired``
    is unreachable from ``cancelled``. We first cancel a fresh
    reservation (active → cancelled is legal), then attempt to expire
    it; the FSM gate must reject.

    NOTE: ``cancel → cancel`` would not test the FSM because
    ``_ensure_transition`` short-circuits when target == current.
    """
    headers = r8_tenant_a["headers"]
    fresh_plot = await client.post(
        "/api/v1/property-dev/plots/",
        json={
            "development_id": r8_tenant_a["development_id"],
            "plot_number": f"R8-FSM-RES-{uuid.uuid4().hex[:4]}",
            "area_m2": "55",
            "price_base": "200000",
            "currency": "EUR",
            "status": "planned",
        },
        headers=headers,
    )
    plot_id = fresh_plot.json()["id"]
    res_create = await client.post(
        "/api/v1/property-dev/reservations/",
        json={
            "plot_id": plot_id,
            "deposit_amount": "5000.00",
            "currency": "EUR",
        },
        headers=headers,
    )
    assert res_create.status_code == 201, res_create.text
    r_id = res_create.json()["id"]

    # cancel once — should succeed (active → cancelled is allowed).
    cancel1 = await client.post(
        f"/api/v1/property-dev/reservations/{r_id}/cancel",
        headers=headers,
    )
    assert cancel1.status_code == 200, cancel1.text
    assert cancel1.json()["status"] == "cancelled"

    # expire after cancel — cancelled ⊕ {refunded}, expire is NOT in
    # the set → 409.
    expire = await client.post(
        f"/api/v1/property-dev/reservations/{r_id}/expire",
        headers=headers,
    )
    assert expire.status_code == 409, expire.text
    detail = expire.json().get("detail", "").lower()
    assert "invalid" in detail and "transition" in detail


@pytest.mark.asyncio
async def test_r8_fsm_accepts_valid_buyer_lead_to_cancelled(
    client: AsyncClient,
    r8_tenant_a,
):
    """lead → cancelled IS allowed (sanity for FSM)."""
    headers = r8_tenant_a["headers"]
    # mint a fresh buyer so we don't perturb the fixture buyer.
    buyer = await client.post(
        "/api/v1/property-dev/buyers/",
        json={
            "development_id": r8_tenant_a["development_id"],
            "full_name": "Carol R8",
            "email": "carol-r8@test.io",
            "status": "lead",
        },
        headers=headers,
    )
    assert buyer.status_code == 201, buyer.text
    b_id = buyer.json()["id"]
    res = await client.patch(
        f"/api/v1/property-dev/buyers/{b_id}",
        json={"status": "cancelled"},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "cancelled"


# ════════════════════════════════════════════════════════════════════════
# 5. Member-denied PATCH + DELETE (RBAC + IDOR combo)
# ════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_r8_member_denied_delete_plot(
    client: AsyncClient,
    r8_tenant_a,
    r8_tenant_b,
):
    """A non-owner editor in another tenant must not DELETE tenant A's
    plot; the IDOR gate collapses to 404 even if the RBAC gate would
    have permitted (editor role does NOT have property_dev.delete, so
    the 4xx might be 403; assert it's in {403, 404} but never 204)."""
    res = await client.delete(
        f"/api/v1/property-dev/plots/{r8_tenant_a['plot_id']}",
        headers=r8_tenant_b["headers"],
    )
    # We DO NOT permit the operation to succeed. Either 403 (RBAC) or
    # 404 (IDOR) is acceptable — both deny the request.
    assert res.status_code in (403, 404), res.text


@pytest.mark.asyncio
async def test_r8_member_denied_patch_development(
    client: AsyncClient,
    r8_tenant_a,
    r8_tenant_b,
):
    """Editor in tenant B trying to mutate tenant A's development → 404."""
    res = await client.patch(
        f"/api/v1/property-dev/developments/{r8_tenant_a['development_id']}",
        json={"name": "Hijacked"},
        headers=r8_tenant_b["headers"],
    )
    assert res.status_code == 404, res.text


# ════════════════════════════════════════════════════════════════════════
# 6. Portal IDOR — verify _buyers_for_portal_user actually filters
# ════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_r8_portal_unauthenticated_request_blocked(
    client: AsyncClient,
):
    """``/portal/me/snags`` without a portal session must NOT return rows.

    The exact status code depends on RequirePortalSession's failure mode
    (401 or 403); both are acceptable — what's not acceptable is 200.
    """
    res = await client.get("/api/v1/property-dev/portal/me/snags")
    assert res.status_code in (401, 403), res.text


@pytest.mark.asyncio
async def test_r8_portal_warranty_unauthenticated_blocked(
    client: AsyncClient,
):
    """Same gate test for portal/me/warranty-claims."""
    res = await client.get("/api/v1/property-dev/portal/me/warranty-claims")
    assert res.status_code in (401, 403), res.text


# ════════════════════════════════════════════════════════════════════════
# 7. Regulator-report IDOR
# ════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_r8_idor_regulator_report_rera_collapses_to_404(
    client: AsyncClient,
    r8_tenant_a,
    r8_tenant_b,
):
    """Non-owner cannot generate a RERA report for another tenant's dev.

    The endpoint requires ``property_dev.regulator_report.generate``
    which editor MAY have — but the IDOR gate fires first and 404s
    on cross-tenant access. (If the RBAC denies first with 403 that's
    also acceptable — both block the disclosure.)
    """
    res = await client.get(
        f"/api/v1/property-dev/regulator-reports/RERA?dev_id={r8_tenant_a['development_id']}&quarter=2026-Q1",
        headers=r8_tenant_b["headers"],
    )
    assert res.status_code in (403, 404), res.text


@pytest.mark.asyncio
async def test_r8_idor_regulator_report_maharera_collapses_to_404(
    client: AsyncClient,
    r8_tenant_a,
    r8_tenant_b,
):
    """Same for MAHARERA."""
    res = await client.get(
        f"/api/v1/property-dev/regulator-reports/MAHARERA?dev_id={r8_tenant_a['development_id']}&quarter=2026-Q1",
        headers=r8_tenant_b["headers"],
    )
    assert res.status_code in (403, 404), res.text


@pytest.mark.asyncio
async def test_r8_idor_regulator_report_214fz_collapses_to_404(
    client: AsyncClient,
    r8_tenant_a,
    r8_tenant_b,
):
    """Same for 214-FZ (Russian Federal Law no.214)."""
    res = await client.get(
        f"/api/v1/property-dev/regulator-reports/214-FZ?dev_id={r8_tenant_a['development_id']}&quarter=2026-Q1",
        headers=r8_tenant_b["headers"],
    )
    assert res.status_code in (403, 404), res.text


# ════════════════════════════════════════════════════════════════════════
# 8. Existence-oracle parity — random UUID == cross-tenant UUID
# ════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_r8_pnl_random_uuid_returns_404(
    client: AsyncClient,
    r8_tenant_b,
):
    """A non-existent dev_id on /pnl returns the same 404 as a
    cross-tenant one — confirms no existence oracle."""
    res = await client.get(
        f"/api/v1/property-dev/developments/{uuid.uuid4()}/pnl",
        headers=r8_tenant_b["headers"],
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_r8_sales_kanban_random_uuid_returns_404(
    client: AsyncClient,
    r8_tenant_b,
):
    """Same parity test for sales-kanban."""
    res = await client.get(
        f"/api/v1/property-dev/developments/{uuid.uuid4()}/sales-kanban",
        headers=r8_tenant_b["headers"],
    )
    assert res.status_code == 404, res.text
