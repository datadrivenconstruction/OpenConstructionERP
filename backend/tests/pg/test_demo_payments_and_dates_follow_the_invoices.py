# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""A demo project's payments settle its own paid invoices, and no document is dated after the install day.

Berlin carried seven paid invoices and six payments, and Berlin and Paris carried the same payment amounts, because
the payments came from a forecast seed that wrote its own invoices and the invoices of the install itself were never
settled. Each paid invoice now has exactly one payment, and a sent or paid document is never dated in the future.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.core.demo_projects import install_demo_project
from app.modules.finance.models import Invoice, Payment
from app.modules.schedule.models import Activity, Schedule

pytestmark = pytest.mark.asyncio

_DEMOS = ("residential-berlin", "school-paris", "condo-toronto")


@pytest.mark.parametrize("demo_id", _DEMOS)
async def test_each_paid_invoice_has_one_payment_and_none_is_dated_ahead(pg_session, demo_id: str) -> None:
    project_id = (await install_demo_project(pg_session, demo_id))["project_id"]
    await pg_session.flush()
    today = datetime.now(UTC).strftime("%Y-%m-%d")

    invoices = (await pg_session.execute(select(Invoice).where(Invoice.project_id == project_id))).scalars().all()
    paid = [i for i in invoices if i.status == "paid"]
    assert paid, demo_id
    payments = (
        await pg_session.execute(select(func.count(Payment.id)).where(Payment.invoice_id.in_([i.id for i in paid])))
    ).scalar_one()
    assert payments == len(paid), demo_id
    assert not [i.invoice_number for i in invoices if i.status in ("paid", "sent") and i.invoice_date > today]


async def test_toronto_concrete_starts_after_the_excavation_finishes(pg_session) -> None:
    project_id = (await install_demo_project(pg_session, "condo-toronto"))["project_id"]
    await pg_session.flush()
    schedule_id = (await pg_session.execute(select(Schedule.id).where(Schedule.project_id == project_id))).scalar_one()
    phases = (
        (
            await pg_session.execute(
                select(Activity)
                .where(Activity.schedule_id == schedule_id, Activity.activity_type != "summary")
                .order_by(Activity.sort_order)
            )
        )
        .scalars()
        .all()
    )
    assert len(phases) > 1
    for before, after in zip(phases, phases[1:], strict=False):
        assert after.start_date > before.end_date, (before.name, after.name)
