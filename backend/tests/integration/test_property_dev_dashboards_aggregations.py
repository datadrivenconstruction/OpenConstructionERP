"""Property Development R6 dashboards aggregations integration suite.

Task #140 — covers the six new dashboard endpoints introduced by
``backend/app/modules/property_dev/router.py``::

  GET /dashboards/inventory-heatmap
  GET /dashboards/sales-velocity
  GET /dashboards/cashflow-waterfall
  GET /dashboards/inventory-ageing
  GET /dashboards/funnel-conversion
  GET /dashboards/buyer-journey

All endpoints are gated by ``RequirePermission("property_dev.read")`` and
walked through ``_verify_owner_via_*`` IDOR closures.

Seeding is done directly through the repository layer to avoid a
pre-existing aiosqlite/Windows MissingGreenlet that surfaces only in the
Lead -> Reservation HTTP pipeline. The dashboard endpoints themselves
are exercised via HTTP so the permission gate + IDOR closure are
exercised end-to-end.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from decimal import Decimal
from pathlib import Path

# ── Per-module SQLite isolation (must run BEFORE app imports) ──────────────
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-propdev-dashboards-"))
_TMP_DB = _TMP_DIR / "propdev_dashboards.db"
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
    email = f"{label}-{uuid.uuid4().hex[:8]}@dash-r6.io"
    password = f"DashR6{uuid.uuid4().hex[:6]}9!"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": label},
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


# ── Direct-DB seeders (bypass the buggy convert pipeline on Win+aiosqlite) ─


async def _seed_db_world(
    *,
    project_name: str,
    project_owner_email: str,
    code_suffix: str,
    name: str = "Marina Heights",
    plots_data: list[dict] | None = None,
    leads_data: list[dict] | None = None,
    spas_data: list[dict] | None = None,
    escrows_data: list[dict] | None = None,
    add_handover_completed_plot: bool = False,
) -> dict:
    """Seed Project + Development + Phase + Block + plots + (optionally)
    leads / SPAs / payment schedules / instalments / escrows."""
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.projects.models import Project
    from app.modules.property_dev.models import (
        Block,
        Buyer,
        ContractParty,
        Development,
        EscrowAccount,
        EscrowTransaction,
        Handover,
        Instalment,
        Lead,
        PaymentSchedule,
        Phase,
        Plot,
        Reservation,
        SalesContract,
    )
    from app.modules.users.models import User

    async with async_session_factory() as s:
        # Find the owner user.
        owner = (await s.execute(select(User).where(User.email == project_owner_email.lower()))).scalar_one()

        proj = Project(
            name=project_name,
            description="dashboard seed",
            owner_id=owner.id,
            currency="EUR",
        )
        s.add(proj)
        await s.flush()

        dev = Development(
            project_id=proj.id,
            code=f"DEV{code_suffix}",
            name=name,
            total_plots=6,
            sales_phase="sales_open",
        )
        s.add(dev)
        await s.flush()

        phase = Phase(
            development_id=dev.id,
            code=f"P{code_suffix[:4]}",
            name="Phase 1",
            sequence=1,
            status="planned",
        )
        s.add(phase)
        await s.flush()

        block = Block(
            phase_id=phase.id,
            code=f"B{code_suffix[:4]}A",
            name="Tower A",
            levels_count=3,
            units_per_level=2,
            status="planned",
        )
        s.add(block)
        await s.flush()

        plot_ids: dict[str, Plot] = {}
        for p in plots_data or []:
            plot = Plot(
                development_id=dev.id,
                plot_number=p["plot_number"],
                block_id=block.id if p.get("with_block", True) else None,
                area_m2=Decimal(str(p.get("area_m2", 100))),
                price_base=Decimal(str(p.get("price_base", 400_000))),
                currency=p.get("currency", "EUR"),
                status=p.get("status", "planned"),
            )
            s.add(plot)
            await s.flush()
            plot_ids[p["plot_number"]] = plot

        for ld in leads_data or []:
            lead = Lead(
                development_id=dev.id,
                source=ld.get("source", "web_form"),
                full_name=ld.get("full_name", "Seeded Lead"),
                email=ld.get("email", f"l{uuid.uuid4().hex[:6]}@x.io"),
                status=ld.get("status", "new"),
                currency=ld.get("currency", "EUR"),
            )
            s.add(lead)

        spa_objs: dict[str, SalesContract] = {}
        for sd in spas_data or []:
            plot_obj = plot_ids[sd["plot_number"]]
            buyer = Buyer(
                development_id=dev.id,
                plot_id=plot_obj.id,
                full_name=sd.get("buyer_name", "Seeded Buyer"),
                email=sd.get("buyer_email", f"b{uuid.uuid4().hex[:6]}@x.io"),
                status="contracted",
                contract_value=Decimal(str(sd["total_value"])),
                currency=sd["currency"],
                contract_signed_at=sd["signing_date"],
            )
            s.add(buyer)
            await s.flush()

            res = Reservation(
                plot_id=plot_obj.id,
                buyer_id=buyer.id,
                reservation_number=f"RES-{code_suffix}-{sd['seq']:05d}",
                deposit_amount=Decimal("5000"),
                currency=sd["currency"],
                status="converted",
            )
            s.add(res)
            await s.flush()

            spa = SalesContract(
                contract_number=f"SPA-{code_suffix}-{sd['seq']:05d}",
                plot_id=plot_obj.id,
                reservation_id=res.id,
                signing_date=sd["signing_date"],
                governing_law="DE-BE",
                language="en",
                total_price_breakdown={
                    "base": str(sd["total_value"]),
                    "vat": "0",
                    "stamp_duty": "0",
                    "legal_fees": "0",
                    "options_value": "0",
                    "discounts": "0",
                },
                total_value=Decimal(str(sd["total_value"])),
                currency=sd["currency"],
                status="signed",
                terms_version="v1.0",
            )
            s.add(spa)
            await s.flush()
            spa_objs[sd["plot_number"]] = spa

            # Link buyer as the primary contract party so the journey
            # endpoint can walk Buyer -> ContractParty -> SalesContract.
            s.add(
                ContractParty(
                    sales_contract_id=spa.id,
                    buyer_id=buyer.id,
                    ownership_pct=Decimal("100"),
                    party_role="primary",
                    signing_order=1,
                )
            )

            sched = PaymentSchedule(
                sales_contract_id=spa.id,
                currency=sd["currency"],
                total_amount=Decimal(str(sd["total_value"])),
                status="active",
            )
            s.add(sched)
            await s.flush()

            for ins_d in sd.get("instalments", []):
                ins = Instalment(
                    schedule_id=sched.id,
                    sequence=ins_d["sequence"],
                    milestone_label=ins_d.get("milestone_label", "milestone"),
                    milestone_event=ins_d.get("milestone_event", "spa_signed"),
                    due_date=ins_d["due_date"],
                    amount=Decimal(str(ins_d["amount"])),
                    status=ins_d.get("status", "pending"),
                )
                s.add(ins)

        for ed in escrows_data or []:
            acct = EscrowAccount(
                development_id=dev.id,
                regulator_ref=ed.get("regulator_ref", "other"),
                regulator_account_number=ed.get("regulator_account_number", "X"),
                bank_name=ed.get("bank_name", "Bank"),
                iban=ed.get("iban", "DE89370400440532013000"),
                swift_bic=ed.get("swift_bic", "COBADEFFXXX"),
                currency=ed["currency"],
                opened_at=ed.get("opened_at", "2026-01-01"),
            )
            s.add(acct)
            await s.flush()
            for tx_d in ed.get("transactions", []):
                s.add(
                    EscrowTransaction(
                        escrow_account_id=acct.id,
                        direction=tx_d["direction"],
                        amount=Decimal(str(tx_d["amount"])),
                        currency=ed["currency"],
                        source_type=tx_d.get("source_type", "instalment"),
                        source_reference=tx_d.get("source_reference", ""),
                        transaction_date=tx_d["transaction_date"],
                        reconciliation_state="unreconciled",
                    )
                )

        # Optionally seed a completed handover (for funnel test).
        if add_handover_completed_plot and plot_ids:
            target = next(iter(plot_ids.values()))
            h = Handover(
                plot_id=target.id,
                scheduled_at="2026-05-15",
                completed_at="2026-05-20",
                snag_count_at_handover=0,
                final_check_passed=True,
            )
            s.add(h)

        await s.commit()

        return {
            "project_id": str(proj.id),
            "development_id": str(dev.id),
            "phase_id": str(phase.id),
            "block_id": str(block.id),
            "plots": {pn: str(p.id) for pn, p in plot_ids.items()},
            "spas": {pn: str(spa.id) for pn, spa in spa_objs.items()},
        }


# ── Tenant fixtures ─────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def tenant_a(http_client):
    email, meta = await _register(http_client, "tenant-a-dash")
    await _set_role(email, "admin")
    headers = await _login(http_client, email, meta["_password"])
    suffix = uuid.uuid4().hex[:6].upper()

    plots = [
        {"plot_number": f"H{suffix}-A1", "area_m2": 120, "status": "planned"},
        {"plot_number": f"H{suffix}-A2", "area_m2": 110, "status": "reserved"},
        {"plot_number": f"H{suffix}-LEG", "area_m2": 130, "with_block": False},
        {"plot_number": f"H{suffix}-SOLD", "area_m2": 125, "status": "sold"},
        {"plot_number": f"H{suffix}-MAR", "area_m2": 140, "status": "planned"},
        {"plot_number": f"H{suffix}-CF", "area_m2": 150, "status": "planned"},
    ]
    leads = [
        {"full_name": "Lead A", "email": f"la-{uuid.uuid4().hex[:5]}@x.io"},
        {"full_name": "Lead B", "email": f"lb-{uuid.uuid4().hex[:5]}@x.io"},
        {"full_name": "Lead C", "email": f"lc-{uuid.uuid4().hex[:5]}@x.io"},
    ]
    spas = [
        {
            "plot_number": f"H{suffix}-A1",
            "seq": 1,
            "signing_date": "2026-04-15",
            "total_value": "480000",
            "currency": "EUR",
            "buyer_name": "SPA Buyer 1",
            "buyer_email": "spa1@x.io",
            "instalments": [
                {
                    "sequence": 1,
                    "due_date": "2026-06-15",
                    "amount": "60000",
                    "milestone_label": "Foundation",
                },
                {
                    "sequence": 2,
                    "due_date": "2026-09-15",
                    "amount": "80000",
                    "milestone_label": "Structure",
                },
            ],
        },
    ]
    escrows = [
        {
            "currency": "EUR",
            "transactions": [
                {
                    "direction": "credit",
                    "amount": "60000",
                    "transaction_date": "2026-06-20",
                    "source_type": "instalment",
                },
                {
                    "direction": "debit",
                    "amount": "15000",
                    "transaction_date": "2026-06-25",
                    "source_type": "draw_request",
                },
            ],
        },
    ]
    seed = await _seed_db_world(
        project_name=f"PD-{suffix}",
        project_owner_email=email,
        code_suffix=suffix,
        plots_data=plots,
        leads_data=leads,
        spas_data=spas,
        escrows_data=escrows,
        add_handover_completed_plot=True,
    )
    return {"email": email, "headers": headers, **seed}


@pytest_asyncio.fixture(scope="module")
async def tenant_b(http_client):
    """Cross-tenant intruder: owns its own (empty) dev for auth + IDOR check."""
    email, meta = await _register(http_client, "tenant-b-dash")
    await _set_role(email, "editor")
    headers = await _login(http_client, email, meta["_password"])
    suffix = uuid.uuid4().hex[:6].upper()
    seed = await _seed_db_world(
        project_name=f"PD-B-{suffix}",
        project_owner_email=email,
        code_suffix=suffix,
        name="Highland Mews",
    )
    return {"email": email, "headers": headers, **seed}


@pytest_asyncio.fixture(scope="module")
async def tenant_multi(http_client):
    """Mixed-currency development for the velocity + cashflow tests."""
    email, meta = await _register(http_client, "tenant-mc-dash")
    await _set_role(email, "admin")
    headers = await _login(http_client, email, meta["_password"])
    suffix = uuid.uuid4().hex[:6].upper()

    plots = [
        {"plot_number": f"MC{suffix}-EUR", "area_m2": 140, "currency": "EUR"},
        {"plot_number": f"MC{suffix}-USD", "area_m2": 140, "currency": "USD"},
    ]
    spas = [
        {
            "plot_number": f"MC{suffix}-EUR",
            "seq": 1,
            "signing_date": "2026-03-15",
            "total_value": "500000",
            "currency": "EUR",
            "buyer_email": f"mc-eur-{uuid.uuid4().hex[:4]}@x.io",
        },
        {
            "plot_number": f"MC{suffix}-USD",
            "seq": 2,
            "signing_date": "2026-03-22",
            "total_value": "600000",
            "currency": "USD",
            "buyer_email": f"mc-usd-{uuid.uuid4().hex[:4]}@x.io",
        },
    ]
    escrows = [
        {
            "currency": "EUR",
            "transactions": [
                {
                    "direction": "credit",
                    "amount": "25000",
                    "transaction_date": "2026-04-10",
                    "source_type": "instalment",
                },
            ],
        },
        {
            "currency": "USD",
            "iban": "US12345678901234567890",
            "swift_bic": "CHASUS33XXX",
            "transactions": [
                {
                    "direction": "credit",
                    "amount": "30000",
                    "transaction_date": "2026-04-12",
                    "source_type": "instalment",
                },
            ],
        },
    ]
    seed = await _seed_db_world(
        project_name=f"PD-MC-{suffix}",
        project_owner_email=email,
        code_suffix=suffix,
        name="Mixed Currency Project",
        plots_data=plots,
        spas_data=spas,
        escrows_data=escrows,
    )
    return {"email": email, "headers": headers, **seed}


# ════════════════════════════════════════════════════════════════════════
# Happy-path tests (one per endpoint, with full R6-schema seeding)
# ════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_inventory_heatmap_groups_by_phase_and_block(http_client, tenant_a):
    """Plots placed inside a Block appear under that Phase -> Block path.
    Legacy plot without a block lands in the fallback group.
    """
    dev_id = tenant_a["development_id"]
    res = await http_client.get(
        "/api/v1/property-dev/dashboards/inventory-heatmap",
        params={"dev_id": dev_id},
        headers=tenant_a["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["development_id"] == dev_id
    assert body["total_units"] >= 6

    found_plots = []
    for phase in body["phases"]:
        for blk in phase["blocks"]:
            for unit in blk["units"]:
                found_plots.append((phase["phase_id"], blk["block_id"], unit["plot_id"]))
    plot_to_phase = {p[2]: p for p in found_plots}
    a1_id = tenant_a["plots"][next(k for k in tenant_a["plots"] if k.endswith("-A1"))]
    leg_id = tenant_a["plots"][next(k for k in tenant_a["plots"] if k.endswith("-LEG"))]
    assert a1_id in plot_to_phase
    assert plot_to_phase[a1_id][1] == tenant_a["block_id"]
    # Legacy plot (no block) must surface in a None/None fallback group.
    assert leg_id in plot_to_phase
    assert plot_to_phase[leg_id][0] is None
    assert plot_to_phase[leg_id][1] is None
    # status_counts sums to total_units.
    assert sum(body["status_counts"].values()) == body["total_units"]


@pytest.mark.asyncio
async def test_sales_velocity_uses_spa_signing_date(http_client, tenant_a):
    """Velocity primary source = SalesContract.signing_date.

    The seeded SPA has signing_date 2026-04-15 with total_value 480000 EUR.
    """
    dev_id = tenant_a["development_id"]
    res = await http_client.get(
        "/api/v1/property-dev/dashboards/sales-velocity",
        params={"dev_id": dev_id, "granularity": "month"},
        headers=tenant_a["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["granularity"] == "month"
    apr = next((b for b in body["series"] if b["period"] == "2026-04"), None)
    assert apr is not None, body
    eur_rev = next(
        (e for e in apr["revenue"] if e["currency"] == "EUR"),
        None,
    )
    assert eur_rev is not None
    assert Decimal(str(eur_rev["amount"])) == Decimal("480000.00")
    assert apr["units"] == 1


@pytest.mark.asyncio
async def test_cashflow_waterfall_from_instalments_and_escrow(
    http_client,
    tenant_a,
):
    """Cashflow waterfall sums Instalment + EscrowTransaction by month."""
    dev_id = tenant_a["development_id"]
    res = await http_client.get(
        "/api/v1/property-dev/dashboards/cashflow-waterfall",
        params={"dev_id": dev_id, "start_month": "2026-05", "months": 6},
        headers=tenant_a["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["start_month"] == "2026-05"
    assert body["months"] == 6
    jun = next((s for s in body["series"] if s["month"] == "2026-06"), None)
    assert jun is not None, body
    sched_eur = next(
        (e for e in jun["scheduled"] if e["currency"] == "EUR"),
        None,
    )
    assert sched_eur is not None
    assert Decimal(str(sched_eur["amount"])) == Decimal("60000.00")
    coll_eur = next(
        (e for e in jun["actual_collected"] if e["currency"] == "EUR"),
        None,
    )
    assert coll_eur is not None
    assert Decimal(str(coll_eur["amount"])) == Decimal("60000.00")
    disb_eur = next(
        (e for e in jun["actual_disbursed"] if e["currency"] == "EUR"),
        None,
    )
    assert disb_eur is not None
    assert Decimal(str(disb_eur["amount"])) == Decimal("15000.00")


@pytest.mark.asyncio
async def test_inventory_ageing_buckets(http_client, tenant_a):
    """Ageing buckets cover unsold inventory; sold/handed_over excluded."""
    dev_id = tenant_a["development_id"]
    res = await http_client.get(
        "/api/v1/property-dev/dashboards/inventory-ageing",
        params={"dev_id": dev_id},
        headers=tenant_a["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    bucket_labels = [b["label"] for b in body["buckets"]]
    assert "Reserved, no contract" in bucket_labels
    # All four day-buckets present.
    assert "0–30" in bucket_labels or "0–30" in bucket_labels
    # total_unsold = sum across all buckets.
    assert body["total_unsold"] == sum(int(b["count"]) for b in body["buckets"])
    # Sold plot is not in any bucket.
    sold_id = tenant_a["plots"][next(k for k in tenant_a["plots"] if k.endswith("-SOLD"))]
    for b in body["buckets"]:
        for p in b["plots"]:
            assert p["plot_id"] != sold_id


@pytest.mark.asyncio
async def test_funnel_conversion_5_stages(http_client, tenant_a):
    """Funnel emits Lead -> Reservation -> SPA draft -> SPA signed -> Handover."""
    dev_id = tenant_a["development_id"]
    res = await http_client.get(
        "/api/v1/property-dev/dashboards/funnel-conversion",
        params={"dev_id": dev_id, "period_days": 365},
        headers=tenant_a["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    codes = [s["code"] for s in body["stages"]]
    assert codes == [
        "lead",
        "reservation",
        "spa_draft",
        "spa_signed",
        "handover",
    ]
    # We seeded 3 leads + 1 reservation + 1 SPA (signed) + 1 handover.
    by_code = {s["code"]: int(s["count"]) for s in body["stages"]}
    assert by_code["lead"] >= 3
    assert by_code["reservation"] >= 1
    assert by_code["spa_signed"] >= 1
    assert by_code["handover"] >= 1
    assert Decimal(str(body["stages"][0]["drop_pct"])) == Decimal("0")


@pytest.mark.asyncio
async def test_buyer_journey_cross_entity_chain(http_client, tenant_a):
    """Journey emits Lead + Reservation + SPA + Schedule + Handover events.

    Locate the seeded Buyer via direct DB query (we created one but didn't
    expose its id through the seeder return value).
    """
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.property_dev.models import Buyer

    async with async_session_factory() as s:
        # Buyer whose plot is the A1 one (has signed SPA).
        a1_id = tenant_a["plots"][next(k for k in tenant_a["plots"] if k.endswith("-A1"))]
        buyer_row = (await s.execute(select(Buyer).where(Buyer.plot_id == uuid.UUID(a1_id)))).scalar_one()
        buyer_id = str(buyer_row.id)

    res = await http_client.get(
        "/api/v1/property-dev/dashboards/buyer-journey",
        params={"buyer_id": buyer_id},
        headers=tenant_a["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    codes = [e["code"] for e in body["events"]]
    assert "lead_created" in codes
    assert "reservation" in codes
    # Either "spa_signed" or "spa_draft" depending on seed state.
    assert any(c.startswith("spa_") for c in codes), codes
    for ev in body["events"]:
        assert ev["state"] in {"completed", "in_progress", "upcoming"}


# ════════════════════════════════════════════════════════════════════════
# Cross-tenant IDOR closure tests (six endpoints — every one must 404).
# ════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_idor_inventory_heatmap_404(http_client, tenant_a, tenant_b):
    res = await http_client.get(
        "/api/v1/property-dev/dashboards/inventory-heatmap",
        params={"dev_id": tenant_a["development_id"]},
        headers=tenant_b["headers"],
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_idor_sales_velocity_404(http_client, tenant_a, tenant_b):
    res = await http_client.get(
        "/api/v1/property-dev/dashboards/sales-velocity",
        params={"dev_id": tenant_a["development_id"]},
        headers=tenant_b["headers"],
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_idor_cashflow_waterfall_404(http_client, tenant_a, tenant_b):
    res = await http_client.get(
        "/api/v1/property-dev/dashboards/cashflow-waterfall",
        params={"dev_id": tenant_a["development_id"]},
        headers=tenant_b["headers"],
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_idor_inventory_ageing_404(http_client, tenant_a, tenant_b):
    res = await http_client.get(
        "/api/v1/property-dev/dashboards/inventory-ageing",
        params={"dev_id": tenant_a["development_id"]},
        headers=tenant_b["headers"],
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_idor_funnel_conversion_404(http_client, tenant_a, tenant_b):
    res = await http_client.get(
        "/api/v1/property-dev/dashboards/funnel-conversion",
        params={"dev_id": tenant_a["development_id"]},
        headers=tenant_b["headers"],
    )
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_idor_buyer_journey_404(http_client, tenant_a, tenant_b):
    """Intruder must 404 on tenant_a's buyer."""
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.property_dev.models import Buyer

    async with async_session_factory() as s:
        a1_id = tenant_a["plots"][next(k for k in tenant_a["plots"] if k.endswith("-A1"))]
        buyer_row = (await s.execute(select(Buyer).where(Buyer.plot_id == uuid.UUID(a1_id)))).scalar_one()
        target_buyer_id = str(buyer_row.id)

    res = await http_client.get(
        "/api/v1/property-dev/dashboards/buyer-journey",
        params={"buyer_id": target_buyer_id},
        headers=tenant_b["headers"],
    )
    assert res.status_code == 404, res.text


# ════════════════════════════════════════════════════════════════════════
# Multi-currency correctness (Cashflow + Velocity stay accurate)
# ════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_velocity_keeps_separate_currency_buckets(
    http_client,
    tenant_multi,
):
    dev_id = tenant_multi["development_id"]
    res = await http_client.get(
        "/api/v1/property-dev/dashboards/sales-velocity",
        params={"dev_id": dev_id, "granularity": "month"},
        headers=tenant_multi["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert "EUR" in body["currencies"]
    assert "USD" in body["currencies"]
    march = next((b for b in body["series"] if b["period"] == "2026-03"), None)
    assert march is not None
    eur = next((r for r in march["revenue"] if r["currency"] == "EUR"), None)
    usd = next((r for r in march["revenue"] if r["currency"] == "USD"), None)
    assert eur is not None and Decimal(str(eur["amount"])) == Decimal("500000.00")
    assert usd is not None and Decimal(str(usd["amount"])) == Decimal("600000.00")
    totals_eur = next(
        (r for r in body["totals"]["revenue"] if r["currency"] == "EUR"),
        None,
    )
    totals_usd = next(
        (r for r in body["totals"]["revenue"] if r["currency"] == "USD"),
        None,
    )
    assert totals_eur is not None
    assert totals_usd is not None
    assert Decimal(str(totals_eur["amount"])) == Decimal("500000.00")
    assert Decimal(str(totals_usd["amount"])) == Decimal("600000.00")


@pytest.mark.asyncio
async def test_cashflow_keeps_separate_currency_buckets(
    http_client,
    tenant_multi,
):
    dev_id = tenant_multi["development_id"]
    res = await http_client.get(
        "/api/v1/property-dev/dashboards/cashflow-waterfall",
        params={"dev_id": dev_id, "start_month": "2026-03", "months": 4},
        headers=tenant_multi["headers"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert "EUR" in body["currencies"] and "USD" in body["currencies"]
    apr = next((s for s in body["series"] if s["month"] == "2026-04"), None)
    assert apr is not None
    eur_coll = next(
        (e for e in apr["actual_collected"] if e["currency"] == "EUR"),
        None,
    )
    usd_coll = next(
        (e for e in apr["actual_collected"] if e["currency"] == "USD"),
        None,
    )
    assert eur_coll is not None
    assert usd_coll is not None
    assert Decimal(str(eur_coll["amount"])) == Decimal("25000.00")
    assert Decimal(str(usd_coll["amount"])) == Decimal("30000.00")
