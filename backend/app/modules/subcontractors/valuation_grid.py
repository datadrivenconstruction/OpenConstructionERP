"""Submitted / assessed / certified grid of one subcontractor payment application.

The claimed and certified amounts are stored on the line. The assessed amount
is the assessed quantity at the line's own claimed rate (claimed amount over
claimed quantity), and is left empty when nothing was claimed by quantity.
The running total is the claimed quantity of this work package over every
earlier application of the agreement that was not rejected, plus this one.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.valuation_grid import GridLine, grid_with_findings
from app.modules.subcontractors.models import PaymentApplication, PaymentApplicationLine, WorkPackage

NOTE_KEY = "valuation_note"


def application_note(app: PaymentApplication) -> str:
    """The valuation note kept in the application's metadata."""
    meta = app.metadata_ if isinstance(app.metadata_, dict) else {}
    return str(meta.get(NOTE_KEY) or "")


async def build_application_grid(session: AsyncSession, app: PaymentApplication) -> dict[str, Any]:
    """The grid of ``app`` with findings, ready for :class:`ValuationGridResponse`."""
    lines = list(
        (
            await session.execute(
                select(PaymentApplicationLine).where(PaymentApplicationLine.payment_application_id == app.id)
            )
        )
        .scalars()
        .all()
    )
    packages = {
        wp.id: wp
        for wp in (await session.execute(select(WorkPackage).where(WorkPackage.agreement_id == app.agreement_id)))
        .scalars()
        .all()
    }
    earlier = (
        (
            await session.execute(
                select(PaymentApplicationLine)
                .join(PaymentApplication, PaymentApplication.id == PaymentApplicationLine.payment_application_id)
                .where(
                    PaymentApplication.agreement_id == app.agreement_id,
                    PaymentApplication.id != app.id,
                    PaymentApplication.status != "rejected",
                    PaymentApplication.created_at < app.created_at,
                )
            )
        )
        .scalars()
        .all()
    )
    prior_claimed: dict[Any, Decimal] = {}
    prior_cert: dict[Any, Decimal] = {}
    for row in earlier:
        prior_claimed[row.work_package_id] = prior_claimed.get(row.work_package_id, Decimal("0")) + Decimal(
            str(row.claimed_qty)
        )
        prior_cert[row.work_package_id] = prior_cert.get(row.work_package_id, Decimal("0")) + Decimal(
            str(row.certified_qty)
        )
    grid_lines: list[GridLine] = []
    for ln in lines:
        wp = packages.get(ln.work_package_id)
        claimed_qty = Decimal(str(ln.claimed_qty))
        claimed_amount = Decimal(str(ln.claimed_amount))
        rate = (claimed_amount / claimed_qty).quantize(Decimal("0.0001")) if claimed_qty > 0 else None
        prior = prior_claimed.get(ln.work_package_id)
        grid_lines.append(
            GridLine(
                id=str(ln.id),
                label=(wp.name if wp is not None else "") or str(ln.work_package_id),
                submitted_qty=claimed_qty,
                assessed_qty=Decimal(str(ln.assessed_qty)),
                certified_qty=Decimal(str(ln.certified_qty)),
                rate=rate,
                rate_source="claimed_amount/claimed_qty" if rate is not None else None,
                submitted_amount=claimed_amount,
                submitted_amount_field="claimed_amount",
                certified_amount=Decimal(str(ln.certified_amount)),
                certified_amount_field="certified_amount",
                prior_certified_qty=prior_cert.get(ln.work_package_id, Decimal("0")),
                prior_cumulative=prior,
                cumulative=(prior or Decimal("0")) + claimed_qty,
                cumulative_field="claimed_qty",
            )
        )
    note = application_note(app)
    grid = await grid_with_findings(grid_lines, note=note, target_type="sub_payment_application", target_id=str(app.id))
    return {
        "source_kind": "sub_payment_application",
        "source_id": str(app.id),
        "document_number": app.application_number or "",
        "status": app.status,
        "currency": app.currency or "",
        "note": note,
        **grid,
    }
