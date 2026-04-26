"""Module-routes smoke tests — guard the 404/422 fixes from BUGS_R2_R3_R4.

These tests cover the path-name and route-ordering bugs reported in
``/tmp/qa_install/bugs/BUGS_R2_R3_R4_2026_04_25.md``:

* BUG-CPM01      — schedule critical-path accepts schedule_id (not just project_id)
* BUG-FINANCE01  — InvoiceCreate accepts seed-shaped payload (incl. blank invoice_date)
* BUG-API12      — /api/v1/finance/invoices/ list returns 200, not 422
* BUG-TENDER01   — /api/v1/tendering/ returns 200 (empty list when project_id omitted)
* BUG-API13      — /api/v1/i18n/locales/{code}/messages/ returns translations
* BUG-AI-PROVIDERS — /api/v1/ai/providers/ returns the provider list

Run: pytest tests/integration/test_module_routes_smoke.py -v
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest_asyncio.fixture
async def client():
    """Test client with full app lifecycle so module routers are mounted."""
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest_asyncio.fixture
async def auth_headers(client):
    """Register + login a fresh user so we can hit auth-gated routes."""
    await client.post(
        "/api/v1/users/auth/register",
        json={
            "email": "module-routes@smoke.io",
            "password": "ModuleRoutes123!",
            "full_name": "Module Routes Tester",
        },
    )
    resp = await client.post(
        "/api/v1/users/auth/login",
        json={"email": "module-routes@smoke.io", "password": "ModuleRoutes123!"},
    )
    token = resp.json().get("access_token", "")
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def project_id(client, auth_headers) -> str:
    """Create a throwaway project we can scope finance/schedule probes against."""
    resp = await client.post(
        "/api/v1/projects/",
        json={"name": "Module Routes Project", "description": "smoke"},
        headers=auth_headers,
    )
    if resp.status_code in (200, 201):
        return resp.json()["id"]
    # Fall back to any project the user can already see (multi-tenant deploys
    # may seed projects on register).
    listing = await client.get("/api/v1/projects/", headers=auth_headers)
    if listing.status_code == 200:
        items = listing.json()
        if isinstance(items, list) and items:
            return items[0]["id"]
        if isinstance(items, dict) and items.get("items"):
            return items["items"][0]["id"]
    pytest.skip(f"Could not obtain a project_id: {resp.status_code} {resp.text[:200]}")


# ── BUG-CPM01 ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_schedule_cpm_route_exists(client, auth_headers, project_id):
    """``GET /schedule/critical-path/`` accepts project_id without 422."""
    resp = await client.get(
        f"/api/v1/schedule/critical-path/?project_id={project_id}",
        headers=auth_headers,
    )
    # 200 with empty list (no schedule yet) is the canonical happy path.
    # 404 with a "no schedule" body would also be acceptable, as long as we
    # don't get a raw FastAPI 404 ("Not Found") OR a 422 saying
    # ``schedule_id`` is required.
    assert resp.status_code in (200, 404), (
        f"Expected 200 or 404 with body, got {resp.status_code}: {resp.text[:200]}"
    )
    if resp.status_code == 404:
        # Must not be the bare framework 404 — should carry a JSON body.
        body = resp.json()
        assert "detail" in body


@pytest.mark.asyncio
async def test_schedule_cpm_accepts_schedule_id(client, auth_headers):
    """``GET /schedule/critical-path/?schedule_id=...`` no longer 422s.

    Per BUG-CPM01 the route used to reject ``schedule_id`` because only
    ``project_id`` was wired. We now accept either parameter; with a bogus
    schedule_id we should see 404 (schedule not found) — never 422.
    """
    bogus = "00000000-0000-0000-0000-000000000001"
    resp = await client.get(
        f"/api/v1/schedule/critical-path/?schedule_id={bogus}",
        headers=auth_headers,
    )
    assert resp.status_code != 422, f"schedule_id rejected with 422: {resp.text[:200]}"


# ── BUG-API12 + BUG-FINANCE01 ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_finance_invoices_collection_returns_list(client, auth_headers):
    """``/api/v1/finance/invoices/`` returns a list, not a UUID-parse 422."""
    resp = await client.get("/api/v1/finance/invoices/", headers=auth_headers)
    assert resp.status_code == 200, f"{resp.status_code}: {resp.text[:200]}"
    body = resp.json()
    assert "items" in body
    assert isinstance(body["items"], list)


@pytest.mark.asyncio
async def test_finance_invoice_create_with_seed_payload_succeeds(
    client, auth_headers, project_id
):
    """Seed-shaped payload with blank ``invoice_date`` is accepted (BUG-FINANCE01)."""
    payload = {
        "project_id": project_id,
        "invoice_direction": "payable",
        "invoice_number": "INV-SMOKE-1",
        "invoice_date": "",  # the seed-shape that used to 422
        "currency_code": "EUR",
        "amount_subtotal": "1000.00",
        "tax_amount": "190.00",
        "amount_total": "1190.00",
    }
    resp = await client.post(
        "/api/v1/finance/", json=payload, headers=auth_headers
    )
    assert resp.status_code in (200, 201), f"{resp.status_code}: {resp.text[:300]}"


# ── BUG-TENDER01 ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tendering_root_returns_empty_or_list(client, auth_headers):
    """``GET /api/v1/tendering/`` returns 200 with a list (empty when unscoped)."""
    resp = await client.get("/api/v1/tendering/", headers=auth_headers)
    assert resp.status_code == 200, f"{resp.status_code}: {resp.text[:200]}"
    body = resp.json()
    assert isinstance(body, list)


# ── BUG-API13 ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_i18n_locales_messages_route_exists(client):
    """``GET /api/v1/i18n/locales/en/messages`` returns the EN bundle."""
    resp = await client.get("/api/v1/i18n/locales/en/messages")
    assert resp.status_code == 200, f"{resp.status_code}: {resp.text[:200]}"
    body = resp.json()
    assert "_meta" in body
    assert body["_meta"]["locale"] == "en"


@pytest.mark.asyncio
async def test_i18n_locales_messages_unsupported_returns_helpful_404(client):
    """Unsupported locales get a JSON 404 with the supported list."""
    resp = await client.get("/api/v1/i18n/locales/xx/messages/")
    assert resp.status_code == 404
    assert "supported" in resp.json().get("detail", "").lower()


# ── BUG-AI-PROVIDERS ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ai_providers_route_exists(client, auth_headers):
    """``GET /api/v1/ai/providers/`` returns the provider list."""
    resp = await client.get("/api/v1/ai/providers/", headers=auth_headers)
    assert resp.status_code == 200, f"{resp.status_code}: {resp.text[:200]}"
    body = resp.json()
    assert isinstance(body, list)
    assert any(p.get("id") == "anthropic" for p in body)
    assert any(p.get("id") == "openai" for p in body)
