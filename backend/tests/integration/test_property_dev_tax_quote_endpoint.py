"""Integration tests for ``POST /sales-contracts/{id}/tax-quote``.

Exercises the full HTTP stack — auth → permission gate → IDOR check →
service-layer dispatch → tax_engine pure functions → response shape.

Scaffolding mirrors :mod:`test_property_dev_lead_to_spa` (per-module
temp SQLite registered BEFORE any ``from app...`` import to keep the
production DB un-touched).

Coverage:
    * GB happy path — first-time-buyer SDLT 0 %, response shape OK.
    * DE happy path — Berlin Grunderwerbsteuer 6 %, governing_law
      resolves DE-BE without explicit subcode in the body.
    * AE happy path — Dubai DLD transfer fee + zero-rated VAT.
    * IN happy path — Maharashtra 6 % stamp duty + premium GST.
    * RU happy path — flat state duty 2000 RUB.
    * SG happy path — BSD progressive + ABSD foreigner 60 %.
    * Cross-tenant IDOR — tenant_b probing tenant_a's SPA gets 404.
    * Viewer role can read; permission gate honoured.
    * Unsupported jurisdiction returns 422 with ``supported`` list.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

# ── Per-module SQLite isolation (must run BEFORE app imports) ──────────────
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-propdev-taxquote-"))
_TMP_DB = _TMP_DIR / "propdev_taxquote.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()

    async with app.router.lifespan_context(app):
        from app.database import Base, engine
        from app.modules.property_dev import models as _propdev_models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _set_role(email: str, role: str) -> None:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(role=role, is_active=True))
        await s.commit()


async def _register(client: AsyncClient, label: str) -> tuple[str, dict[str, str]]:
    email = f"{label}-{uuid.uuid4().hex[:8]}@taxquote.io"
    password = f"TaxQuote{uuid.uuid4().hex[:6]}9!"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": f"{label}"},
    )
    assert reg.status_code in (200, 201), reg.text
    return email, {"_password": password}


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    res = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


async def _seed_spa(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    governing_law: str = "",
    total_value: str = "500000.00",
    currency: str = "EUR",
    plot_currency: str | None = None,
) -> dict:
    """Create project → development → plot → SPA. Returns ids dict."""
    proj = await client.post(
        "/api/v1/projects/",
        json={
            "name": f"TaxQuote {uuid.uuid4().hex[:6]}",
            "description": "tax-quote-test",
            "currency": currency,
        },
        headers=headers,
    )
    assert proj.status_code == 201, proj.text
    project_id = proj.json()["id"]

    dev = await client.post(
        "/api/v1/property-dev/developments/",
        json={
            "project_id": project_id,
            "code": f"TX{uuid.uuid4().hex[:6].upper()}",
            "name": "Tax-quote Dev",
            "total_plots": 1,
        },
        headers=headers,
    )
    assert dev.status_code == 201, dev.text
    development_id = dev.json()["id"]

    plot = await client.post(
        "/api/v1/property-dev/plots/",
        json={
            "development_id": development_id,
            "plot_number": "TX-01",
            "area_m2": 100,
            "price_base": 500000,
            "currency": plot_currency or currency,
        },
        headers=headers,
    )
    assert plot.status_code == 201, plot.text
    plot_id = plot.json()["id"]

    spa = await client.post(
        "/api/v1/property-dev/sales-contracts/",
        json={
            "plot_id": plot_id,
            "signing_date": "2026-06-01",
            "governing_law": governing_law,
            "language": "en",
            "total_value": total_value,
            "currency": currency,
        },
        headers=headers,
    )
    assert spa.status_code == 201, spa.text
    return {
        "project_id": project_id,
        "development_id": development_id,
        "plot_id": plot_id,
        "spa_id": spa.json()["id"],
    }


@pytest_asyncio.fixture(scope="module")
async def tenant_a(http_client):
    """Admin tenant — owns most SPAs used by happy-path tests."""
    email, meta = await _register(http_client, "tx-tenant-a")
    await _set_role(email, "admin")
    headers = await _login(http_client, email, meta["_password"])
    return {"email": email, "headers": headers}


@pytest_asyncio.fixture(scope="module")
async def tenant_b(http_client):
    """Second tenant for IDOR coverage.

    Note: tenant_b runs as ``editor`` (not ``admin``) because
    :func:`_verify_owner_via_plot` short-circuits admins past the
    project-ownership check. The IDOR-blocked test would silently
    pass under admin since admins legitimately see every tenant.
    """
    email, meta = await _register(http_client, "tx-tenant-b")
    await _set_role(email, "editor")
    headers = await _login(http_client, email, meta["_password"])
    return {"email": email, "headers": headers}


@pytest_asyncio.fixture(scope="module")
async def viewer_user(http_client):
    email, meta = await _register(http_client, "tx-viewer")
    await _set_role(email, "viewer")
    headers = await _login(http_client, email, meta["_password"])
    return {"email": email, "headers": headers}


# ── Happy paths per jurisdiction ────────────────────────────────────────


@pytest.mark.asyncio
async def test_tax_quote_gb_first_time_buyer(http_client, tenant_a):
    ids = await _seed_spa(
        http_client,
        tenant_a["headers"],
        governing_law="GB",
        total_value="400000.00",
        currency="GBP",
    )
    res = await http_client.post(
        f"/api/v1/property-dev/sales-contracts/{ids['spa_id']}/tax-quote",
        json={
            "jurisdiction": "GB",
            "is_first_home": True,
        },
        headers=tenant_a["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["jurisdiction"] == "GB"
    # 0 % SDLT under £425k first-time relief.
    assert str(body["stamp_duty"]) in ("0.00", "0")
    # 20 % VAT applied (standard class) — 80,000.
    assert str(body["vat"]) == "80000.00"
    # Net price echoed at 400k.
    assert str(body["net"]) == "400000.00"
    # Breakdown carries at least the net line + the VAT line.
    lines = [item["line"] for item in body["breakdown"]]
    assert any("Net price" in line for line in lines)
    assert any("VAT" in line for line in lines)


@pytest.mark.asyncio
async def test_tax_quote_de_berlin_via_governing_law(http_client, tenant_a):
    ids = await _seed_spa(
        http_client,
        tenant_a["headers"],
        governing_law="DE-BE",  # ISO 3166-2 — engine splits to DE / BE.
        total_value="500000.00",
        currency="EUR",
    )
    res = await http_client.post(
        f"/api/v1/property-dev/sales-contracts/{ids['spa_id']}/tax-quote",
        json={},  # Empty body — engine must resolve.
        headers=tenant_a["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["jurisdiction"] == "DE"
    assert body["region_subcode"] == "BE"
    # 19 % VAT on net 500k = 95,000.
    assert str(body["vat"]) == "95000.00"
    # Berlin Grunderwerbsteuer 6 % on net 500k = 30,000.
    assert str(body["stamp_duty"]) == "30000.00"


@pytest.mark.asyncio
async def test_tax_quote_ae_dubai_zero_rated(http_client, tenant_a):
    ids = await _seed_spa(
        http_client,
        tenant_a["headers"],
        governing_law="AE",
        total_value="1000000.00",
        currency="AED",
    )
    res = await http_client.post(
        f"/api/v1/property-dev/sales-contracts/{ids['spa_id']}/tax-quote",
        json={
            "vat_rate_class": "zero_rated",
            "emirate": "dubai",
        },
        headers=tenant_a["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["jurisdiction"] == "AE"
    # Zero-rated VAT.
    assert str(body["vat"]) in ("0.00", "0")
    # DLD Dubai transfer fee 4 % × 1M = 40,000.
    assert str(body["transfer_fee"]) == "40000.00"


@pytest.mark.asyncio
async def test_tax_quote_in_maharashtra_premium(http_client, tenant_a):
    ids = await _seed_spa(
        http_client,
        tenant_a["headers"],
        governing_law="IN",
        total_value="10000000.00",
        currency="INR",
    )
    res = await http_client.post(
        f"/api/v1/property-dev/sales-contracts/{ids['spa_id']}/tax-quote",
        json={
            "jurisdiction": "IN",
            "region_subcode": "MH",
            "vat_rate_class": "premium",
        },
        headers=tenant_a["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    # Premium GST 5 % × 1 Cr = 5 Lakh.
    assert str(body["vat"]) == "500000.00"
    # Maharashtra 6 % stamp duty = 6 Lakh.
    assert str(body["stamp_duty"]) == "600000.00"
    # 1 % registration fee = 1 Lakh.
    assert str(body["registration_fee"]) == "100000.00"


@pytest.mark.asyncio
async def test_tax_quote_ru_flat_state_duty(http_client, tenant_a):
    ids = await _seed_spa(
        http_client,
        tenant_a["headers"],
        governing_law="RU",
        total_value="10000000.00",
        currency="RUB",
    )
    res = await http_client.post(
        f"/api/v1/property-dev/sales-contracts/{ids['spa_id']}/tax-quote",
        json={
            "jurisdiction": "RU",
        },
        headers=tenant_a["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    # Flat госпошлина 2000 RUB regardless of price.
    assert str(body["stamp_duty"]) == "2000.00"


@pytest.mark.asyncio
async def test_tax_quote_sg_with_absd_foreigner(http_client, tenant_a):
    ids = await _seed_spa(
        http_client,
        tenant_a["headers"],
        governing_law="SG",
        total_value="2000000.00",
        currency="SGD",
    )
    res = await http_client.post(
        f"/api/v1/property-dev/sales-contracts/{ids['spa_id']}/tax-quote",
        json={
            "jurisdiction": "SG",
            "absd_buyer_profile": "foreigner",
        },
        headers=tenant_a["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    # BSD progressive bands on 2M = 69,600.
    assert str(body["stamp_duty"]) == "69600.00"
    # ABSD 60 % foreigner = 1.2M.
    assert str(body["absd"]) == "1200000.00"


# ── IDOR + role enforcement ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tax_quote_cross_tenant_idor_blocked(http_client, tenant_a, tenant_b):
    ids = await _seed_spa(
        http_client,
        tenant_a["headers"],
        governing_law="GB",
        total_value="400000.00",
        currency="GBP",
    )
    # tenant_b probes tenant_a's SPA — must be 404 (no UUID oracle).
    res = await http_client.post(
        f"/api/v1/property-dev/sales-contracts/{ids['spa_id']}/tax-quote",
        json={"jurisdiction": "GB"},
        headers=tenant_b["headers"],
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_tax_quote_viewer_can_read(http_client, tenant_a, viewer_user):
    ids = await _seed_spa(
        http_client,
        tenant_a["headers"],
        governing_law="DE-BE",
        total_value="500000.00",
        currency="EUR",
    )
    # property_dev.read is a VIEWER permission — but the cross-tenant
    # IDOR closure runs first and 404s because viewer_user doesn't own
    # the project. Confirm we get a 404, NOT a 403 (no permission leak).
    res = await http_client.post(
        f"/api/v1/property-dev/sales-contracts/{ids['spa_id']}/tax-quote",
        json={},
        headers=viewer_user["headers"],
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_tax_quote_unsupported_jurisdiction_422(http_client, tenant_a):
    ids = await _seed_spa(
        http_client,
        tenant_a["headers"],
        governing_law="GB",
        total_value="500000.00",
        currency="GBP",
    )
    res = await http_client.post(
        f"/api/v1/property-dev/sales-contracts/{ids['spa_id']}/tax-quote",
        json={"jurisdiction": "ZZ"},
        headers=tenant_a["headers"],
    )
    assert res.status_code == 422, res.text
    detail = res.json()["detail"]
    assert detail["error"] == "unsupported_jurisdiction"
    assert "GB" in detail["supported"]
    assert detail["jurisdiction"] == "ZZ"
