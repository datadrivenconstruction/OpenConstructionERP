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
* committed: net. Each order at its net value, each live agreement at its
  value, and a supplier invoice that no order stands behind at its own net
  (money spent without an order is committed the day it is invoiced). An order
  and its invoice are one commitment, never two; a payment application draws
  down its agreement and is not a second commitment.
  50 000 + 120 000 + 2 000 = 172 000.
* invoiced: net. Supplier invoices at their subtotal, payment applications at
  the gross finance approved (before retention, which is still owed).
  40 000 + 2 000 + 30 000 = 72 000.
* paid (``total_paid``): cash out, VAT included, as the bank sees it.
  50 000 + 28 500 = 78 500.
* actual (``total_actual``): what has been paid, net of VAT, so it compares
  with a net budget. 40 000 + 28 500 = 68 500.
* ``total_payable`` keeps its meaning: supplier invoices not yet marked paid,
  gross. 2 500.
* ``total_payments`` keeps its meaning: every payment row, either direction.

The order-first variant approves the purchase order before any bill is
locked, which is the order a busy site works in. A commitment counter that
needs a budget row to exist loses the order in that case.
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


async def _seed_project_and_bill(owner_id: str) -> tuple[uuid.UUID, uuid.UUID]:
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


async def _subcontract(client: AsyncClient, h: dict[str, str], project_id: uuid.UUID) -> None:
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


def _assert_position(dash: dict) -> None:
    """Every figure of the scenario, with its basis named in the message."""
    expected = {
        "total_budget_original": "400000",  # net, locked bill leaves only
        "total_budget_revised": "400000",
        "total_committed": "172000",  # net: order 50k + agreement 120k + unordered invoice 2k
        "total_invoiced": "72000",  # net: 40k + 2k supplier, 30k approved pay app gross
        "total_paid": "78500",  # cash: 50k incl. VAT + 28.5k sub net of retention
        "total_actual": "68500",  # paid, net of VAT: 40k + 28.5k
        "total_payable": "2500",  # unpaid supplier invoices, gross
        "total_payments": "50000",  # finance payment rows, any direction
    }
    wrong = {k: (dash.get(k), v) for k, v in expected.items() if dash.get(k) is None or _money(dash[k]) != Decimal(v)}
    assert not wrong, f"figures that do not roll up, as (got, expected): {wrong}"
    assert dash["currency"] == "EUR"
    assert dash["mixed_currencies"] is False
    assert Decimal(str(dash["budget_consumed_pct"])) == Decimal("17.1")  # 68 500 / 400 000
    # Committed 172k of 400k is 43 %, well under the caution line.
    assert dash["budget_warning_level"] == "normal"
    assert _money(dash["total_variance"]) == Decimal("228000")  # 400k budget less 172k committed
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
    await _issue_and_receive(client, h, po)
    await _supplier_invoices(client, h, project_id, vendor, po)
    await _subcontract(client, h, project_id)

    _assert_position(await _dashboard(client, h, project_id))

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
    await _issue_and_receive(client, h, po)
    await _supplier_invoices(client, h, project_id, vendor, po)
    await _subcontract(client, h, project_id)

    _assert_position(await _dashboard(client, h, project_id))


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

    # The dashboard counts the order once: 50 000 order vs 45 000 invoiced on it.
    dash = await _dashboard(client, h, project_id)
    assert Decimal(dash["total_committed"]) == Decimal("50000")
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
