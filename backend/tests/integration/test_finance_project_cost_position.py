# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""End to end: one project's budget, committed, invoiced and paid on the finance dashboard.

A main contractor records supplier invoices, pays its subcontractors and wants
one screen that says where the project stands. This drives exactly that job
through the real HTTP API and asserts every figure ``GET /finance/dashboard/``
returns for it.

The scenario (EUR, VAT 25 %)
----------------------------
* Bill of quantities, net, two WBS groups under two sections. The sections
  carry their own subtotal, as a real bill does, so a roll-up that sums every
  row instead of the priced leaves counts the bill twice.

  ====  ==========================  ===========
  WBS   leaf                         net
  ====  ==========================  ===========
  01    excavation 2 000 m3 x 30     60 000
  01    backfill   1 000 m3 x 40     40 000
  02    concrete   1 000 m3 x 150   150 000
  02    rebar     50 000 kg x 3     150 000
  ====  ==========================  ===========

  Locking the bill makes the budget: 400 000 net.
* Purchase order for rebar, 20 000 kg x 2.50 = 50 000 net + 12 500 VAT,
  approved and issued; 16 000 kg received and confirmed.
* Supplier invoice against that order, 16 000 kg = 40 000 net + 10 000 VAT,
  approved and paid in full (50 000 cash).
* A direct supplier invoice with no order behind it (site container hire),
  2 000 net + 500 VAT, approved, unpaid.
* Subcontract agreement 120 000 EUR, 5 % retention, active. One payment
  application for 30 000 gross, approved by foreman and finance and paid:
  1 500 retention held, 28 500 cash.

Basis of every figure (the point of the test)
---------------------------------------------
* budget: net of VAT, from the locked bill.
* actual (``total_actual``): net, what has been incurred. The order at the
  larger of what was received and what was settled on its invoices (40 000
  either way, the same money), the paid payment application at its gross
  (retention is owed, only later). 40 000 + 30 000 = 70 000.
* committed: net, the part of each commitment not yet incurred, so that
  committed plus actual is the outturn. The order 50 000 - 40 000, the
  agreement 120 000 - 30 000, and the supplier invoice no order stands behind
  at its own 2 000 (money spent without an order is committed the day it is
  invoiced). 10 000 + 90 000 + 2 000 = 102 000; outturn 172 000.
* invoiced: net. Supplier invoices at their subtotal, payment applications at
  the gross finance approved (before retention, which is still owed).
  40 000 + 2 000 + 30 000 = 72 000.
* paid (``total_paid``): cash out, VAT included, as the bank sees it.
  50 000 + 28 500 = 78 500.
* ``total_payable`` keeps its meaning: supplier invoices not yet marked paid,
  gross. 2 500.
* ``total_payments`` keeps its meaning: every payment row, either direction.

The order-first variant approves the purchase order before any bill is
locked, which is the order a busy site works in. A commitment counter that
needs a budget row to exist loses the order in that case.

The budget rows carry the same committed and actual line by line, so the
Budgets table adds up to the dashboard; that is asserted after every step,
not only at the end, because a step whose write does not reach the rows is
exactly what the end state can hide.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

import app.modules.boq.models  # noqa: F401
import app.modules.projects.models  # noqa: F401
import app.modules.users.models  # noqa: F401

API = "/api/v1"


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
async def client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _drain_events() -> None:
    """Wait for every detached event handler to finish.

    Almost every write here publishes through ``publish_detached``; a figure
    read before its subscriber ran would make a working roll-up look broken.
    """
    from app.core.events import event_bus

    for _ in range(100):
        pending = [t for t in list(event_bus._background_tasks) if not t.done()]
        if not pending:
            return
        await asyncio.gather(*pending, return_exceptions=True)
    raise AssertionError("event handlers did not settle")


async def _login(client: AsyncClient) -> tuple[str, dict[str, str]]:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    email = f"fin-{uuid.uuid4().hex[:8]}@cost-position.io"
    password = f"Cost{uuid.uuid4().hex[:6]}9"
    reg = await client.post(
        f"{API}/users/auth/register", json={"email": email, "password": password, "full_name": "QS"}
    )
    assert reg.status_code in (200, 201), reg.text
    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(role="admin", is_active=True))
        await s.commit()
    login = await client.post(f"{API}/users/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return reg.json()["id"], {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _seed_project_and_bill(owner_id: str, country: str = "HR") -> tuple[uuid.UUID, uuid.UUID]:
    """A Croatian project in EUR with one priced, unlocked bill (see module docstring)."""
    from app.database import async_session_factory
    from app.modules.boq.models import BOQ, Position
    from app.modules.projects.models import Project

    async with async_session_factory() as s:
        project = Project(
            id=uuid.uuid4(),
            name=f"Zagreb office block {uuid.uuid4().hex[:4]}",
            owner_id=uuid.UUID(owner_id),
            currency="EUR",
            region="EU",
            country_code=country,
            metadata_={},
            fx_rates=[],
        )
        s.add(project)
        await s.flush()
        boq = BOQ(project_id=project.id, name="Main bill")
        s.add(boq)
        await s.flush()
        sections = {
            "01": Position(
                boq_id=boq.id,
                ordinal="01",
                description="Earthworks",
                unit="",
                quantity="0",
                unit_rate="0",
                total="100000",
                wbs_id="01",
            ),
            "02": Position(
                boq_id=boq.id,
                ordinal="02",
                description="Concrete works",
                unit="",
                quantity="0",
                unit_rate="0",
                total="300000",
                wbs_id="02",
            ),
        }
        s.add_all(sections.values())
        await s.flush()
        leaves = [
            ("01", "01.001", "Excavation", "m3", "2000", "30", "60000"),
            ("01", "01.002", "Backfill", "m3", "1000", "40", "40000"),
            ("02", "02.001", "Concrete C30/37", "m3", "1000", "150", "150000"),
            ("02", "02.002", "Reinforcement B500B", "kg", "50000", "3", "150000"),
        ]
        for wbs, ordinal, text, unit, qty, rate, total in leaves:
            s.add(
                Position(
                    boq_id=boq.id,
                    parent_id=sections[wbs].id,
                    ordinal=ordinal,
                    description=text,
                    unit=unit,
                    quantity=qty,
                    unit_rate=rate,
                    total=total,
                    wbs_id=wbs,
                )
            )
        await s.commit()
        return project.id, boq.id


async def _ok(resp, *codes: int) -> dict:
    assert resp.status_code in (codes or (200, 201)), f"{resp.request.method} {resp.request.url}: {resp.text}"
    await _drain_events()
    return resp.json() if resp.content else {}


async def _supplier(client: AsyncClient, h: dict[str, str]) -> str:
    body = await _ok(
        await client.post(
            f"{API}/contacts/",
            json={"contact_type": "supplier", "company_name": f"Armatura d.o.o. {uuid.uuid4().hex[:4]}"},
            headers=h,
        )
    )
    return body["id"]


async def _order(client: AsyncClient, h: dict[str, str], project_id: uuid.UUID, vendor: str) -> dict:
    po = await _ok(
        await client.post(
            f"{API}/procurement/",
            json={
                "project_id": str(project_id),
                "vendor_contact_id": vendor,
                "issue_date": "2026-09-01",
                "delivery_date": "2026-09-20",
                "currency_code": "EUR",
                "amount_subtotal": "50000.00",
                "tax_amount": "12500.00",
                "amount_total": "62500.00",
                "items": [
                    {
                        "description": "Reinforcement B500B",
                        "quantity": "20000",
                        "unit": "kg",
                        "unit_rate": "2.50",
                        "amount": "50000.00",
                        "wbs_id": "02",
                        "cost_category": "material",
                    }
                ],
            },
            headers=h,
        )
    )
    await _ok(await client.post(f"{API}/procurement/{po['id']}/approve/", headers=h))
    return po


async def _issue_and_receive(client: AsyncClient, h: dict[str, str], po: dict) -> None:
    await _ok(await client.post(f"{API}/procurement/{po['id']}/issue/", headers=h))
    gr = await _ok(
        await client.post(
            f"{API}/procurement/goods-receipts/",
            json={
                "po_id": po["id"],
                "receipt_date": "2026-09-18",
                "delivery_note_number": "OTP-4471",
                "items": [
                    {
                        "po_item_id": po["items"][0]["id"],
                        "quantity_ordered": "20000",
                        "quantity_received": "16000",
                    }
                ],
            },
            headers=h,
        )
    )
    await _ok(await client.post(f"{API}/procurement/goods-receipts/{gr['id']}/confirm/", headers=h))


async def _supplier_invoices(
    client: AsyncClient, h: dict[str, str], project_id: uuid.UUID, vendor: str, po: dict
) -> None:
    linked = await _ok(
        await client.post(
            f"{API}/finance/",
            json={
                "project_id": str(project_id),
                "contact_id": vendor,
                "invoice_direction": "payable",
                "invoice_number": "R-2026-118",
                "invoice_date": "2026-09-22",
                "due_date": "2026-10-22",
                "currency_code": "EUR",
                "amount_subtotal": "40000.00",
                "tax_amount": "10000.00",
                "amount_total": "50000.00",
                "purchase_order_id": po["id"],
                "line_items": [
                    {
                        "description": "Reinforcement B500B",
                        "quantity": "16000",
                        "unit": "kg",
                        "unit_rate": "2.50",
                        "amount": "40000.00",
                        "wbs_id": "02",
                        "vat_rate": "25",
                    }
                ],
            },
            headers=h,
        )
    )
    await _ok(await client.post(f"{API}/finance/{linked['id']}/approve/", headers=h))
    await _ok(
        await client.post(
            f"{API}/finance/payments/",
            json={
                "invoice_id": linked["id"],
                "payment_date": "2026-09-25",
                "amount": "50000.00",
                "currency_code": "EUR",
                "reference": "HR12 2360 0001 1023 4567 8",
            },
            headers=h,
        )
    )
    await _ok(await client.post(f"{API}/finance/{linked['id']}/pay/", headers=h))

    direct = await _ok(
        await client.post(
            f"{API}/finance/",
            json={
                "project_id": str(project_id),
                "contact_id": vendor,
                "invoice_direction": "payable",
                "invoice_number": "R-2026-131",
                "invoice_date": "2026-09-23",
                "due_date": "2099-12-31",
                "currency_code": "EUR",
                "amount_subtotal": "2000.00",
                "tax_amount": "500.00",
                "amount_total": "2500.00",
                "line_items": [
                    {"description": "Site container hire, September", "amount": "2000.00", "vat_rate": "25"}
                ],
            },
            headers=h,
        )
    )
    await _ok(await client.post(f"{API}/finance/{direct['id']}/approve/", headers=h))


async def _active_agreement(client: AsyncClient, h: dict[str, str], project_id: uuid.UUID) -> dict:
    """A signed 120 000 EUR subcontract agreement with 5 % retention."""
    sub = await _ok(
        await client.post(
            f"{API}/subcontractors/subcontractors/",
            json={"legal_name": f"Beton Gradnja d.o.o. {uuid.uuid4().hex[:4]}", "country_code": "HR"},
            headers=h,
        )
    )
    for cert_type in ("insurance", "license"):
        await _ok(
            await client.post(
                f"{API}/subcontractors/certificates/",
                json={
                    "subcontractor_id": sub["id"],
                    "cert_type": cert_type,
                    "valid_until": (date.today() + timedelta(days=365)).isoformat(),
                },
                headers=h,
            )
        )
    agreement = await _ok(
        await client.post(
            f"{API}/subcontractors/agreements/",
            json={
                "subcontractor_id": sub["id"],
                "project_id": str(project_id),
                "title": "Formwork and concreting, basement",
                "total_value": "120000.00",
                "currency": "EUR",
                "retention_percent": "5",
                "start_date": date.today().isoformat(),
                "end_date": (date.today() + timedelta(days=180)).isoformat(),
            },
            headers=h,
        )
    )
    await _ok(
        await client.post(
            f"{API}/subcontractors/work-packages/",
            json={"agreement_id": agreement["id"], "name": "Basement slab and walls", "scope": "Formwork, pour, cure"},
            headers=h,
        )
    )
    await _ok(
        await client.patch(f"{API}/subcontractors/agreements/{agreement['id']}", json={"status": "active"}, headers=h)
    )
    return agreement


async def _subcontract(client: AsyncClient, h: dict[str, str], project_id: uuid.UUID) -> None:
    agreement = await _active_agreement(client, h, project_id)
    pa = await _ok(
        await client.post(
            f"{API}/subcontractors/payment-applications/",
            json={"agreement_id": agreement["id"], "gross_amount": "30000.00", "currency": "EUR"},
            headers=h,
        )
    )
    assert Decimal(pa["retention_amount"]) == Decimal("1500.00")
    await _ok(await client.post(f"{API}/subcontractors/payment-applications/{pa['id']}/approve-foreman", headers=h))
    await _ok(await client.post(f"{API}/subcontractors/payment-applications/{pa['id']}/approve-finance", headers=h))
    await _ok(await client.post(f"{API}/subcontractors/payment-applications/{pa['id']}/mark-paid", headers=h))


async def _dashboard(client: AsyncClient, h: dict[str, str], project_id: uuid.UUID) -> dict:
    return await _ok(await client.get(f"{API}/finance/dashboard/?project_id={project_id}", headers=h))


def _money(value: object) -> Decimal:
    return Decimal(str(value))


async def _assert_rows_match_dashboard(client: AsyncClient, h: dict[str, str], project_id: uuid.UUID) -> dict:
    """The Budgets rows add up to the dashboard's committed and actual."""
    dash = await _dashboard(client, h, project_id)
    body = await _ok(await client.get(f"{API}/finance/budgets/?project_id={project_id}", headers=h))
    items = body["items"] if isinstance(body, dict) else body
    rows = (sum(_money(r["committed"]) for r in items), sum(_money(r["actual"]) for r in items))
    assert rows == (_money(dash["total_committed"]), _money(dash["total_actual"])), (
        f"rows (committed, actual) {rows} != dashboard {dash['total_committed'], dash['total_actual']}"
    )
    return dash


def _assert_position(dash: dict) -> None:
    """Every figure of the scenario, with its basis named in the message."""
    expected = {
        "total_budget_original": "400000",  # net, locked bill leaves only
        "total_budget_revised": "400000",
        "total_committed": "102000",  # net, still open: order 10k + agreement 90k + unordered invoice 2k
        "total_invoiced": "72000",  # net: 40k + 2k supplier, 30k approved pay app gross
        "total_paid": "78500",  # cash: 50k incl. VAT + 28.5k sub net of retention
        "total_actual": "70000",  # incurred, net of VAT: 40k received + 30k pay app gross
        "total_over_commitment": "0",  # nothing incurred beyond what was committed
        "total_payable": "2500",  # unpaid supplier invoices, gross
        "total_payments": "50000",  # finance payment rows, any direction
    }
    wrong = {k: (dash.get(k), v) for k, v in expected.items() if dash.get(k) is None or _money(dash[k]) != Decimal(v)}
    assert not wrong, f"figures that do not roll up, as (got, expected): {wrong}"
    assert dash["currency"] == "EUR"
    assert dash["mixed_currencies"] is False
    assert Decimal(str(dash["budget_consumed_pct"])) == Decimal("17.5")  # 70 000 / 400 000
    # Outturn 172k of 400k is 43 %, well under the caution line.
    assert dash["budget_warning_level"] == "normal"
    assert _money(dash["total_variance"]) == Decimal("228000")  # 400k budget less the 172k outturn
    # The open balances. Nothing is receivable here, so the "net cash flow"
    # the dashboard reports is receivable less unpaid payables, an open
    # balance rather than money that moved.
    assert _money(dash["total_receivable"]) == Decimal("0")
    assert _money(dash["total_overdue"]) == Decimal("0")
    assert _money(dash["cash_flow_net"]) == Decimal("-2500")
    assert (dash["invoices_draft"], dash["invoices_pending"], dash["invoices_approved"], dash["invoices_paid"]) == (
        0,
        0,
        1,
        1,
    )


@pytest.mark.asyncio
async def test_the_dashboard_rolls_up_budget_committed_invoiced_and_paid(client: AsyncClient) -> None:
    from app.core.events import event_bus

    assert event_bus.list_handlers("procurement.po.approved")["procurement.po.approved"]
    owner, h = await _login(client)
    project_id, boq_id = await _seed_project_and_bill(owner)

    await _ok(await client.post(f"{API}/boq/boqs/{boq_id}/lock/", headers=h))
    vendor = await _supplier(client, h)
    po = await _order(client, h, project_id, vendor)
    await _assert_rows_match_dashboard(client, h, project_id)
    await _issue_and_receive(client, h, po)
    await _assert_rows_match_dashboard(client, h, project_id)
    await _supplier_invoices(client, h, project_id, vendor, po)
    await _assert_rows_match_dashboard(client, h, project_id)
    await _subcontract(client, h, project_id)

    _assert_position(await _assert_rows_match_dashboard(client, h, project_id))

    cf = await client.get(f"{API}/finance/gaap/statements/cash-flow", params={"project_id": str(project_id)}, headers=h)
    # Known gap, pinned so that closing it shows up here: the GAAP cash flow is
    # derived from journal movements on cash accounts, and neither a supplier
    # payment nor a paid subcontract application posts one. The 78 500 paid in
    # this scenario therefore does not appear; the dashboard's total_paid is
    # the figure that carries it. Update this assertion when payments post.
    cash_flow = await _ok(cf)
    assert (cash_flow["operating"], cash_flow["closing_cash"]) == ("0.00", "0.00")


@pytest.mark.asyncio
async def test_an_order_approved_before_the_bill_is_locked_is_still_committed(client: AsyncClient) -> None:
    owner, h = await _login(client)
    project_id, boq_id = await _seed_project_and_bill(owner)

    vendor = await _supplier(client, h)
    po = await _order(client, h, project_id, vendor)
    await _ok(await client.post(f"{API}/boq/boqs/{boq_id}/lock/", headers=h))
    # The order reaches the rows seeded after it.
    await _assert_rows_match_dashboard(client, h, project_id)
    await _issue_and_receive(client, h, po)
    await _supplier_invoices(client, h, project_id, vendor, po)
    await _subcontract(client, h, project_id)

    _assert_position(await _assert_rows_match_dashboard(client, h, project_id))


@pytest.mark.asyncio
async def test_locking_the_same_bill_twice_does_not_double_the_budget(client: AsyncClient) -> None:
    owner, h = await _login(client)
    project_id, boq_id = await _seed_project_and_bill(owner)

    await _ok(await client.post(f"{API}/boq/boqs/{boq_id}/lock/", headers=h))
    await _ok(await client.post(f"{API}/boq/boqs/{boq_id}/unlock/", headers=h))
    await _ok(await client.post(f"{API}/boq/boqs/{boq_id}/lock/", headers=h))

    dash = await _dashboard(client, h, project_id)
    assert _money(dash["total_budget_original"]) == Decimal("400000")


# ── The invoice-to-order link (column, legacy stamp, guard, three-way warning) ─


def _warned(report: dict) -> set[str]:
    return {r["rule_id"] for r in report["results"] if not r["passed"]}


@pytest.mark.asyncio
async def test_an_invoice_links_to_its_order_and_the_order_shows_what_is_invoiced(client: AsyncClient) -> None:
    from app.database import async_session_factory
    from app.modules.finance.models import Invoice
    from app.modules.procurement.repository import PurchaseOrderRepository

    owner, h = await _login(client)
    project_id, _ = await _seed_project_and_bill(owner)
    vendor = await _supplier(client, h)
    po = await _order(client, h, project_id, vendor)
    await _issue_and_receive(client, h, po)  # 16 000 of 20 000 kg received

    async def check(net: str, qty: str, invoice_id: str | None = None) -> set[str]:
        body = {"amount_subtotal": net, "line_items": [{"description": "Rebar B500B, delivery 1", "quantity": qty}]}
        if invoice_id:
            body["invoice_id"] = invoice_id
        return _warned(
            await _ok(await client.post(f"{API}/procurement/{po['id']}/invoice-check/", json=body, headers=h))
        )

    # Before any invoice: the full order is open; only what arrived may be billed.
    assert await check("40000.00", "16000") == set()
    assert await check("50000.00", "20000") == {"procurement.invoice_quantity_received"}
    assert await check("55000.00", "22000") == {
        "procurement.invoice_quantity_received",
        "procurement.invoice_within_order",
    }

    invoice_body = {
        "project_id": str(project_id),
        "contact_id": vendor,
        "invoice_direction": "payable",
        "invoice_date": "2026-09-22",
        "currency_code": "EUR",
        "amount_subtotal": "40000.00",
        "tax_amount": "10000.00",
        "amount_total": "50000.00",
        "purchase_order_id": po["id"],
        "line_items": [{"description": "Rebar B500B, delivery 1", "quantity": "16000", "amount": "40000.00"}],
    }
    linked = await _ok(await client.post(f"{API}/finance/", json=invoice_body, headers=h))
    assert linked["purchase_order_id"] == po["id"]
    await _ok(await client.post(f"{API}/finance/{linked['id']}/approve/", headers=h))

    # The saved invoice is not counted against itself; a second one is.
    assert await check("40000.00", "16000", invoice_id=linked["id"]) == set()
    assert await check("12000.00", "4800") == {
        "procurement.invoice_quantity_received",
        "procurement.invoice_within_order",
    }

    # An invoice raised before the column existed carries only the stamp.
    async with async_session_factory() as s:
        s.add(
            Invoice(
                project_id=project_id,
                contact_id=vendor,
                invoice_direction="payable",
                invoice_number=f"LEGACY-{uuid.uuid4().hex[:4]}",
                invoice_date="2026-09-01",
                currency_code="EUR",
                amount_subtotal=Decimal("5000"),
                tax_amount=Decimal("1250"),
                amount_total=Decimal("6250"),
                status="approved",
                metadata_={"source": "procurement", "po_id": po["id"]},
            )
        )
        await s.commit()
        assert await PurchaseOrderRepository(s).count_payable_invoices(uuid.UUID(po["id"]), project_id) == 2

    got = await _ok(await client.get(f"{API}/procurement/{po['id']}", headers=h))
    assert Decimal(got["invoiced_net"]) == Decimal("45000")
    assert got["invoice_count"] == 2
    listed = await _ok(await client.get(f"{API}/procurement/?project_id={project_id}", headers=h))
    assert Decimal(listed["items"][0]["invoiced_net"]) == Decimal("45000")
    legacy = [
        i
        for i in (await _ok(await client.get(f"{API}/finance/?project_id={project_id}", headers=h)))["items"]
        if i["invoice_number"].startswith("LEGACY-")
    ]
    assert legacy[0]["purchase_order_id"] == po["id"]
    # Saved the way the invoice form saves it, on an approved invoice: vendor
    # and link sent back unchanged, a note edited. Not a change of terms, and
    # the link is written to the column.
    resaved = await _ok(
        await client.patch(
            f"{API}/finance/{legacy[0]['id']}",
            json={
                "contact_id": vendor,
                "invoice_direction": "payable",
                "purchase_order_id": po["id"],
                "notes": "Delivery note 4471 attached",
            },
            headers=h,
        )
    )
    assert resaved["purchase_order_id"] == po["id"]
    async with async_session_factory() as s:
        row = await s.get(Invoice, uuid.UUID(legacy[0]["id"]))
        assert row is not None and str(row.purchase_order_id) == po["id"]
    # Unlinking a stamped invoice clears the stamp, or the link would read back.
    cleared = await _ok(
        await client.patch(f"{API}/finance/{legacy[0]['id']}", json={"purchase_order_id": None}, headers=h)
    )
    assert cleared["purchase_order_id"] is None
    await _ok(await client.patch(f"{API}/finance/{legacy[0]['id']}", json={"purchase_order_id": po["id"]}, headers=h))

    # The dashboard counts the order once: 50 000 order vs 45 000 invoiced on
    # it, 40 000 of it received, so 40 000 incurred and 10 000 still open.
    dash = await _dashboard(client, h, project_id)
    assert (Decimal(dash["total_committed"]), Decimal(dash["total_actual"])) == (Decimal("10000"), Decimal("40000"))
    assert Decimal(dash["total_invoiced"]) == Decimal("45000")


@pytest.mark.asyncio
async def test_a_link_the_order_cannot_back_is_refused(client: AsyncClient) -> None:
    owner, h = await _login(client)
    project_id, _ = await _seed_project_and_bill(owner)
    other_project, _ = await _seed_project_and_bill(owner)
    vendor = await _supplier(client, h)
    other_vendor = await _supplier(client, h)
    po = await _order(client, h, project_id, vendor)

    base = {
        "project_id": str(project_id),
        "contact_id": vendor,
        "invoice_direction": "payable",
        "currency_code": "EUR",
        "amount_subtotal": "100.00",
        "purchase_order_id": po["id"],
    }
    cases = {
        "other project": dict(base, project_id=str(other_project)),
        "other supplier": dict(base, contact_id=other_vendor),
        "receivable": dict(base, invoice_direction="receivable"),
        "unknown order": dict(base, purchase_order_id=str(uuid.uuid4())),
    }
    for name, body in cases.items():
        resp = await client.post(f"{API}/finance/", json=body, headers=h)
        assert resp.status_code == 422, (name, resp.text)

    draft = await _ok(
        await client.post(
            f"{API}/procurement/",
            json={"project_id": str(project_id), "vendor_contact_id": vendor, "currency_code": "EUR"},
            headers=h,
        )
    )
    resp = await client.post(f"{API}/finance/", json=dict(base, purchase_order_id=draft["id"]), headers=h)
    assert resp.status_code == 422, resp.text

    ok = await _ok(await client.post(f"{API}/finance/", json=base, headers=h))
    assert ok["purchase_order_id"] == po["id"]
    # Moving the vendor under a link that stays is weighed like a new link.
    resp = await client.patch(f"{API}/finance/{ok['id']}", json={"contact_id": other_vendor}, headers=h)
    assert resp.status_code == 422, resp.text
    # Unlinking is a plain update.
    unlinked = await _ok(await client.patch(f"{API}/finance/{ok['id']}", json={"purchase_order_id": None}, headers=h))
    assert unlinked["purchase_order_id"] is None


async def _budget_rows(client: AsyncClient, h: dict[str, str], project_id: uuid.UUID) -> dict[str, dict]:
    body = await _ok(await client.get(f"{API}/finance/budgets/?project_id={project_id}", headers=h))
    items = body["items"] if isinstance(body, dict) else body
    return {row["wbs_id"]: row for row in items}


@pytest.mark.asyncio
async def test_budget_lines_keep_their_own_actual_and_commitment(client: AsyncClient) -> None:
    """Each paid amount lands on one budget line, net; an order commits net and is spent once.

    Before: the order committed its gross, so after full delivery its VAT
    stayed in committed; and every payment wrote the project's whole paid
    gross into ``actual`` on every line, so two lines showed twice the spend.
    """
    owner, h = await _login(client)
    project_id, boq_id = await _seed_project_and_bill(owner)
    await _ok(await client.post(f"{API}/boq/boqs/{boq_id}/lock/", headers=h))
    vendor = await _supplier(client, h)
    po = await _order(client, h, project_id, vendor)
    rows = await _budget_rows(client, h, project_id)
    assert set(rows) == {"01", "02"}
    # The order commits its net on the line of its WBS, not the 62 500 gross.
    assert _money(rows["02"]["committed"]) == Decimal("50000")

    await _issue_and_receive(client, h, po)
    await _supplier_invoices(client, h, project_id, vendor, po)
    split = await _ok(
        await client.post(
            f"{API}/finance/",
            json={
                "project_id": str(project_id),
                "contact_id": vendor,
                "invoice_direction": "payable",
                "invoice_number": "R-2026-140",
                "invoice_date": "2026-09-24",
                "currency_code": "EUR",
                "amount_subtotal": "4000.00",
                "tax_amount": "1000.00",
                "amount_total": "5000.00",
                "line_items": [
                    {"description": "Survey pegs", "amount": "1000.00", "wbs_id": "01", "vat_rate": "25"},
                    {"description": "Formwork ties", "amount": "3000.00", "wbs_id": "02", "vat_rate": "25"},
                ],
            },
            headers=h,
        )
    )
    await _ok(await client.post(f"{API}/finance/{split['id']}/approve/", headers=h))
    await _ok(await client.post(f"{API}/finance/{split['id']}/pay/", headers=h))

    rows = await _budget_rows(client, h, project_id)
    actual = {wbs: _money(row["actual"]) for wbs, row in rows.items()}
    committed = {wbs: _money(row["committed"]) for wbs, row in rows.items()}
    # 02: 40 000 received on the order (its paid invoice is the same money)
    # plus 3 000 of the split invoice; 01: its 1 000 line. Net throughout.
    assert actual == {"01": Decimal("1000"), "02": Decimal("43000")}
    # 02: the order's 50 000 less the 40 000 received and paid, 10 000 still
    # open. 01: the unpaid container hire, 2 000, which names no WBS and so
    # lands on the first line (there is no project-level line here).
    assert committed == {"01": Decimal("2000"), "02": Decimal("10000")}


@pytest.mark.asyncio
async def test_a_budget_line_keyed_by_a_bill_section_shows_its_name(client: AsyncClient) -> None:
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.boq.models import Position

    owner, h = await _login(client)
    project_id, boq_id = await _seed_project_and_bill(owner)
    async with async_session_factory() as s:
        section_id = (
            await s.execute(select(Position.id).where(Position.boq_id == boq_id, Position.ordinal == "02"))
        ).scalar_one()
    await _ok(
        await client.post(
            f"{API}/finance/budgets/",
            json={
                "project_id": str(project_id),
                "wbs_id": str(section_id),
                "category": "material",
                "original_budget": "1000",
                "currency_code": "EUR",
            },
            headers=h,
        )
    )
    body = await _ok(await client.get(f"{API}/finance/budgets/?project_id={project_id}", headers=h))
    row = next(r for r in body["items"] if r["wbs_id"] == str(section_id))
    assert row["wbs_label"] == "02 Concrete works"


@pytest.mark.asyncio
@pytest.mark.parametrize(("country", "expected"), [("HR", "25"), ("DE", "19")])
async def test_an_invoice_line_without_a_vat_rate_gets_the_project_country_rate(
    client: AsyncClient, country: str, expected: str
) -> None:
    owner, h = await _login(client)
    project_id, _ = await _seed_project_and_bill(owner, country=country)
    vendor = await _supplier(client, h)
    created = await _ok(
        await client.post(
            f"{API}/finance/",
            json={
                "project_id": str(project_id),
                "contact_id": vendor,
                "invoice_direction": "payable",
                "invoice_date": "2026-09-24",
                "currency_code": "EUR",
                "amount_subtotal": "300.00",
                "line_items": [
                    {"description": "No rate given", "amount": "100.00"},
                    {"description": "Reduced rate", "amount": "100.00", "vat_rate": "13"},
                    {"description": "Exempt", "amount": "100.00", "vat_rate": "0"},
                ],
            },
            headers=h,
        )
    )
    rates = {line["description"]: line["vat_rate"] for line in created["line_items"]}
    assert Decimal(str(rates["No rate given"])) == Decimal(expected)
    assert Decimal(str(rates["Reduced rate"])) == Decimal("13")
    assert Decimal(str(rates["Exempt"])) == Decimal("0")


@pytest.mark.asyncio
async def test_a_subcontract_billed_through_a_payable_invoice_is_committed_and_incurred_once(
    client: AsyncClient,
) -> None:
    """120 000 signed, 5 % retention, a 30 % payment application billed as one payable invoice.

    The invoice is the only money record for the pay application: 36 000 net,
    1 800 retention. Paid with the retention withheld (34 200 cash), the
    whole 36 000 is incurred, since the retention is owed and only paid later;
    84 000 stays open. The rows add up to the dashboard at every step, and the
    5D actual gets the 36 000 once: the cash leg of the payment used to be
    posted as well, putting 70 200 there.
    """
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.costmodel.models import BudgetLine

    owner, h = await _login(client)
    project_id, boq_id = await _seed_project_and_bill(owner)
    await _ok(await client.post(f"{API}/boq/boqs/{boq_id}/lock/", headers=h))
    agreement = await _active_agreement(client, h, project_id)
    vendor = await _supplier(client, h)

    invoice = await _ok(
        await client.post(
            f"{API}/finance/",
            json={
                "project_id": str(project_id),
                "contact_id": vendor,
                "invoice_direction": "payable",
                "invoice_number": "PA-001",
                "invoice_date": "2026-09-24",
                "currency_code": "EUR",
                "amount_subtotal": "36000.00",
                "tax_amount": "0.00",
                "retention_amount": "1800.00",
                "amount_total": "36000.00",
                "metadata": {"agreement_id": agreement["id"]},
                "line_items": [{"description": "Payment application 1, 30 %", "amount": "36000.00", "vat_rate": "0"}],
            },
            headers=h,
        )
    )
    dash = await _assert_rows_match_dashboard(client, h, project_id)
    assert (_money(dash["total_committed"]), _money(dash["total_actual"])) == (Decimal("120000"), Decimal("0"))

    await _ok(await client.post(f"{API}/finance/{invoice['id']}/approve/", headers=h))
    await _ok(
        await client.post(
            f"{API}/finance/invoices/{invoice['id']}/record-payment/",
            json={"payment_date": "2026-09-25", "currency_code": "EUR"},
            headers=h,
        )
    )
    dash = await _assert_rows_match_dashboard(client, h, project_id)
    assert (_money(dash["total_committed"]), _money(dash["total_actual"])) == (Decimal("84000"), Decimal("36000"))
    assert _money(dash["total_paid"]) == Decimal("34200")

    await _ok(await client.post(f"{API}/finance/{invoice['id']}/pay/", headers=h))
    dash = await _assert_rows_match_dashboard(client, h, project_id)
    assert (_money(dash["total_committed"]), _money(dash["total_actual"])) == (Decimal("84000"), Decimal("36000"))

    async with async_session_factory() as s:
        spine = (await s.execute(select(BudgetLine.actual_amount).where(BudgetLine.project_id == project_id))).all()
    assert sum((_money(row[0]) for row in spine), Decimal("0")) == Decimal("36000")
