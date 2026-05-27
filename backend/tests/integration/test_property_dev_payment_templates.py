"""Integration tests for the milestone-template payment-schedule flows.

Covers the new endpoints + service helpers added so the PropertyDevPage
UI can drive Reservations → SPA → Payment Schedule end-to-end:

* GET  /api/v1/property-dev/payment-schedule-templates/
* POST /api/v1/property-dev/payment-schedules/from-template
* GET  /api/v1/property-dev/payment-schedules/?development_id=…
* GET  /api/v1/property-dev/sales-contracts/?development_id=…

Scaffolding follows the existing ``test_property_dev_lead_to_spa.py``
pattern: per-module temporary SQLite registered BEFORE any ``from app…``
import keeps the production DB untouched.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from decimal import Decimal
from pathlib import Path

# ── Per-module SQLite isolation (must run BEFORE app imports) ──────────────
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-propdev-templates-"))
_TMP_DB = _TMP_DIR / "propdev_templates.db"
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


@pytest_asyncio.fixture(scope="module")
async def admin_session(http_client):
    """Register an admin + bootstrap project → dev → plot → SPA stack."""
    email = f"propdev-tmpl-{uuid.uuid4().hex[:8]}@example.com"
    password = f"PropDevTpl{uuid.uuid4().hex[:6]}9!"
    reg = await http_client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "Admin Templates"},
    )
    assert reg.status_code in (200, 201), reg.text
    await _set_role(email, "admin")
    login = await http_client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    proj = await http_client.post(
        "/api/v1/projects/",
        json={
            "name": f"Templates {uuid.uuid4().hex[:6]}",
            "description": "payment-schedule templates probe",
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
            "code": f"DT{uuid.uuid4().hex[:6].upper()}",
            "name": "Templates dev",
            "total_plots": 4,
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


async def _create_spa(
    http_client: AsyncClient,
    headers: dict[str, str],
    development_id: str,
    *,
    plot_number: str,
    total_value: str = "1000000",
) -> dict:
    """Helper: dev → plot → reservation → convert → SPA."""
    plot = await http_client.post(
        "/api/v1/property-dev/plots/",
        json={
            "development_id": development_id,
            "plot_number": plot_number,
            "area_m2": "120",
            "price_base": total_value,
            "currency": "EUR",
        },
        headers=headers,
    )
    assert plot.status_code == 201, plot.text
    plot_id = plot.json()["id"]

    res = await http_client.post(
        "/api/v1/property-dev/reservations/",
        json={
            "plot_id": plot_id,
            "deposit_amount": "50000",
            "currency": "EUR",
        },
        headers=headers,
    )
    assert res.status_code == 201, res.text
    reservation_id = res.json()["id"]

    spa = await http_client.post(
        f"/api/v1/property-dev/reservations/{reservation_id}/convert-to-spa",
        json={
            "signing_date": "2026-06-01",
            "total_value": total_value,
            "currency": "EUR",
        },
        headers=headers,
    )
    assert spa.status_code == 201, spa.text
    return {
        "plot_id": plot_id,
        "reservation_id": reservation_id,
        "spa": spa.json(),
    }


@pytest.mark.asyncio
async def test_template_catalogue_lists_five_templates(http_client, admin_session) -> None:
    resp = await http_client.get(
        "/api/v1/property-dev/payment-schedule-templates/",
        headers=admin_session["headers"],
    )
    assert resp.status_code == 200, resp.text
    catalogue = resp.json()
    keys = {entry["key"] for entry in catalogue}
    assert keys >= {
        "single_balance",
        "10_40_50",
        "30_30_40",
        "20_30_30_20",
        "quarterly_12",
    }
    by_key = {entry["key"]: entry for entry in catalogue}
    assert by_key["10_40_50"]["milestone_count"] == 3
    assert by_key["quarterly_12"]["milestone_count"] == 12


@pytest.mark.asyncio
async def test_generate_from_template_30_30_40(http_client, admin_session) -> None:
    ctx = await _create_spa(
        http_client,
        admin_session["headers"],
        admin_session["development_id"],
        plot_number="T-001",
        total_value="1000000",
    )
    spa = ctx["spa"]

    # Default single-balance schedule was auto-created. Suspend first.
    sched_resp = await http_client.get(
        f"/api/v1/property-dev/payment-schedules/?sales_contract_id={spa['id']}",
        headers=admin_session["headers"],
    )
    assert sched_resp.status_code == 200, sched_resp.text
    schedules = sched_resp.json()
    assert len(schedules) == 1
    sched_id = schedules[0]["id"]
    suspend = await http_client.post(
        f"/api/v1/property-dev/payment-schedules/{sched_id}/suspend",
        headers=admin_session["headers"],
    )
    assert suspend.status_code == 200, suspend.text

    gen = await http_client.post(
        "/api/v1/property-dev/payment-schedules/from-template",
        json={
            "sales_contract_id": spa["id"],
            "template_key": "30_30_40",
            "start_date": "2026-06-01",
            "late_fee_pct": "5",
            "grace_period_days": 7,
        },
        headers=admin_session["headers"],
    )
    assert gen.status_code == 201, gen.text
    sched = gen.json()
    assert sched["status"] == "active"
    assert Decimal(sched["total_amount"]) == Decimal("1000000")
    assert Decimal(sched["late_fee_pct"]) == Decimal("5")

    ins_resp = await http_client.get(
        f"/api/v1/property-dev/instalments/?schedule_id={sched['id']}",
        headers=admin_session["headers"],
    )
    assert ins_resp.status_code == 200, ins_resp.text
    instalments = ins_resp.json()
    assert len(instalments) == 3
    amounts = [Decimal(i["amount"]) for i in instalments]
    assert amounts[0] == Decimal("300000.00")
    assert amounts[1] == Decimal("300000.00")
    assert amounts[2] == Decimal("400000.00")
    assert sum(amounts) == Decimal("1000000.00")
    # First line marked due so dashboards pick it up immediately.
    assert instalments[0]["status"] == "due"
    # Due dates: start + 0d, +180d, +360d.
    assert instalments[0]["due_date"] == "2026-06-01"
    assert instalments[1]["due_date"] == "2026-11-28"
    assert instalments[2]["due_date"] == "2027-05-27"


@pytest.mark.asyncio
async def test_generate_from_template_rejects_unknown(http_client, admin_session) -> None:
    ctx = await _create_spa(
        http_client,
        admin_session["headers"],
        admin_session["development_id"],
        plot_number="T-002",
    )
    resp = await http_client.post(
        "/api/v1/property-dev/payment-schedules/from-template",
        json={
            "sales_contract_id": ctx["spa"]["id"],
            "template_key": "made_up_split",
            "start_date": "2026-06-01",
        },
        headers=admin_session["headers"],
    )
    assert resp.status_code == 422
    assert "Unknown template_key" in resp.text


@pytest.mark.asyncio
async def test_generate_refuses_active_schedule(http_client, admin_session) -> None:
    """Re-running the generator against an active schedule must 409."""
    ctx = await _create_spa(
        http_client,
        admin_session["headers"],
        admin_session["development_id"],
        plot_number="T-003",
    )
    spa = ctx["spa"]
    # Default schedule is active immediately after convert-to-spa.
    resp = await http_client.post(
        "/api/v1/property-dev/payment-schedules/from-template",
        json={
            "sales_contract_id": spa["id"],
            "template_key": "10_40_50",
            "start_date": "2026-06-01",
        },
        headers=admin_session["headers"],
    )
    assert resp.status_code == 409, resp.text


@pytest.mark.asyncio
async def test_list_sales_contracts_by_development(http_client, admin_session) -> None:
    ctx = await _create_spa(
        http_client,
        admin_session["headers"],
        admin_session["development_id"],
        plot_number="T-004",
    )
    dev_id = admin_session["development_id"]
    spa_id = ctx["spa"]["id"]
    resp = await http_client.get(
        f"/api/v1/property-dev/sales-contracts/?development_id={dev_id}",
        headers=admin_session["headers"],
    )
    assert resp.status_code == 200, resp.text
    contracts = resp.json()
    assert any(c["id"] == spa_id for c in contracts)


@pytest.mark.asyncio
async def test_list_payment_schedules_by_development(http_client, admin_session) -> None:
    dev_id = admin_session["development_id"]
    resp = await http_client.get(
        f"/api/v1/property-dev/payment-schedules/?development_id={dev_id}",
        headers=admin_session["headers"],
    )
    assert resp.status_code == 200, resp.text
    schedules = resp.json()
    assert len(schedules) >= 1
    assert all("sales_contract_id" in s for s in schedules)


@pytest.mark.asyncio
async def test_list_schedules_requires_a_filter(http_client, admin_session) -> None:
    """422 when neither sales_contract_id nor development_id supplied."""
    resp = await http_client.get(
        "/api/v1/property-dev/payment-schedules/",
        headers=admin_session["headers"],
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_sales_contracts_requires_a_filter(http_client, admin_session) -> None:
    resp = await http_client.get(
        "/api/v1/property-dev/sales-contracts/",
        headers=admin_session["headers"],
    )
    assert resp.status_code == 422
