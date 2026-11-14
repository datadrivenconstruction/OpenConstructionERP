# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""The Riyadh and US medical demos open on records, not on empty screens.

What is pinned: the Saudi clearance document and the withholding register are
written from the pack's own declaration, the schedule carries a baseline, a
data date and monthly progress, the earned-value indices sit near 1, and the
US hospital is priced as a US hospital (cost per ft2, US units, sales tax).
"""

from __future__ import annotations

import re
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.demo_projects import DEMO_TEMPLATES, install_demo_project
from app.core.demo_vat import demo_vat_rate
from app.modules.costmodel.cashflow_forecast_demo import project_contract_value, seed_cashflow_forecast_demo
from app.modules.costmodel.models import CostSnapshot
from app.modules.einvoice_clearance.models import EInvoiceDocument
from app.modules.einvoice_clearance.seed import seed_einvoice_clearance_demo
from app.modules.finance.models import Invoice
from app.modules.procurement.models import PurchaseOrder
from app.modules.schedule.evm_demo import seed_schedule_evm_demo
from app.modules.schedule.models import Activity, ProgressUpdate, Schedule, ScheduleBaseline
from app.modules.tax_withholding.models import WithholdingDeduction
from app.modules.tax_withholding.seed import seed_tax_withholding_demo

pytestmark = pytest.mark.asyncio


async def _install(session, demo_id: str) -> uuid.UUID:
    result = await install_demo_project(session, demo_id)
    await session.flush()
    return uuid.UUID(str(result["project_id"]))


async def test_riyadh_gets_a_zatca_document_and_a_withholding_register(pg_session) -> None:
    pid = await _install(pg_session, "full-showcase-riyadh")

    counts = await seed_einvoice_clearance_demo(pg_session, [pid])
    assert counts.get("documents") == 1, counts
    doc = (await pg_session.execute(select(EInvoiceDocument))).scalar_one()
    assert doc.country == "SA"

    declared = DEMO_TEMPLATES["full-showcase-riyadh"].withholding_showcase
    written = await seed_tax_withholding_demo(pg_session, [pid])
    assert written.get("deductions") == len(declared["payments"])
    rows = (
        (await pg_session.execute(select(WithholdingDeduction).where(WithholdingDeduction.project_id == pid)))
        .scalars()
        .all()
    )
    assert {r.status for r in rows} >= {"returned", "remitted", "calculated", "draft"}
    # The related-party fee is withheld at the management-fee band, not the services one.
    fee = next(r for r in rows if r.band_code == "MANAGEMENT_FEE")
    assert fee.rate_pct == Decimal("20")
    assert fee.tax_withheld == fee.taxable_base * Decimal("0.20")
    # Re-running adds nothing.
    assert await seed_tax_withholding_demo(pg_session, [pid]) == {}


@pytest.mark.parametrize("demo_id", ["full-showcase-riyadh", "medical-us"])
async def test_schedule_history_is_written_and_indices_are_credible(pg_session, demo_id: str) -> None:
    pid = await _install(pg_session, demo_id)
    counts = await seed_schedule_evm_demo(pg_session, [pid])
    assert counts.get("baselines") == 1, counts

    schedule = (await pg_session.execute(select(Schedule).where(Schedule.project_id == pid))).scalars().first()
    assert schedule.data_date, "no data date"
    baselines = (await pg_session.execute(select(func.count()).select_from(ScheduleBaseline))).scalar_one()
    updates = (await pg_session.execute(select(func.count()).select_from(ProgressUpdate))).scalar_one()
    assert baselines >= 1 and updates > 0

    last = (
        (
            await pg_session.execute(
                select(CostSnapshot).where(CostSnapshot.project_id == pid).order_by(CostSnapshot.period)
            )
        )
        .scalars()
        .all()[-1]
    )
    assert Decimal("0.90") <= Decimal(last.spi) <= Decimal("1.05"), last.spi
    assert Decimal("0.95") <= Decimal(last.cpi) <= Decimal("1.05"), last.cpi
    assert await seed_schedule_evm_demo(pg_session, [pid]) == {}


def test_us_hospital_is_priced_per_square_foot_in_us_units() -> None:
    tpl = DEMO_TEMPLATES["medical-us"]
    ft2 = tpl.project_metadata["area_ft2"]
    direct = sum(Decimal(str(q)) * Decimal(str(r)) for _, _, _, items in tpl.sections for _, _, _, q, r, _ in items)
    markup = sum(Decimal(str(m[1])) for m in tpl.markups if m[3] == "direct_cost")
    total = direct * (1 + markup / 100) * Decimal("1.015")
    assert 900 <= total / ft2 <= 1300, f"USD {total / ft2:.0f} per ft2"
    units = {u for _, _, _, items in tpl.sections for _, _, u, _, _, _ in items}
    assert units <= {"lsum", "ft2", "cy", "ton_us", "ea", "lf"}, units
    tax = [m for m in tpl.markups if m[2] == "tax"]
    assert tax and "Texas" in tax[0][0]
    assert "sales_tax_note" in tpl.boq_metadata


@pytest.mark.parametrize(
    ("demo_id", "currency"),
    [("office-london", "GBP"), ("medical-us", "USD"), ("office-shanghai", "CNY"), ("condo-toronto", "CAD")],
)
async def test_generic_invoices_and_order_scale_with_the_project_and_carry_its_tax(
    pg_session, demo_id: str, currency: str
) -> None:
    pid = await _install(pg_session, demo_id)
    value = await project_contract_value(pg_session, pid)
    direct = sum(
        Decimal(str(q)) * Decimal(str(r))
        for _, _, _, items in DEMO_TEMPLATES[demo_id].sections
        for _, _, _, q, r, _ in items
    )
    assert abs(value - direct) <= direct * Decimal("0.001")
    assert await seed_cashflow_forecast_demo(pg_session, pid, dip=True) > 0

    rate = demo_vat_rate(currency)
    assert rate > 0
    rows = (await pg_session.execute(select(Invoice).where(Invoice.project_id == pid))).scalars().all()
    invoices = [inv for inv in rows if (inv.metadata_ or {}).get("demo_seed") == "cashflow_forecast_demo"]
    assert invoices
    for inv in invoices:
        net = Decimal(inv.amount_subtotal)
        assert Decimal(inv.tax_amount) == (net * rate).quantize(Decimal("0.01")), inv.invoice_number
        assert value * Decimal("0.001") <= net <= value * Decimal("0.2"), (inv.invoice_number, net, value)

    order = (
        (
            await pg_session.execute(
                select(PurchaseOrder).where(PurchaseOrder.project_id == pid).order_by(PurchaseOrder.po_number.desc())
            )
        )
        .scalars()
        .first()
    )
    assert order.vendor_contact_id, "the generic order names no vendor"
    assert order.notes and "supply" in order.notes
    assert Decimal(order.amount_subtotal) == (value * Decimal("0.12")).quantize(Decimal("0.01"))


@pytest.mark.parametrize("demo_id", ["full-showcase-riyadh", "warehouse-dubai"])
async def test_riyadh_and_dubai_carry_vat_retention_dates_and_a_consistent_programme(pg_session, demo_id: str) -> None:
    from datetime import date

    pid = await _install(pg_session, demo_id)
    rate = demo_vat_rate(DEMO_TEMPLATES[demo_id].currency)
    assert rate > 0
    for inv in (await pg_session.execute(select(Invoice).where(Invoice.project_id == pid))).scalars():
        assert Decimal(inv.tax_amount) == (Decimal(inv.amount_subtotal) * rate).quantize(Decimal("0.01"))
        assert inv.invoice_date <= date.today().isoformat(), inv.invoice_number
    for po in (await pg_session.execute(select(PurchaseOrder).where(PurchaseOrder.project_id == pid))).scalars():
        assert re.fullmatch(r"\d+\.\d{2}", po.amount_subtotal), po.amount_subtotal
        assert Decimal(po.tax_amount) == (Decimal(po.amount_subtotal) * rate).quantize(Decimal("0.01"))
    schedule = (await pg_session.execute(select(Schedule).where(Schedule.project_id == pid))).scalars().first()
    root = (
        (
            await pg_session.execute(
                select(Activity).where(Activity.schedule_id == schedule.id, Activity.parent_id.is_(None))
            )
        )
        .scalars()
        .one()
    )
    assert (schedule.start_date, schedule.end_date) == (root.start_date, root.end_date)
