# DDC-CWICR-OE: DataDrivenConstruction​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Demo data for the cash-flow forecast on the existing demo projects.

Per demo project, in its own currency, relative to today so the picture never
goes stale: a client contract with a payment plan and 5 % retention, a
subcontract spread over the works, one purchase order, three months of paid
invoices on both sides and one client invoice past its due date. The
``dip`` project gets a back-loaded payment plan, so its cash position goes
negative mid-way and recovers at the end. Every row carries the marker below;
a project that already has it is left alone.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.costmodel.cashflow_forecast import month_end, q2

MARKER = "cashflow_forecast_demo"
CONTRACT_VALUE = Decimal("2400000")

#: (months from start, share of the contract) of the payment plan.
_EVEN_PLAN = [(m, Decimal(1) / Decimal(12)) for m in range(5, 13)]
_DIP_PLAN = [(6, Decimal("0.15")), (9, Decimal("0.25")), (12, Decimal("0.27"))]


def _shift(day: date, months: int) -> date:
    idx = day.year * 12 + day.month - 1 + months
    return date(idx // 12, idx % 12 + 1, min(day.day, 28))


async def seed_cashflow_forecast_demo(
    session: AsyncSession, project_id: uuid.UUID, *, dip: bool, today: date | None = None
) -> int:
    """Write the demo rows for one project; returns the number of rows written (0 when already seeded)."""
    from app.modules.contracts.models import Contract, ContractMilestone
    from app.modules.finance.models import Invoice, Payment
    from app.modules.procurement.models import PurchaseOrder
    from app.modules.projects.models import Project
    from app.modules.subcontractors.models import SubcontractAgreement, Subcontractor

    project = await session.get(Project, project_id)
    if project is None:
        return 0
    seeded = (
        await session.execute(select(Contract.id, Contract.metadata_).where(Contract.project_id == project_id))
    ).all()
    if any((meta or {}).get("demo_seed") == MARKER for _, meta in seeded):
        return 0
    today = today or date.today()
    currency = (project.currency or "EUR").upper()[:3]
    start = _shift(today, -4)
    end = _shift(today, 8)
    value = CONTRACT_VALUE
    meta = {"demo_seed": MARKER}
    tag = project_id.hex[:8].upper()
    rows: list[object] = []

    contract = Contract(
        code=f"CF-{tag}-CLIENT",
        title="Main contract",
        contract_type="lump_sum",
        counterparty_type="client",
        project_id=project_id,
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        total_value=value,
        currency=currency,
        retention_percent=Decimal("5.00"),
        status="active",
        terms={"payment_terms": {"payment_period_days": 30}},
        metadata_=meta,
    )
    session.add(contract)
    await session.flush()
    rows.append(contract)
    # The first third is billed and paid already: three paid client invoices.
    billed = q2(value / Decimal(3))
    for idx, (months, share) in enumerate(_DIP_PLAN if dip else _EVEN_PLAN, start=1):
        rows.append(
            ContractMilestone(
                contract_id=contract.id,
                code=f"M{idx:02d}",
                name=f"Payment stage {idx}",
                planned_date=_shift(start, months).isoformat(),
                value=q2(
                    (value - billed) * share / sum((s for _, s in (_DIP_PLAN if dip else _EVEN_PLAN)), Decimal(0))
                ),
                trigger="date",
                status="pending",
                payment_terms_days=30,
                metadata_=meta,
            )
        )

    sub = Subcontractor(legal_name="Demo Structures Ltd", metadata_=meta)
    session.add(sub)
    await session.flush()
    rows.append(sub)
    sub_value = q2(value * Decimal("0.55"))
    rows.append(
        SubcontractAgreement(
            subcontractor_id=sub.id,
            project_id=project_id,
            title="Structure and envelope",
            total_value=sub_value,
            currency=currency,
            start_date=today,
            end_date=_shift(today, 6) if dip else end,
            retention_percent=Decimal("5.00"),
            status="active",
            metadata_={**meta, "payment_terms_days": 30},
        )
    )
    po_value = q2(value * Decimal("0.12"))
    rows.append(
        PurchaseOrder(
            project_id=project_id,
            po_number=f"CF-{tag}-PO1",
            currency_code=currency,
            amount_subtotal=str(po_value),
            amount_total=str(po_value),
            status="issued",
            issue_date=today.isoformat(),
            delivery_date=_shift(today, 1).isoformat(),
            payment_terms="Net 30",
        )
    )

    month_in = q2(billed / Decimal(3))
    month_out = q2(month_in * Decimal("0.85"))
    invoices: list[tuple[Invoice, date]] = []
    for back in (3, 2, 1):
        issued = month_end(_shift(today, -back - 1))
        paid_on = issued + timedelta(days=30)
        for direction, amount, prefix in (("receivable", month_in, "CF-AR"), ("payable", month_out, "CF-AP")):
            inv = Invoice(
                project_id=project_id,
                invoice_direction=direction,
                invoice_number=f"{prefix}-{tag}-{back:02d}",
                invoice_date=issued.isoformat(),
                due_date=paid_on.isoformat(),
                currency_code=currency,
                amount_subtotal=amount,
                amount_total=amount,
                status="paid",
                payment_terms_days="30",
                metadata_=meta,
            )
            invoices.append((inv, min(paid_on, today)))
    overdue = Invoice(
        project_id=project_id,
        invoice_direction="receivable",
        invoice_number=f"CF-AR-{tag}-OD",
        invoice_date=(today - timedelta(days=50)).isoformat(),
        due_date=(today - timedelta(days=20)).isoformat(),
        currency_code=currency,
        amount_subtotal=q2(value * Decimal("0.02")),
        amount_total=q2(value * Decimal("0.02")),
        status="sent",
        payment_terms_days="30",
        metadata_=meta,
    )
    session.add(overdue)
    rows.append(overdue)
    for inv, _ in invoices:
        session.add(inv)
    await session.flush()
    for inv, paid_on in invoices:
        rows.append(inv)
        rows.append(
            Payment(
                invoice_id=inv.id, payment_date=paid_on.isoformat(), amount=inv.amount_total, currency_code=currency
            )
        )
    for row in rows:
        session.add(row)
    await session.flush()
    return len(rows)
