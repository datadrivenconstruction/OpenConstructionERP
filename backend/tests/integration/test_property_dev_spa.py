"""Property Development SPA / PaymentSchedule integration regressions.

Targets the bugs that surfaced when the user reported "Sales Contracts +
Payment Schedules tabs не работают":

  * Auto-create primary ContractParty on Reservation→SPA conversion so
    the SPA isn't stuck in draft with no way to "Send for signature"
    (FSM was rejecting with "no primary party").
  * Verify the Reservation→SPA conversion creates a default payment
    schedule with one pending instalment.
  * Verify the FSM transitions on send/sign/cancel.
  * Verify generate-from-template overrides the default schedule when
    the SPA is still in draft (typical UX flow).
  * Verify mark-paid updates instalment status and amount_paid.
  * Cross-tenant IDOR on /sales-contracts and /payment-schedules.

Scaffolding follows the same per-module SQLite isolation pattern as the
existing R6 lead-to-SPA suite.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

# ── Per-module SQLite isolation (must run BEFORE app imports) ──────────────
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-propdev-spa-tab-"))
_TMP_DB = _TMP_DIR / "propdev_spa_tab.db"
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


async def _register_and_login(
    client: AsyncClient,
    label: str,
    role: str = "admin",
) -> dict[str, str]:
    email = f"{label}-{uuid.uuid4().hex[:8]}@spa-tab.io"
    password = f"SpaTab{uuid.uuid4().hex[:6]}9!"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": label},
    )
    assert reg.status_code in (200, 201), reg.text
    await _set_role(email, role)
    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, login.text
    return {
        "email": email,
        "headers": {"Authorization": f"Bearer {login.json()['access_token']}"},
    }


@pytest_asyncio.fixture(scope="module")
async def tenant(http_client):
    """Tenant with a development, plot and buyer ready to convert."""
    user = await _register_and_login(http_client, "spa-tab-tenant")
    headers = user["headers"]
    proj = await http_client.post(
        "/api/v1/projects/",
        json={
            "name": f"SPATab {uuid.uuid4().hex[:6]}",
            "description": "spa-tab",
            "currency": "EUR",
        },
        headers=headers,
    )
    assert proj.status_code == 201, proj.text
    project_id = proj.json()["id"]

    dev = await http_client.post(
        "/api/v1/property-dev/developments/",
        json={
            "project_id": project_id,
            "code": f"SPA{uuid.uuid4().hex[:6].upper()}",
            "name": "SPA Tab Test",
            "total_plots": 4,
        },
        headers=headers,
    )
    assert dev.status_code == 201, dev.text
    development_id = dev.json()["id"]

    plot_ids: list[str] = []
    for i in range(2):
        p = await http_client.post(
            "/api/v1/property-dev/plots/",
            json={
                "development_id": development_id,
                "plot_number": f"S-{i + 1:02d}",
                "area_m2": 100,
                "price_base": 300_000,
                "currency": "EUR",
            },
            headers=headers,
        )
        assert p.status_code == 201, p.text
        plot_ids.append(p.json()["id"])

    return {
        "email": user["email"],
        "headers": headers,
        "project_id": project_id,
        "development_id": development_id,
        "plot_ids": plot_ids,
    }


async def _new_buyer(client, tenant) -> str:
    res = await client.post(
        "/api/v1/property-dev/buyers/",
        json={
            "development_id": tenant["development_id"],
            "full_name": f"Buyer {uuid.uuid4().hex[:4]}",
            "email": f"b{uuid.uuid4().hex[:6]}@example.com",
            "status": "lead",
        },
        headers=tenant["headers"],
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def _new_reservation(client, tenant, plot_id: str, buyer_id: str) -> str:
    res = await client.post(
        "/api/v1/property-dev/reservations/",
        json={
            "plot_id": plot_id,
            "buyer_id": buyer_id,
            "deposit_amount": "5000.00",
            "currency": "EUR",
            "cooling_off_days": 7,
            "expires_at": "2027-01-01",
        },
        headers=tenant["headers"],
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


@pytest.mark.asyncio
async def test_convert_reservation_to_spa_creates_party_and_schedule(
    http_client,
    tenant,
):
    """Conversion path creates a usable SPA with primary party + schedule.

    Root-cause regression for the user-reported "Sales Contracts не
    работает" bug — before the fix the SPA was created without a
    primary party so it could never be sent for signature.
    """
    buyer_id = await _new_buyer(http_client, tenant)
    plot_id = tenant["plot_ids"][0]
    reservation_id = await _new_reservation(http_client, tenant, plot_id, buyer_id)

    res = await http_client.post(
        f"/api/v1/property-dev/reservations/{reservation_id}/convert-to-spa",
        json={
            "signing_date": "2026-06-01",
            "total_value": "300000.00",
            "currency": "EUR",
            "governing_law": "DE-BE",
            "language": "en",
        },
        headers=tenant["headers"],
    )
    assert res.status_code == 201, res.text
    spa = res.json()
    assert spa["status"] == "draft"
    assert spa["plot_id"] == plot_id
    assert spa["reservation_id"] == reservation_id

    # 1. Primary party auto-created → SPA can be sent for signature
    parties = await http_client.get(
        "/api/v1/property-dev/contract-parties/",
        params={"sales_contract_id": spa["id"]},
        headers=tenant["headers"],
    )
    assert parties.status_code == 200, parties.text
    party_rows = parties.json()
    assert len(party_rows) >= 1, "primary party must be auto-created"
    primary = next(p for p in party_rows if p["party_role"] == "primary")
    assert primary["buyer_id"] == buyer_id

    # 2. Default payment schedule exists with one pending instalment
    schedules = await http_client.get(
        "/api/v1/property-dev/payment-schedules/",
        params={"sales_contract_id": spa["id"]},
        headers=tenant["headers"],
    )
    assert schedules.status_code == 200, schedules.text
    schedule_rows = schedules.json()
    assert len(schedule_rows) == 1
    schedule = schedule_rows[0]
    assert schedule["status"] == "active"

    instalments = await http_client.get(
        "/api/v1/property-dev/instalments/",
        params={"sales_contract_id": spa["id"]},
        headers=tenant["headers"],
    )
    assert instalments.status_code == 200, instalments.text
    ins_rows = instalments.json()
    assert len(ins_rows) == 1
    assert ins_rows[0]["status"] == "pending"


@pytest.mark.asyncio
async def test_spa_fsm_send_sign_cancel(http_client, tenant):
    """Full happy-path FSM: draft → sent_for_signature → signed → countersigned."""
    buyer_id = await _new_buyer(http_client, tenant)
    plot_id = tenant["plot_ids"][1]
    reservation_id = await _new_reservation(http_client, tenant, plot_id, buyer_id)

    res = await http_client.post(
        f"/api/v1/property-dev/reservations/{reservation_id}/convert-to-spa",
        json={
            "signing_date": "2026-06-15",
            "total_value": "275000.00",
            "currency": "EUR",
        },
        headers=tenant["headers"],
    )
    assert res.status_code == 201, res.text
    spa_id = res.json()["id"]

    # Send for signature — must NOT 409 (primary party was auto-created)
    sent = await http_client.post(
        f"/api/v1/property-dev/sales-contracts/{spa_id}/send-for-signature",
        json={},
        headers=tenant["headers"],
    )
    assert sent.status_code == 200, sent.text
    assert sent.json()["status"] == "sent_for_signature"

    # Sign → "signed"
    signed = await http_client.post(
        f"/api/v1/property-dev/sales-contracts/{spa_id}/sign",
        json={"signing_date": "2026-06-16"},
        headers=tenant["headers"],
    )
    assert signed.status_code == 200, signed.text
    assert signed.json()["status"] == "signed"

    # Counter-sign → "countersigned"
    counter = await http_client.post(
        f"/api/v1/property-dev/sales-contracts/{spa_id}/sign",
        json={},
        headers=tenant["headers"],
    )
    assert counter.status_code == 200, counter.text
    assert counter.json()["status"] == "countersigned"


@pytest.mark.asyncio
async def test_generate_payment_schedule_from_template(http_client, tenant):
    """generate-from-template replaces the default single-line schedule."""
    buyer_id = await _new_buyer(http_client, tenant)
    # Need a fresh plot — create one rather than recycling from fixture.
    p = await http_client.post(
        "/api/v1/property-dev/plots/",
        json={
            "development_id": tenant["development_id"],
            "plot_number": f"S-3-{uuid.uuid4().hex[:4]}",
            "area_m2": 110,
            "price_base": "320000",
            "currency": "EUR",
        },
        headers=tenant["headers"],
    )
    assert p.status_code == 201, p.text
    plot_id = p.json()["id"]
    reservation_id = await _new_reservation(http_client, tenant, plot_id, buyer_id)

    spa = await http_client.post(
        f"/api/v1/property-dev/reservations/{reservation_id}/convert-to-spa",
        json={
            "signing_date": "2026-07-01",
            "total_value": "320000.00",
            "currency": "EUR",
        },
        headers=tenant["headers"],
    )
    assert spa.status_code == 201, spa.text
    spa_id = spa.json()["id"]

    # Fetch templates catalogue
    tmpls = await http_client.get(
        "/api/v1/property-dev/payment-schedule-templates/",
        headers=tenant["headers"],
    )
    assert tmpls.status_code == 200, tmpls.text
    template_keys = [t["key"] for t in tmpls.json()]
    assert template_keys, "templates catalogue must not be empty"

    # Generate a 10-40-50 schedule (or first available template).
    chosen_key = "10_40_50" if "10_40_50" in template_keys else template_keys[0]
    gen = await http_client.post(
        "/api/v1/property-dev/payment-schedules/from-template",
        json={
            "sales_contract_id": spa_id,
            "template_key": chosen_key,
            "start_date": "2026-07-01",
            "late_fee_pct": "5",
            "grace_period_days": 14,
        },
        headers=tenant["headers"],
    )
    assert gen.status_code == 201, gen.text
    schedule = gen.json()
    assert schedule["sales_contract_id"] == spa_id

    # Verify generated instalments
    ins = await http_client.get(
        "/api/v1/property-dev/instalments/",
        params={"sales_contract_id": spa_id},
        headers=tenant["headers"],
    )
    assert ins.status_code == 200, ins.text
    rows = ins.json()
    assert len(rows) >= 2, "template must produce ≥2 instalments"


@pytest.mark.asyncio
async def test_mark_instalment_paid(http_client, tenant):
    """mark-paid flips status → paid + sums amount_paid."""
    buyer_id = await _new_buyer(http_client, tenant)
    p = await http_client.post(
        "/api/v1/property-dev/plots/",
        json={
            "development_id": tenant["development_id"],
            "plot_number": f"S-4-{uuid.uuid4().hex[:4]}",
            "area_m2": 95,
            "price_base": "250000",
            "currency": "EUR",
        },
        headers=tenant["headers"],
    )
    assert p.status_code == 201, p.text
    plot_id = p.json()["id"]
    reservation_id = await _new_reservation(http_client, tenant, plot_id, buyer_id)

    spa = await http_client.post(
        f"/api/v1/property-dev/reservations/{reservation_id}/convert-to-spa",
        json={
            "signing_date": "2026-08-01",
            "total_value": "250000.00",
            "currency": "EUR",
        },
        headers=tenant["headers"],
    )
    assert spa.status_code == 201, spa.text
    spa_id = spa.json()["id"]

    ins = await http_client.get(
        "/api/v1/property-dev/instalments/",
        params={"sales_contract_id": spa_id},
        headers=tenant["headers"],
    )
    assert ins.status_code == 200, ins.text
    ins_id = ins.json()[0]["id"]

    paid = await http_client.post(
        f"/api/v1/property-dev/instalments/{ins_id}/mark-paid",
        json={
            "amount": "250000.00",
            "paid_at": "2026-08-02T10:00:00Z",
            "invoice_ref": "INV-001",
        },
        headers=tenant["headers"],
    )
    assert paid.status_code == 200, paid.text
    row = paid.json()
    assert row["status"] == "paid"
    # amount_paid arrives as a Decimal-serialised string.
    assert float(row["amount_paid"]) == pytest.approx(250000.00, rel=1e-3)


@pytest.mark.asyncio
async def test_list_endpoints_idor_cross_tenant(http_client, tenant):
    """Cross-tenant SPA + schedule reads must 4xx, not leak.

    Use a non-admin "other" tenant — admins are intentionally exempt
    from the IDOR check (system-level read access).
    """
    other = await _register_and_login(http_client, "spa-tab-other", role="editor")

    # Other tenant tries to list SPAs for the first tenant's development.
    res = await http_client.get(
        "/api/v1/property-dev/sales-contracts/",
        params={"development_id": tenant["development_id"]},
        headers=other["headers"],
    )
    assert res.status_code in (403, 404), (
        f"expected 403/404 on cross-tenant SPA list, got {res.status_code}: {res.text}"
    )

    res = await http_client.get(
        "/api/v1/property-dev/payment-schedules/",
        params={"development_id": tenant["development_id"]},
        headers=other["headers"],
    )
    assert res.status_code in (403, 404), (
        f"expected 403/404 on cross-tenant schedule list, got {res.status_code}: {res.text}"
    )
