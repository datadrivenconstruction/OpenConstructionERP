# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""The Riyadh and US medical demos open on records, not on empty screens.

What is pinned: the Saudi clearance document and the withholding register are
written from the pack's own declaration, the schedule carries a baseline, a
data date and monthly progress, the earned-value indices sit near 1, and the
US hospital is priced as a US hospital (cost per ft2, US units, sales tax).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.demo_projects import DEMO_TEMPLATES, install_demo_project
from app.modules.costmodel.models import CostSnapshot
from app.modules.einvoice_clearance.models import EInvoiceDocument
from app.modules.einvoice_clearance.seed import seed_einvoice_clearance_demo
from app.modules.schedule.evm_demo import seed_schedule_evm_demo
from app.modules.schedule.models import ProgressUpdate, Schedule, ScheduleBaseline
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
