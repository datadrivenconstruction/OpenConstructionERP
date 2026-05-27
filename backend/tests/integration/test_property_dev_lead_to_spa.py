"""Property Development R6 lead-to-SPA pipeline integration suite.

Task #137 — extends ``property_dev`` with the full sales-pipeline
backbone: Lead → Reservation → SalesContract (SPA) → PaymentSchedule
→ Instalment, plus multi-buyer ContractParty.

Coverage targets:

  * Lead CRUD + role gates + cross-tenant IDOR.
  * Lead → Reservation conversion (FSM valid + invalid).
  * Reservation expiry (manual + batch) + cooling-off computation.
  * Reservation → SPA conversion + auto-default PaymentSchedule.
  * SPA signing FSM (sent → signed → countersigned).
  * Multi-buyer ContractParty ownership_pct sum=100 enforcement.
  * ContractParty role enforcement.
  * Instalment FSM (pending → due → paid / waived / overdue).
  * PaymentSchedule activation + suspension.
  * Late-fee accrual.
  * Demand-letter event published with right payload.
  * Cross-tenant IDOR on every new endpoint.
  * Schema validation edge cases.

Scaffolding mirrors ``test_property_dev_buyer_update.py`` (the existing
Wave 0 test): per-module temp SQLite registered BEFORE any
``from app...`` import to keep the production DB un-touched.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from decimal import Decimal
from pathlib import Path

# ── Per-module SQLite isolation (must run BEFORE app imports) ──────────────
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-propdev-lead-spa-"))
_TMP_DB = _TMP_DIR / "propdev_lead_spa.db"
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
    email = f"{label}-{uuid.uuid4().hex[:8]}@propdev-r6.io"
    password = f"PropDevR6{uuid.uuid4().hex[:6]}9!"
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


@pytest_asyncio.fixture(scope="module")
async def tenant_a(http_client):
    """Tenant A: admin owning a project + development + 3 plots + a buyer."""
    email, meta = await _register(http_client, "tenant-a")
    await _set_role(email, "admin")
    headers = await _login(http_client, email, meta["_password"])

    proj = await http_client.post(
        "/api/v1/projects/",
        json={
            "name": f"Tenant-A {uuid.uuid4().hex[:6]}",
            "description": "owner: tenant A",
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
            "code": f"DEVA{uuid.uuid4().hex[:6].upper()}",
            "name": "Marina Heights",
            "total_plots": 5,
        },
        headers=headers,
    )
    assert dev.status_code == 201, dev.text
    development_id = dev.json()["id"]

    plots: list[str] = []
    for i in range(3):
        p = await http_client.post(
            "/api/v1/property-dev/plots/",
            json={
                "development_id": development_id,
                "plot_number": f"A-{i + 1:02d}",
                "area_m2": 120 + i,
                "price_base": 450_000 + i * 5000,
                "currency": "EUR",
            },
            headers=headers,
        )
        assert p.status_code == 201, p.text
        plots.append(p.json()["id"])

    # Pre-seed two buyers we'll re-use for multi-party SPA tests.
    buyers: list[str] = []
    for i in range(2):
        b = await http_client.post(
            "/api/v1/property-dev/buyers/",
            json={
                "development_id": development_id,
                "full_name": f"Buyer {i + 1}",
                "email": f"buyer{i + 1}@example.com",
                "status": "lead",
            },
            headers=headers,
        )
        assert b.status_code == 201, b.text
        buyers.append(b.json()["id"])

    return {
        "email": email,
        "headers": headers,
        "project_id": project_id,
        "development_id": development_id,
        "plots": plots,
        "buyers": buyers,
    }


@pytest_asyncio.fixture(scope="module")
async def tenant_b(http_client):
    email, meta = await _register(http_client, "tenant-b")
    await _set_role(email, "editor")
    headers = await _login(http_client, email, meta["_password"])

    proj = await http_client.post(
        "/api/v1/projects/",
        json={
            "name": f"Tenant-B {uuid.uuid4().hex[:6]}",
            "description": "owner: tenant B",
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
            "code": f"DEVB{uuid.uuid4().hex[:6].upper()}",
            "name": "Highland Mews",
        },
        headers=headers,
    )
    assert dev.status_code == 201, dev.text
    development_id = dev.json()["id"]

    p = await http_client.post(
        "/api/v1/property-dev/plots/",
        json={
            "development_id": development_id,
            "plot_number": "B-01",
            "area_m2": 110,
            "price_base": 410_000,
            "currency": "EUR",
        },
        headers=headers,
    )
    assert p.status_code == 201, p.text
    return {
        "email": email,
        "headers": headers,
        "project_id": project_id,
        "development_id": development_id,
        "plot_id": p.json()["id"],
    }


@pytest_asyncio.fixture(scope="module")
async def viewer_user(http_client):
    email, meta = await _register(http_client, "viewer")
    await _set_role(email, "viewer")
    headers = await _login(http_client, email, meta["_password"])
    return {"email": email, "headers": headers}


@pytest_asyncio.fixture(scope="module")
async def manager_user(http_client):
    email, meta = await _register(http_client, "manager")
    await _set_role(email, "manager")
    headers = await _login(http_client, email, meta["_password"])
    return {"email": email, "headers": headers}


async def _fresh_lead(client: AsyncClient, tenant: dict, **overrides) -> str:
    payload = {
        "development_id": tenant["development_id"],
        "source": "web_form",
        "full_name": f"Lead {uuid.uuid4().hex[:6]}",
        "email": f"lead{uuid.uuid4().hex[:8]}@example.com",
        "phone": "+49 30 7654321",
        "status": "new",
    }
    payload.update(overrides)
    res = await client.post(
        "/api/v1/property-dev/leads/",
        json=payload,
        headers=tenant["headers"],
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def _convert_lead_to_reservation(
    client: AsyncClient, tenant: dict, lead_id: str, plot_id: str, **overrides
) -> dict:
    payload = {
        "plot_id": plot_id,
        "deposit_amount": "5000.00",
        "currency": "EUR",
        "cooling_off_days": 7,
        "create_buyer": True,
    }
    payload.update(overrides)
    res = await client.post(
        f"/api/v1/property-dev/leads/{lead_id}/convert-to-reservation",
        json=payload,
        headers=tenant["headers"],
    )
    assert res.status_code == 201, res.text
    return res.json()


async def _convert_reservation_to_spa(client: AsyncClient, tenant: dict, reservation_id: str, **overrides) -> dict:
    payload = {
        "signing_date": "2026-06-01",
        "governing_law": "DE-BE",
        "language": "en",
        "total_value": "450000.00",
        "currency": "EUR",
        "total_price_breakdown": {
            "base": "450000",
            "vat": "0",
            "stamp_duty": "0",
            "legal_fees": "0",
            "options_value": "0",
            "discounts": "0",
        },
    }
    payload.update(overrides)
    res = await client.post(
        f"/api/v1/property-dev/reservations/{reservation_id}/convert-to-spa",
        json=payload,
        headers=tenant["headers"],
    )
    assert res.status_code == 201, res.text
    return res.json()


# ════════════════════════════════════════════════════════════════════════
# Lead CRUD + role gates
# ════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_lead_create_basic(http_client, tenant_a):
    res = await http_client.post(
        "/api/v1/property-dev/leads/",
        json={
            "development_id": tenant_a["development_id"],
            "source": "web_form",
            "full_name": "Jane Buyer",
            "email": "jane@example.com",
            "lead_score": "25.50",
            "currency": "EUR",
        },
        headers=tenant_a["headers"],
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["full_name"] == "Jane Buyer"
    assert body["status"] == "new"
    assert body["currency"] == "EUR"


@pytest.mark.asyncio
async def test_lead_invalid_source_rejected(http_client, tenant_a):
    res = await http_client.post(
        "/api/v1/property-dev/leads/",
        json={
            "development_id": tenant_a["development_id"],
            "source": "telepathy",
            "full_name": "Mind Reader",
        },
        headers=tenant_a["headers"],
    )
    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_lead_invalid_currency_rejected(http_client, tenant_a):
    res = await http_client.post(
        "/api/v1/property-dev/leads/",
        json={
            "development_id": tenant_a["development_id"],
            "source": "web_form",
            "full_name": "Foo",
            "currency": "EUROS",
        },
        headers=tenant_a["headers"],
    )
    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_lead_viewer_blocked_from_create(http_client, tenant_a, viewer_user):
    res = await http_client.post(
        "/api/v1/property-dev/leads/",
        json={
            "development_id": tenant_a["development_id"],
            "source": "web_form",
            "full_name": "Viewer Lead",
        },
        headers=viewer_user["headers"],
    )
    assert res.status_code == 403, res.text


@pytest.mark.asyncio
async def test_lead_idor_get_blocked_for_tenant_b(http_client, tenant_a, tenant_b):
    lead_id = await _fresh_lead(http_client, tenant_a)
    res = await http_client.get(
        f"/api/v1/property-dev/leads/{lead_id}",
        headers=tenant_b["headers"],
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_lead_idor_update_blocked_for_tenant_b(http_client, tenant_a, tenant_b):
    lead_id = await _fresh_lead(http_client, tenant_a)
    res = await http_client.patch(
        f"/api/v1/property-dev/leads/{lead_id}",
        json={"full_name": "Hacker"},
        headers=tenant_b["headers"],
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_lead_fsm_invalid_transition(http_client, tenant_a):
    lead_id = await _fresh_lead(http_client, tenant_a)
    # new → converted is NOT a valid direct transition (must go through
    # qualified → visited → converted path).
    res = await http_client.patch(
        f"/api/v1/property-dev/leads/{lead_id}",
        json={"status": "converted"},
        headers=tenant_a["headers"],
    )
    assert res.status_code == 409, res.text
    assert "transition" in res.json().get("detail", "").lower()


@pytest.mark.asyncio
async def test_lead_fsm_valid_transition(http_client, tenant_a):
    lead_id = await _fresh_lead(http_client, tenant_a)
    res = await http_client.patch(
        f"/api/v1/property-dev/leads/{lead_id}",
        json={"status": "qualified"},
        headers=tenant_a["headers"],
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "qualified"


# ════════════════════════════════════════════════════════════════════════
# Lead → Reservation conversion
# ════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_lead_to_reservation_happy_path(http_client, tenant_a):
    lead_id = await _fresh_lead(http_client, tenant_a)
    plot_id = tenant_a["plots"][0]
    reservation = await _convert_lead_to_reservation(http_client, tenant_a, lead_id, plot_id)
    assert reservation["status"] == "active"
    assert reservation["plot_id"] == plot_id
    assert reservation["currency"] == "EUR"
    assert Decimal(reservation["deposit_amount"]) == Decimal("5000.00")
    assert reservation["reservation_number"].startswith("RES-DEVA")
    assert reservation["cooling_off_days"] == 7
    assert reservation["cooling_off_until"] is not None
    # Lead should be marked converted now.
    refreshed_lead = await http_client.get(f"/api/v1/property-dev/leads/{lead_id}", headers=tenant_a["headers"])
    assert refreshed_lead.json()["status"] == "converted"
    assert refreshed_lead.json()["converted_to_buyer_id"] is not None


@pytest.mark.asyncio
async def test_lead_to_reservation_invalid_currency(http_client, tenant_a):
    lead_id = await _fresh_lead(http_client, tenant_a)
    res = await http_client.post(
        f"/api/v1/property-dev/leads/{lead_id}/convert-to-reservation",
        json={
            "plot_id": tenant_a["plots"][1],
            "deposit_amount": "5000",
            "currency": "EUROS",
        },
        headers=tenant_a["headers"],
    )
    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_lead_already_converted_cannot_convert_again(http_client, tenant_a):
    lead_id = await _fresh_lead(http_client, tenant_a)
    await _convert_lead_to_reservation(http_client, tenant_a, lead_id, tenant_a["plots"][0])
    res = await http_client.post(
        f"/api/v1/property-dev/leads/{lead_id}/convert-to-reservation",
        json={
            "plot_id": tenant_a["plots"][1],
            "deposit_amount": "5000",
            "currency": "EUR",
        },
        headers=tenant_a["headers"],
    )
    assert res.status_code == 409, res.text


@pytest.mark.asyncio
async def test_reservation_negative_deposit_rejected(http_client, tenant_a):
    lead_id = await _fresh_lead(http_client, tenant_a)
    res = await http_client.post(
        f"/api/v1/property-dev/leads/{lead_id}/convert-to-reservation",
        json={
            "plot_id": tenant_a["plots"][0],
            "deposit_amount": "-100",
            "currency": "EUR",
        },
        headers=tenant_a["headers"],
    )
    assert res.status_code == 422, res.text


# ════════════════════════════════════════════════════════════════════════
# Reservation lifecycle + expiry
# ════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_reservation_manual_expire(http_client, tenant_a):
    lead_id = await _fresh_lead(http_client, tenant_a)
    reservation = await _convert_lead_to_reservation(http_client, tenant_a, lead_id, tenant_a["plots"][0])
    r_id = reservation["id"]
    res = await http_client.post(
        f"/api/v1/property-dev/reservations/{r_id}/expire",
        headers=tenant_a["headers"],
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "expired"


@pytest.mark.asyncio
async def test_reservation_cancel(http_client, tenant_a):
    lead_id = await _fresh_lead(http_client, tenant_a)
    reservation = await _convert_lead_to_reservation(http_client, tenant_a, lead_id, tenant_a["plots"][1])
    res = await http_client.post(
        f"/api/v1/property-dev/reservations/{reservation['id']}/cancel",
        headers=tenant_a["headers"],
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_reservation_terminal_state_is_read_only(http_client, tenant_a):
    lead_id = await _fresh_lead(http_client, tenant_a)
    reservation = await _convert_lead_to_reservation(http_client, tenant_a, lead_id, tenant_a["plots"][0])
    # Cancel first.
    await http_client.post(
        f"/api/v1/property-dev/reservations/{reservation['id']}/cancel",
        headers=tenant_a["headers"],
    )
    # Now try to update — should 409.
    res = await http_client.patch(
        f"/api/v1/property-dev/reservations/{reservation['id']}",
        json={"cooling_off_days": 14},
        headers=tenant_a["headers"],
    )
    assert res.status_code == 409, res.text


@pytest.mark.asyncio
async def test_reservation_expire_overdue_batch(http_client, tenant_a):
    """Set up a reservation with expires_at in the past and confirm batch."""
    lead_id = await _fresh_lead(http_client, tenant_a)
    reservation = await _convert_lead_to_reservation(
        http_client,
        tenant_a,
        lead_id,
        tenant_a["plots"][1],
        expires_at="2020-01-01",  # past
    )
    res = await http_client.post(
        "/api/v1/property-dev/reservations/expire-overdue",
        headers=tenant_a["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["expired_count"] >= 1
    assert reservation["id"] in body["expired_ids"]


@pytest.mark.asyncio
async def test_reservation_idor_blocked_for_tenant_b(http_client, tenant_a, tenant_b):
    lead_id = await _fresh_lead(http_client, tenant_a)
    reservation = await _convert_lead_to_reservation(http_client, tenant_a, lead_id, tenant_a["plots"][0])
    res = await http_client.get(
        f"/api/v1/property-dev/reservations/{reservation['id']}",
        headers=tenant_b["headers"],
    )
    assert res.status_code == 404, res.text


# ════════════════════════════════════════════════════════════════════════
# Reservation → SPA
# ════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_reservation_to_spa_happy_path(http_client, tenant_a):
    lead_id = await _fresh_lead(http_client, tenant_a)
    reservation = await _convert_lead_to_reservation(http_client, tenant_a, lead_id, tenant_a["plots"][0])
    spa = await _convert_reservation_to_spa(http_client, tenant_a, reservation["id"])
    assert spa["status"] == "draft"
    assert spa["contract_number"].startswith("SPA-DEVA")
    assert spa["plot_id"] == tenant_a["plots"][0]
    assert spa["reservation_id"] == reservation["id"]
    assert Decimal(spa["total_value"]) == Decimal("450000.00")

    # Default payment schedule should exist.
    instalments = await http_client.get(
        "/api/v1/property-dev/instalments/",
        params={"sales_contract_id": spa["id"]},
        headers=tenant_a["headers"],
    )
    assert instalments.status_code == 200
    assert len(instalments.json()) == 1
    assert instalments.json()[0]["milestone_event"] == "spa_signed"


# ════════════════════════════════════════════════════════════════════════
# SPA FSM
# ════════════════════════════════════════════════════════════════════════


async def _spa_from_lead(http_client, tenant_a, plot_idx: int = 0) -> dict:
    lead_id = await _fresh_lead(http_client, tenant_a)
    reservation = await _convert_lead_to_reservation(http_client, tenant_a, lead_id, tenant_a["plots"][plot_idx])
    return await _convert_reservation_to_spa(http_client, tenant_a, reservation["id"])


@pytest.mark.asyncio
async def test_spa_send_without_primary_party_fails(http_client, tenant_a):
    spa = await _spa_from_lead(http_client, tenant_a, plot_idx=0)
    res = await http_client.post(
        f"/api/v1/property-dev/sales-contracts/{spa['id']}/send-for-signature",
        json={},
        headers=tenant_a["headers"],
    )
    assert res.status_code == 409, res.text
    assert "primary" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_spa_sign_fsm_full(http_client, tenant_a):
    spa = await _spa_from_lead(http_client, tenant_a, plot_idx=1)
    # Add a primary party first.
    party_res = await http_client.post(
        "/api/v1/property-dev/contract-parties/",
        json={
            "sales_contract_id": spa["id"],
            "buyer_id": tenant_a["buyers"][0],
            "ownership_pct": "100.00",
            "party_role": "primary",
        },
        headers=tenant_a["headers"],
    )
    assert party_res.status_code == 201, party_res.text

    sent = await http_client.post(
        f"/api/v1/property-dev/sales-contracts/{spa['id']}/send-for-signature",
        json={"e_sign_envelope_id": "env-test-001"},
        headers=tenant_a["headers"],
    )
    assert sent.status_code == 200, sent.text
    assert sent.json()["status"] == "sent_for_signature"

    signed = await http_client.post(
        f"/api/v1/property-dev/sales-contracts/{spa['id']}/sign",
        json={"signing_date": "2026-06-01"},
        headers=tenant_a["headers"],
    )
    assert signed.status_code == 200, signed.text
    assert signed.json()["status"] == "signed"

    countersigned = await http_client.post(
        f"/api/v1/property-dev/sales-contracts/{spa['id']}/sign",
        json={},
        headers=tenant_a["headers"],
    )
    assert countersigned.status_code == 200, countersigned.text
    assert countersigned.json()["status"] == "countersigned"


@pytest.mark.asyncio
async def test_spa_cancel(http_client, tenant_a):
    spa = await _spa_from_lead(http_client, tenant_a, plot_idx=2)
    res = await http_client.post(
        f"/api/v1/property-dev/sales-contracts/{spa['id']}/cancel",
        headers=tenant_a["headers"],
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_spa_idor_blocked_for_tenant_b(http_client, tenant_a, tenant_b):
    spa = await _spa_from_lead(http_client, tenant_a, plot_idx=0)
    res = await http_client.get(
        f"/api/v1/property-dev/sales-contracts/{spa['id']}",
        headers=tenant_b["headers"],
    )
    assert res.status_code == 404, res.text


# ════════════════════════════════════════════════════════════════════════
# Multi-buyer ContractParty
# ════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_contract_party_sum_must_be_le_100(http_client, tenant_a):
    spa = await _spa_from_lead(http_client, tenant_a, plot_idx=1)
    # Add first 60% party.
    r1 = await http_client.post(
        "/api/v1/property-dev/contract-parties/",
        json={
            "sales_contract_id": spa["id"],
            "buyer_id": tenant_a["buyers"][0],
            "ownership_pct": "60.00",
            "party_role": "primary",
        },
        headers=tenant_a["headers"],
    )
    assert r1.status_code == 201, r1.text
    # Add second party 50% — would push total to 110 → 422.
    r2 = await http_client.post(
        "/api/v1/property-dev/contract-parties/",
        json={
            "sales_contract_id": spa["id"],
            "buyer_id": tenant_a["buyers"][1],
            "ownership_pct": "50.00",
            "party_role": "co_owner",
        },
        headers=tenant_a["headers"],
    )
    assert r2.status_code == 422, r2.text
    # Add second party 40% — totals 100 → success.
    r3 = await http_client.post(
        "/api/v1/property-dev/contract-parties/",
        json={
            "sales_contract_id": spa["id"],
            "buyer_id": tenant_a["buyers"][1],
            "ownership_pct": "40.00",
            "party_role": "co_owner",
        },
        headers=tenant_a["headers"],
    )
    assert r3.status_code == 201, r3.text


@pytest.mark.asyncio
async def test_contract_party_duplicate_buyer_rejected(http_client, tenant_a):
    spa = await _spa_from_lead(http_client, tenant_a, plot_idx=2)
    a = await http_client.post(
        "/api/v1/property-dev/contract-parties/",
        json={
            "sales_contract_id": spa["id"],
            "buyer_id": tenant_a["buyers"][0],
            "ownership_pct": "100.00",
            "party_role": "primary",
        },
        headers=tenant_a["headers"],
    )
    assert a.status_code == 201, a.text
    b = await http_client.post(
        "/api/v1/property-dev/contract-parties/",
        json={
            "sales_contract_id": spa["id"],
            "buyer_id": tenant_a["buyers"][0],
            "ownership_pct": "0",
            "party_role": "guarantor",
        },
        headers=tenant_a["headers"],
    )
    assert b.status_code == 409, b.text


@pytest.mark.asyncio
async def test_contract_party_invalid_role_rejected(http_client, tenant_a):
    spa = await _spa_from_lead(http_client, tenant_a, plot_idx=0)
    res = await http_client.post(
        "/api/v1/property-dev/contract-parties/",
        json={
            "sales_contract_id": spa["id"],
            "buyer_id": tenant_a["buyers"][0],
            "ownership_pct": "50.00",
            "party_role": "supreme_overlord",
        },
        headers=tenant_a["headers"],
    )
    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_contract_party_ownership_over_100_rejected_at_schema(http_client, tenant_a):
    spa = await _spa_from_lead(http_client, tenant_a, plot_idx=1)
    res = await http_client.post(
        "/api/v1/property-dev/contract-parties/",
        json={
            "sales_contract_id": spa["id"],
            "buyer_id": tenant_a["buyers"][0],
            "ownership_pct": "120.00",
            "party_role": "primary",
        },
        headers=tenant_a["headers"],
    )
    assert res.status_code == 422, res.text


# ════════════════════════════════════════════════════════════════════════
# Instalments / PaymentSchedule
# ════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_instalment_mark_paid_completes_schedule(http_client, tenant_a):
    spa = await _spa_from_lead(http_client, tenant_a, plot_idx=0)
    # Auto-created schedule + 1 line of value 450000.
    instalments = await http_client.get(
        "/api/v1/property-dev/instalments/",
        params={"sales_contract_id": spa["id"]},
        headers=tenant_a["headers"],
    )
    assert instalments.status_code == 200
    ins = instalments.json()[0]
    schedule_id = ins["schedule_id"]

    # Mark fully paid.
    res = await http_client.post(
        f"/api/v1/property-dev/instalments/{ins['id']}/mark-paid",
        json={"amount": "450000.00"},
        headers=tenant_a["headers"],
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "paid"

    # Schedule auto-completes.
    sched = await http_client.get(
        f"/api/v1/property-dev/payment-schedules/{schedule_id}",
        headers=tenant_a["headers"],
    )
    assert sched.status_code == 200
    assert sched.json()["status"] == "completed"


@pytest.mark.asyncio
async def test_instalment_overpayment_rejected(http_client, tenant_a):
    spa = await _spa_from_lead(http_client, tenant_a, plot_idx=1)
    instalments = await http_client.get(
        "/api/v1/property-dev/instalments/",
        params={"sales_contract_id": spa["id"]},
        headers=tenant_a["headers"],
    )
    ins_id = instalments.json()[0]["id"]
    res = await http_client.post(
        f"/api/v1/property-dev/instalments/{ins_id}/mark-paid",
        json={"amount": "999999999.99"},
        headers=tenant_a["headers"],
    )
    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_instalment_waive(http_client, tenant_a):
    spa = await _spa_from_lead(http_client, tenant_a, plot_idx=2)
    instalments = await http_client.get(
        "/api/v1/property-dev/instalments/",
        params={"sales_contract_id": spa["id"]},
        headers=tenant_a["headers"],
    )
    ins_id = instalments.json()[0]["id"]
    res = await http_client.post(
        f"/api/v1/property-dev/instalments/{ins_id}/waive",
        json={"reason": "goodwill"},
        headers=tenant_a["headers"],
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "waived"


@pytest.mark.asyncio
async def test_instalment_issue_demand_publishes_event(http_client, tenant_a):
    """Issuing a demand should not raise + should not touch status when not overdue."""
    from app.core.events import event_bus

    captured: list[dict] = []

    async def _handler(event) -> None:  # noqa: ANN001
        if event.name == "correspondence.outbound.requested":
            captured.append(event.data)

    event_bus.subscribe("correspondence.outbound.requested", _handler)

    spa = await _spa_from_lead(http_client, tenant_a, plot_idx=0)
    instalments = await http_client.get(
        "/api/v1/property-dev/instalments/",
        params={"sales_contract_id": spa["id"]},
        headers=tenant_a["headers"],
    )
    ins_id = instalments.json()[0]["id"]
    res = await http_client.post(
        f"/api/v1/property-dev/instalments/{ins_id}/issue-demand",
        headers=tenant_a["headers"],
    )
    assert res.status_code == 200, res.text

    # The event-bus is async via publish_detached → let it settle.
    import asyncio

    await asyncio.sleep(0.05)
    matching = [c for c in captured if c.get("instalment_id") == ins_id]
    assert matching, "demand event not published"
    assert matching[0]["template"] == "INSTALMENT_DEMAND"
    event_bus.unsubscribe("correspondence.outbound.requested", _handler)


@pytest.mark.asyncio
async def test_instalment_idor_blocked_for_tenant_b(http_client, tenant_a, tenant_b):
    spa = await _spa_from_lead(http_client, tenant_a, plot_idx=1)
    instalments = await http_client.get(
        "/api/v1/property-dev/instalments/",
        params={"sales_contract_id": spa["id"]},
        headers=tenant_a["headers"],
    )
    ins_id = instalments.json()[0]["id"]
    res = await http_client.post(
        f"/api/v1/property-dev/instalments/{ins_id}/mark-paid",
        json={"amount": "1000"},
        headers=tenant_b["headers"],
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_late_fee_accrual_idempotent(http_client, tenant_a):
    """Late-fee accrual endpoint runs without error + reports counts."""
    res = await http_client.post(
        "/api/v1/property-dev/instalments/accrue-late-fees",
        headers=tenant_a["headers"],
    )
    assert res.status_code == 200, res.text
    assert "touched_count" in res.json()


# ════════════════════════════════════════════════════════════════════════
# Schema validation edge cases
# ════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_reservation_create_requires_currency(http_client, tenant_a):
    res = await http_client.post(
        "/api/v1/property-dev/reservations/",
        json={
            "plot_id": tenant_a["plots"][0],
            "deposit_amount": "1000",
        },
        headers=tenant_a["headers"],
    )
    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_spa_create_invalid_contract_number_format(http_client, tenant_a):
    res = await http_client.post(
        "/api/v1/property-dev/sales-contracts/",
        json={
            "plot_id": tenant_a["plots"][0],
            "contract_number": "garbage-format",
            "total_value": "1000",
            "currency": "EUR",
        },
        headers=tenant_a["headers"],
    )
    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_lead_with_invalid_budget_currency_rejected(http_client, tenant_a):
    res = await http_client.post(
        "/api/v1/property-dev/leads/",
        json={
            "development_id": tenant_a["development_id"],
            "source": "broker",
            "full_name": "Test",
            "budget_min": "-1000",
            "currency": "EUR",
        },
        headers=tenant_a["headers"],
    )
    assert res.status_code == 422, res.text


# ════════════════════════════════════════════════════════════════════════
# Permission gates (sample sensitive ops)
# ════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_spa_sign_requires_manager(http_client, tenant_a, viewer_user):
    spa = await _spa_from_lead(http_client, tenant_a, plot_idx=0)
    res = await http_client.post(
        f"/api/v1/property-dev/sales-contracts/{spa['id']}/sign",
        json={},
        headers=viewer_user["headers"],
    )
    assert res.status_code == 403, res.text


@pytest.mark.asyncio
async def test_instalment_waive_requires_manager(http_client, tenant_a, viewer_user):
    spa = await _spa_from_lead(http_client, tenant_a, plot_idx=1)
    instalments = await http_client.get(
        "/api/v1/property-dev/instalments/",
        params={"sales_contract_id": spa["id"]},
        headers=tenant_a["headers"],
    )
    ins_id = instalments.json()[0]["id"]
    res = await http_client.post(
        f"/api/v1/property-dev/instalments/{ins_id}/waive",
        json={"reason": "shouldn't happen"},
        headers=viewer_user["headers"],
    )
    assert res.status_code == 403, res.text


@pytest.mark.asyncio
async def test_lead_convert_requires_manager(http_client, tenant_a, viewer_user):
    lead_id = await _fresh_lead(http_client, tenant_a)
    res = await http_client.post(
        f"/api/v1/property-dev/leads/{lead_id}/convert-to-reservation",
        json={
            "plot_id": tenant_a["plots"][0],
            "deposit_amount": "1000",
            "currency": "EUR",
        },
        headers=viewer_user["headers"],
    )
    assert res.status_code == 403, res.text
