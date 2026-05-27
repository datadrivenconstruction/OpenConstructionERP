"""Tests for the v3124 sales-analytics endpoints.

Coverage matrix per endpoint:
- IDOR — cross-tenant scoping (random + cross-tenant dev_id → 404 or
  empty 200, never an existence oracle).
- Filter — ``since`` / ``until`` query params validated as YYYY-MM-DD;
  malformed values return 422.
- Money-as-string — every Decimal field on the JSON wire is a string,
  round-trippable via ``Decimal``.
- Empty-200 — a fresh tenant with no data gets a 200 + sensible empty
  shape (not 404 / 500).
- ETag + 304 — second request with If-None-Match short-circuits to 304.

Scaffolding (``client`` + ``_register_user``) comes from
``conftest.py``; we mint a fresh tenant pair so the analytics suite
can't accidentally read state left over from R7/R8.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient

from .conftest import _register_user

# ── Fixtures ────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def analytics_tenant_a(client: AsyncClient):
    """Tenant A admin with a project + dev + plot + buyer + reservation + SPA + handover."""
    _uid, _email, headers = await _register_user(client, role="admin", tag="ana")

    proj = await client.post(
        "/api/v1/projects/",
        json={
            "name": f"Analytics-{uuid.uuid4().hex[:6]}",
            "description": "analytics tenant A",
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
            "code": f"ANA-{uuid.uuid4().hex[:6]}",
            "name": "Analytics Heights",
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
            "plot_number": f"P-{uuid.uuid4().hex[:4]}",
            "area_m2": "120.00",
            "price_base": "450000.00",
            "currency": "EUR",
            "status": "planned",
        },
        headers=headers,
    )
    assert plot.status_code == 201, plot.text
    plot_id = plot.json()["id"]

    # Lead → Reservation → SPA so the time-to-close / funnel / cohort
    # widgets have at least one full chain of evidence to chew on.
    lead = await client.post(
        "/api/v1/property-dev/leads/",
        json={
            "development_id": development_id,
            "source": "web_form",
            "full_name": "Analytics Anna",
            "email": "anna-analytics@test.io",
            "status": "qualified",
        },
        headers=headers,
    )
    assert lead.status_code in (200, 201), lead.text
    lead_id = lead.json()["id"]

    res = await client.post(
        "/api/v1/property-dev/reservations/",
        json={
            "plot_id": plot_id,
            "lead_id": lead_id,
            "deposit_amount": "15000.00",
            "currency": "EUR",
            "cooling_off_days": 7,
        },
        headers=headers,
    )
    assert res.status_code == 201, res.text
    reservation_id = res.json()["id"]

    spa = await client.post(
        "/api/v1/property-dev/sales-contracts/",
        json={
            "plot_id": plot_id,
            "reservation_id": reservation_id,
            "total_value": "450000.50",
            "currency": "EUR",
            "signing_date": "2026-03-15",
        },
        headers=headers,
    )
    # SPA can land in draft state; force-status to signed via PATCH so the
    # closed-sale-based widgets exercise their happy paths.
    if spa.status_code == 201:
        spa_id = spa.json()["id"]
        await client.patch(
            f"/api/v1/property-dev/sales-contracts/{spa_id}",
            json={"status": "signed"},
            headers=headers,
        )

    return {
        "headers": headers,
        "project_id": project_id,
        "development_id": development_id,
        "plot_id": plot_id,
        "lead_id": lead_id,
        "reservation_id": reservation_id,
    }


@pytest_asyncio.fixture(scope="module")
async def analytics_tenant_b(client: AsyncClient):
    """Tenant B editor with their OWN project (used to probe IDOR)."""
    _uid, _email, headers = await _register_user(client, role="editor", tag="anb")

    proj = await client.post(
        "/api/v1/projects/",
        json={
            "name": f"Analytics-B-{uuid.uuid4().hex[:6]}",
            "description": "analytics tenant B",
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
            "code": f"ANB-{uuid.uuid4().hex[:6]}",
            "name": "Tenant-B Plot",
            "total_plots": 1,
            "currency": "EUR",
        },
        headers=headers,
    )
    assert dev.status_code == 201, dev.text
    development_id = dev.json()["id"]
    return {
        "headers": headers,
        "project_id": project_id,
        "development_id": development_id,
    }


@pytest_asyncio.fixture(scope="module")
async def analytics_tenant_c_empty(client: AsyncClient):
    """Tenant C editor with NO projects — exercises the empty-200 path."""
    _uid, _email, headers = await _register_user(client, role="editor", tag="anc")
    return {"headers": headers}


# ── 1. Cohort retention ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cohort_retention_200_with_data(
    client: AsyncClient,
    analytics_tenant_a,
):
    res = await client.get(
        "/api/v1/property-dev/dashboards/cohort-retention/",
        headers=analytics_tenant_a["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["cohort_period"] == "month"
    assert "cohorts" in body
    assert isinstance(body["cohorts"], list)
    # Cohort response includes at least the reservation we created.
    assert body["total_cohorts"] >= 1


@pytest.mark.asyncio
async def test_cohort_retention_empty_tenant_200(
    client: AsyncClient,
    analytics_tenant_c_empty,
):
    """Tenant with no devs gets 200 + empty (no oracle)."""
    res = await client.get(
        "/api/v1/property-dev/dashboards/cohort-retention/",
        headers=analytics_tenant_c_empty["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["cohorts"] == []
    assert body["total_cohorts"] == 0


@pytest.mark.asyncio
async def test_cohort_retention_bad_since_422(
    client: AsyncClient,
    analytics_tenant_a,
):
    """Malformed ``since`` (not YYYY-MM-DD) → 422."""
    res = await client.get(
        "/api/v1/property-dev/dashboards/cohort-retention/?since=2026-13-99",
        headers=analytics_tenant_a["headers"],
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_cohort_retention_money_pct_as_strings(
    client: AsyncClient,
    analytics_tenant_a,
):
    """Retention percentages serialize as plain-decimal strings."""
    res = await client.get(
        "/api/v1/property-dev/dashboards/cohort-retention/",
        headers=analytics_tenant_a["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    for row in body["cohorts"]:
        for fld in (
            "retention_pct_d30",
            "retention_pct_d60",
            "retention_pct_d90",
            "retention_pct_d180",
        ):
            assert isinstance(row[fld], str), f"{fld} should be str, got {type(row[fld]).__name__}"
            Decimal(row[fld])
            assert "E" not in row[fld] and "e" not in row[fld]


# ── 2. Time to close ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_time_to_close_200(client: AsyncClient, analytics_tenant_a):
    res = await client.get(
        "/api/v1/property-dev/dashboards/time-to-close/",
        headers=analytics_tenant_a["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert "stages" in body and isinstance(body["stages"], list)
    assert len(body["stages"]) == 4
    stage_codes = [s["stage"] for s in body["stages"]]
    assert stage_codes == [
        "lead_to_reservation",
        "reservation_to_sale",
        "sale_to_handover",
        "lead_to_handover",
    ]


@pytest.mark.asyncio
async def test_time_to_close_empty_tenant_200(
    client: AsyncClient,
    analytics_tenant_c_empty,
):
    res = await client.get(
        "/api/v1/property-dev/dashboards/time-to-close/",
        headers=analytics_tenant_c_empty["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["closed_sales"] == 0
    assert body["stages"] == []


@pytest.mark.asyncio
async def test_time_to_close_bad_until_422(
    client: AsyncClient,
    analytics_tenant_a,
):
    res = await client.get(
        "/api/v1/property-dev/dashboards/time-to-close/?until=garbage",
        headers=analytics_tenant_a["headers"],
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_time_to_close_decimal_days_as_strings(
    client: AsyncClient,
    analytics_tenant_a,
):
    """``mean_days`` / ``p50_days`` / ``p90_days`` serialize as strings."""
    res = await client.get(
        "/api/v1/property-dev/dashboards/time-to-close/",
        headers=analytics_tenant_a["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    for s in body["stages"]:
        for fld in ("mean_days", "p50_days", "p90_days"):
            assert isinstance(s[fld], str), f"{fld} should be str, got {type(s[fld]).__name__}"
            Decimal(s[fld])


# ── 3. Lead source attribution ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_lead_source_attribution_200(
    client: AsyncClient,
    analytics_tenant_a,
):
    res = await client.get(
        "/api/v1/property-dev/dashboards/lead-source-attribution/",
        headers=analytics_tenant_a["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert "rows" in body
    assert body["total_leads"] >= 1


@pytest.mark.asyncio
async def test_lead_source_attribution_empty_tenant_200(
    client: AsyncClient,
    analytics_tenant_c_empty,
):
    res = await client.get(
        "/api/v1/property-dev/dashboards/lead-source-attribution/",
        headers=analytics_tenant_c_empty["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["rows"] == []
    assert body["total_leads"] == 0


@pytest.mark.asyncio
async def test_lead_source_attribution_bad_since_422(
    client: AsyncClient,
    analytics_tenant_a,
):
    res = await client.get(
        "/api/v1/property-dev/dashboards/lead-source-attribution/?since=oops",
        headers=analytics_tenant_a["headers"],
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_lead_source_attribution_money_as_strings(
    client: AsyncClient,
    analytics_tenant_a,
):
    res = await client.get(
        "/api/v1/property-dev/dashboards/lead-source-attribution/",
        headers=analytics_tenant_a["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    for row in body["rows"]:
        for fld in (
            "conversion_to_reservation_pct",
            "conversion_to_sale_pct",
            "total_source_cost",
        ):
            assert isinstance(row[fld], str), f"{fld} should be str on attribution row"
            Decimal(row[fld])
        if row.get("cpa") is not None:
            assert isinstance(row["cpa"], str)
            Decimal(row["cpa"])
        for r in row["revenue"]:
            assert isinstance(r["amount"], str)
            Decimal(r["amount"])


# ── 4. Conversion funnel ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_conversion_funnel_200(client: AsyncClient, analytics_tenant_a):
    res = await client.get(
        "/api/v1/property-dev/dashboards/conversion-funnel/",
        headers=analytics_tenant_a["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert len(body["steps"]) == 5
    codes = [s["code"] for s in body["steps"]]
    assert codes == ["leads", "qualified", "reservation", "sale", "handover"]
    # First step has drop_pct = 0 (always).
    assert body["steps"][0]["drop_pct"] == "0"


@pytest.mark.asyncio
async def test_conversion_funnel_cross_tenant_dev_id_404(
    client: AsyncClient,
    analytics_tenant_a,
    analytics_tenant_b,
):
    """Tenant B passing tenant A's dev_id → 404 (R8 IDOR closure)."""
    res = await client.get(
        f"/api/v1/property-dev/dashboards/conversion-funnel/?dev_id={analytics_tenant_a['development_id']}",
        headers=analytics_tenant_b["headers"],
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_conversion_funnel_random_dev_id_404(
    client: AsyncClient,
    analytics_tenant_b,
):
    """Random UUID → 404 (no existence oracle)."""
    res = await client.get(
        f"/api/v1/property-dev/dashboards/conversion-funnel/?dev_id={uuid.uuid4()}",
        headers=analytics_tenant_b["headers"],
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_conversion_funnel_empty_tenant_200(
    client: AsyncClient,
    analytics_tenant_c_empty,
):
    res = await client.get(
        "/api/v1/property-dev/dashboards/conversion-funnel/",
        headers=analytics_tenant_c_empty["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["steps"] == []
    assert body["overall_conversion_pct"] == "0"


@pytest.mark.asyncio
async def test_conversion_funnel_bad_until_422(
    client: AsyncClient,
    analytics_tenant_a,
):
    res = await client.get(
        "/api/v1/property-dev/dashboards/conversion-funnel/?until=not-a-date",
        headers=analytics_tenant_a["headers"],
    )
    assert res.status_code == 422


# ── 5. Broker performance ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_broker_performance_200(
    client: AsyncClient,
    analytics_tenant_a,
):
    res = await client.get(
        "/api/v1/property-dev/dashboards/broker-performance/",
        headers=analytics_tenant_a["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert "rows" in body
    assert isinstance(body["rows"], list)


@pytest.mark.asyncio
async def test_broker_performance_empty_tenant_200(
    client: AsyncClient,
    analytics_tenant_c_empty,
):
    res = await client.get(
        "/api/v1/property-dev/dashboards/broker-performance/",
        headers=analytics_tenant_c_empty["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["rows"] == []
    assert body["total_brokers"] == 0


@pytest.mark.asyncio
async def test_broker_performance_bad_since_422(
    client: AsyncClient,
    analytics_tenant_a,
):
    res = await client.get(
        "/api/v1/property-dev/dashboards/broker-performance/?since=2026/13/01",
        headers=analytics_tenant_a["headers"],
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_broker_performance_conversion_pct_as_string(
    client: AsyncClient,
    analytics_tenant_a,
):
    """If any broker rows exist, conversion_rate_pct should be a string."""
    res = await client.get(
        "/api/v1/property-dev/dashboards/broker-performance/",
        headers=analytics_tenant_a["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    for row in body["rows"]:
        assert isinstance(row["conversion_rate_pct"], str)
        Decimal(row["conversion_rate_pct"])
        for amt in row["gmv"]:
            assert isinstance(amt["amount"], str)
            Decimal(amt["amount"])
        for amt in row["commission_earned"]:
            assert isinstance(amt["amount"], str)
            Decimal(amt["amount"])


# ── Cross-endpoint cache headers ──────────────────────────────────────


@pytest.mark.asyncio
async def test_cohort_retention_etag_304_short_circuit(
    client: AsyncClient,
    analytics_tenant_a,
):
    """Repeat request with If-None-Match → 304."""
    first = await client.get(
        "/api/v1/property-dev/dashboards/cohort-retention/",
        headers=analytics_tenant_a["headers"],
    )
    assert first.status_code == 200
    etag = first.headers.get("ETag")
    assert etag, "ETag header missing on cohort-retention response"
    assert "max-age=120" in first.headers.get("Cache-Control", "")

    second = await client.get(
        "/api/v1/property-dev/dashboards/cohort-retention/",
        headers={**analytics_tenant_a["headers"], "If-None-Match": etag},
    )
    assert second.status_code == 304, f"expected 304, got {second.status_code}: {second.text!r}"


@pytest.mark.asyncio
async def test_broker_performance_cache_control_header(
    client: AsyncClient,
    analytics_tenant_a,
):
    res = await client.get(
        "/api/v1/property-dev/dashboards/broker-performance/",
        headers=analytics_tenant_a["headers"],
    )
    assert res.status_code == 200
    assert "max-age=120" in res.headers.get("Cache-Control", "")
    assert res.headers.get("ETag")
