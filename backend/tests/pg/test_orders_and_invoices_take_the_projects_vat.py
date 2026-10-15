# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: purchase orders and invoices are taxed at the project's default VAT rate (issue #515).

Project Settings holds a default VAT rate. A new purchase order ignored it and
was saved with a tax of 0, and an invoice line without a rate took the country
rate from the jurisdiction registry instead of the one the project set.

What must hold:

* a new order that states neither a rate nor a tax takes the project rate, and
  its tax is the subtotal at that rate, to the cent;
* a rate the caller states wins over the project's, and an absolute tax stated
  without a rate is kept as it was before the rate existed;
* an invoice line without a rate takes the project's rate before the country's;
* changing the project's default edits nothing that already exists;
* only the opt-in re-apply moves documents, and only drafts. On an invoice it
  moves lines with no rate or with the previous default, and keeps a line at
  any other rate, which somebody set on purpose.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.modules.finance.models import Invoice, InvoiceLineItem
from app.modules.finance.schemas import InvoiceCreate, InvoiceLineItemCreate
from app.modules.finance.service import FinanceService, reapply_vat_rate_to_draft_invoices
from app.modules.procurement.models import PurchaseOrder
from app.modules.procurement.schemas import POCreate, POItemCreate, POUpdate
from app.modules.procurement.service import ProcurementService, reapply_vat_rate_to_draft_pos
from app.modules.projects.models import Project
from app.modules.users.models import User


async def _project(session, *, vat: str | None, country: str = "DE") -> Project:
    owner = User(email=f"vat515-{uuid.uuid4().hex[:8]}@example.test", hashed_password="x", full_name="VAT")
    session.add(owner)
    await session.flush()
    project = Project(
        name="VAT 515",
        owner_id=owner.id,
        currency="EUR",
        country_code=country,
        default_vat_rate=vat,
    )
    session.add(project)
    await session.flush()
    return project


def _order(project: Project, **overrides: object) -> POCreate:
    data: dict[str, object] = {
        "project_id": project.id,
        "currency_code": "EUR",
        "items": [
            POItemCreate(description="Rebar", quantity="3", unit="t", unit_rate="333.33", amount="0"),
        ],
    }
    data.update(overrides)
    return POCreate(**data)


# ── Purchase orders ──────────────────────────────────────────────────────────


async def test_a_new_order_takes_the_projects_rate(pg_session) -> None:
    project = await _project(pg_session, vat="5")

    po = await ProcurementService(pg_session).create_po(_order(project))

    assert po.tax_rate_pct == "5"
    assert Decimal(po.amount_subtotal) == Decimal("999.99")
    # 999.99 x 5% = 49.9995, half-up to the cent.
    assert Decimal(po.tax_amount) == Decimal("50.00")
    assert Decimal(po.amount_total) == Decimal("1049.99")


async def test_a_stated_rate_wins_over_the_projects(pg_session) -> None:
    project = await _project(pg_session, vat="5")

    po = await ProcurementService(pg_session).create_po(_order(project, tax_rate_pct="20", tax_amount="1"))

    assert po.tax_rate_pct == "20"
    assert Decimal(po.tax_amount) == Decimal("200.00")


async def test_a_stated_absolute_tax_is_kept_without_a_rate(pg_session) -> None:
    project = await _project(pg_session, vat="5")

    po = await ProcurementService(pg_session).create_po(_order(project, tax_amount="12.34"))

    assert po.tax_rate_pct is None
    assert Decimal(po.tax_amount) == Decimal("12.34")


async def test_a_project_without_a_rate_leaves_the_order_as_before(pg_session) -> None:
    project = await _project(pg_session, vat=None)

    po = await ProcurementService(pg_session).create_po(_order(project))

    assert po.tax_rate_pct is None
    assert Decimal(po.tax_amount) == Decimal("0")


async def test_a_rate_set_on_an_existing_draft_re_derives_its_tax(pg_session) -> None:
    project = await _project(pg_session, vat=None)
    service = ProcurementService(pg_session)
    po = await service.create_po(_order(project))

    updated = await service.update_po(po.id, POUpdate(tax_rate_pct="10"))

    assert updated.tax_rate_pct == "10"
    assert Decimal(updated.tax_amount) == Decimal("100.00")
    assert Decimal(updated.amount_total) == Decimal("1099.99")


async def test_changing_the_projects_rate_edits_no_order(pg_session) -> None:
    project = await _project(pg_session, vat="5")
    po = await ProcurementService(pg_session).create_po(_order(project))
    po_id = po.id

    project.default_vat_rate = "21"
    await pg_session.flush()
    pg_session.expire_all()

    stored = (await pg_session.execute(select(PurchaseOrder).where(PurchaseOrder.id == po_id))).scalar_one()
    assert stored.tax_rate_pct == "5"
    assert Decimal(stored.tax_amount) == Decimal("50.00")


async def test_the_re_apply_moves_draft_orders_only(pg_session) -> None:
    project = await _project(pg_session, vat="5")
    service = ProcurementService(pg_session)
    draft = await service.create_po(_order(project))
    approved = await service.create_po(_order(project))
    approved.status = "approved"
    await pg_session.flush()
    project_id, draft_id, approved_id = project.id, draft.id, approved.id

    count = await reapply_vat_rate_to_draft_pos(pg_session, project_id, "21")

    assert count == 1
    pg_session.expire_all()
    rows = {
        po.id: po
        for po in (await pg_session.execute(select(PurchaseOrder).where(PurchaseOrder.project_id == project_id)))
        .scalars()
        .all()
    }
    assert rows[draft_id].tax_rate_pct == "21"
    assert Decimal(rows[draft_id].tax_amount) == Decimal("210.00")
    assert Decimal(rows[draft_id].amount_total) == Decimal("1209.99")
    assert rows[approved_id].tax_rate_pct == "5"
    assert Decimal(rows[approved_id].tax_amount) == Decimal("50.00")
    # A second run finds nothing left to change.
    assert await reapply_vat_rate_to_draft_pos(pg_session, project_id, "21") == 0


# ── Invoices ─────────────────────────────────────────────────────────────────


def _invoice(project: Project, lines: list[InvoiceLineItemCreate], **overrides: object) -> InvoiceCreate:
    subtotal = sum((Decimal(line.amount) for line in lines), Decimal("0"))
    data: dict[str, object] = {
        "project_id": project.id,
        "invoice_direction": "payable",
        "invoice_date": "2026-10-01",
        "currency_code": "EUR",
        "amount_subtotal": str(subtotal),
        "line_items": lines,
    }
    data.update(overrides)
    return InvoiceCreate(**data)


async def _line_rates(session, invoice_id: uuid.UUID) -> list[Decimal | None]:
    rows = (
        (
            await session.execute(
                select(InvoiceLineItem)
                .where(InvoiceLineItem.invoice_id == invoice_id)
                .order_by(InvoiceLineItem.sort_order)
            )
        )
        .scalars()
        .all()
    )
    return [None if row.vat_rate is None else Decimal(row.vat_rate).normalize() for row in rows]


async def test_an_invoice_line_without_a_rate_takes_the_projects_before_the_countrys(pg_session) -> None:
    # Germany would give 19; the project says 5.
    project = await _project(pg_session, vat="5", country="DE")

    invoice = await FinanceService(pg_session).create_invoice(
        _invoice(project, [InvoiceLineItemCreate(description="Works", quantity="1", unit_rate="100", amount="100")])
    )

    assert await _line_rates(pg_session, invoice.id) == [Decimal("5")]


@pytest.mark.parametrize("status", ["pending", "paid"])
async def test_the_re_apply_moves_draft_invoices_only(pg_session, status: str) -> None:
    project = await _project(pg_session, vat="5")
    finance = FinanceService(pg_session)

    def lines() -> list[InvoiceLineItemCreate]:
        return [
            InvoiceLineItemCreate(description="Standard", quantity="1", unit_rate="1000", amount="1000", vat_rate="5"),
            InvoiceLineItemCreate(description="Reduced", quantity="1", unit_rate="200", amount="200", vat_rate="2"),
        ]

    draft = await finance.create_invoice(_invoice(project, lines(), tax_amount="54.00"))
    other = await finance.create_invoice(_invoice(project, lines(), tax_amount="54.00"))
    other.status = status
    await pg_session.flush()
    project_id, draft_id, other_id = project.id, draft.id, other.id

    count = await reapply_vat_rate_to_draft_invoices(pg_session, project_id, "21", "5")

    assert count == 1
    pg_session.expire_all()
    assert await _line_rates(pg_session, draft_id) == [Decimal("21"), Decimal("2")]
    assert await _line_rates(pg_session, other_id) == [Decimal("5"), Decimal("2")]
    stored = {
        inv.id: inv
        for inv in (await pg_session.execute(select(Invoice).where(Invoice.project_id == project_id))).scalars().all()
    }
    # 1000 x 21% + 200 x 2% = 210 + 4.
    assert Decimal(stored[draft_id].tax_amount) == Decimal("214.00")
    assert Decimal(stored[draft_id].amount_total) == Decimal("1414.00")
    assert Decimal(stored[other_id].tax_amount) == Decimal("54.00")
