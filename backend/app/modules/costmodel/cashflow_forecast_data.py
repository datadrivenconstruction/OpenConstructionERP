# DDC-CWICR-OE: DataDrivenConstruction​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cash-flow forecast: reading the records that drive it.

Cash in:

* client contracts: billing milestones (the payment plan) at their forecast due
  date; without milestones, the value not yet claimed spread over the months
  left, weighted by the cost-loaded schedule when there is one; each receipt
  less the retention the client holds, which comes back after completion;
* progress claims submitted or approved and not yet invoiced;
* receivable invoices, open part at the effective due date.

Cash out:

* payable invoices, open part at the effective due date;
* purchase orders: value not yet invoiced, at delivery plus the order's terms;
* subcontracts: applications approved and unpaid, then the value not yet
  applied for spread to the end date, less retention released at the end;
* payroll: the own-labour run rate from recent field time, to the end of the
  work;
* guarantee fees, when the guarantees module is installed.

Actuals are payments recorded in finance and field time already worked. When a
project has none of these records, the planned rows of the 5D cash flow are used.
Payment terms come from the document, then its contract, then 30 days.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.costmodel.cashflow_forecast import (
    HUNDRED,
    ZERO,
    ActualLine,
    CashLine,
    month_end,
    months_between,
    parse_terms_days,
    q2,
    spread,
)

logger = logging.getLogger(__name__)

DEFAULT_TERMS_DAYS = 30
#: Weeks of field time the payroll run rate looks back on.
PAYROLL_LOOKBACK_WEEKS = 8

_DEAD_CONTRACT = frozenset({"draft", "terminated", "cancelled", "closed", "void"})
_DEAD_PO = frozenset({"draft", "cancelled", "rejected", "closed"})
_DEAD_AGREEMENT = frozenset({"draft", "terminated", "cancelled", "closed"})
_LIVE_CLAIM = frozenset({"submitted", "approved", "certified"})
_LIVE_APPLICATION = frozenset({"submitted", "foreman_approved", "finance_approved", "approved"})
_POSTED_INVOICE = frozenset({"pending", "approved", "sent", "paid", "partially_paid", "overdue"})
_DEAD_TIMESHEET = frozenset({"draft", "reversed", "rejected"})


def _dec(value: object) -> Decimal:
    if value is None or value == "":
        return ZERO
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return ZERO


def _day(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


class ProjectInputs:
    """Everything the forecast of one project reads, already shaped as records."""

    def __init__(self, project_id: uuid.UUID, name: str, currency: str, status: str) -> None:
        self.project_id = project_id
        self.name = name
        self.currency = currency
        self.status = status
        self.lines: list[CashLine] = []
        self.actuals: list[ActualLine] = []
        self.threshold: Decimal = ZERO

    @property
    def has_inputs(self) -> bool:
        return bool(self.lines or self.actuals)


def _contract_terms_days(contract: object) -> int:
    terms = getattr(contract, "terms", None) or {}
    payment = terms.get("payment_terms") if isinstance(terms, dict) else None
    if isinstance(payment, dict) and payment.get("payment_period_days") not in (None, ""):
        return parse_terms_days(payment.get("payment_period_days"), DEFAULT_TERMS_DAYS)
    if isinstance(terms, dict) and terms.get("payment_terms_days") not in (None, ""):
        return parse_terms_days(terms.get("payment_terms_days"), DEFAULT_TERMS_DAYS)
    return DEFAULT_TERMS_DAYS


async def _schedule_weights(session: AsyncSession, project_id: uuid.UUID) -> dict[str, Decimal]:
    """Planned cost per month from cost-loaded activities, spread by calendar days."""
    from app.modules.schedule.models import Activity, Schedule

    rows = (
        await session.execute(
            select(Activity.start_date, Activity.end_date, Activity.cost_planned)
            .join(Schedule, Schedule.id == Activity.schedule_id)
            .where(Schedule.project_id == project_id, Activity.cost_planned.is_not(None))
        )
    ).all()
    weights: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for start_s, end_s, cost in rows:
        start, end, amount = _day(start_s), _day(end_s), _dec(cost)
        if start is None or end is None or amount <= ZERO:
            continue
        end = max(end, start)
        days = (end - start).days + 1
        cur = start
        while cur <= end:
            stop = min(month_end(cur), end)
            weights[f"{cur.year:04d}-{cur.month:02d}"] += amount * Decimal((stop - cur).days + 1) / Decimal(days)
            cur = stop + timedelta(days=1)
    return dict(weights)


def _spread_months(start: date, end: date, today: date) -> list[date]:
    first = max(start, today)
    return months_between(first, max(end, first))


async def _receivables(session: AsyncSession, inp: ProjectInputs, today: date) -> set[uuid.UUID]:
    """Receivable and payable invoices plus their payments. Returns claim ids already invoiced."""
    from app.modules.finance.ageing import AgeingInvoice, AgeingPayment, open_balance
    from app.modules.finance.models import Invoice, Payment

    invoices = (await session.execute(select(Invoice).where(Invoice.project_id == inp.project_id))).scalars().all()
    invoiced_claims: set[uuid.UUID] = set()
    ids = [i.id for i in invoices]
    payments: dict[uuid.UUID, list[Payment]] = defaultdict(list)
    if ids:
        for pay in (await session.execute(select(Payment).where(Payment.invoice_id.in_(ids)))).scalars():
            payments[pay.invoice_id].append(pay)
    for inv in invoices:
        if inv.source_claim_id:
            invoiced_claims.add(inv.source_claim_id)
        if inv.status not in _POSTED_INVOICE:
            continue
        direction = "in" if inv.invoice_direction == "receivable" else "out"
        currency = (inv.currency_code or inp.currency or "").upper()
        pays = payments.get(inv.id, [])
        for pay in pays:
            on = _day(pay.payment_date)
            if on is None:
                continue
            amount = _dec(pay.amount)
            inp.actuals.append(
                ActualLine(direction=direction, on=on, amount=-amount if pay.is_refund else amount, currency=currency)
            )
        bal = open_balance(
            AgeingInvoice(
                invoice_id=str(inv.id),
                invoice_number=inv.invoice_number,
                project_id=str(inv.project_id),
                legal_entity_id=None,
                contact_id=inv.contact_id,
                direction=inv.invoice_direction,
                status=inv.status,
                currency_code=currency,
                invoice_date=inv.invoice_date,
                due_date=inv.due_date,
                amount_total=inv.amount_total,
                retention_amount=inv.retention_amount,
                payment_terms_days=inv.payment_terms_days,
                payments=[
                    AgeingPayment(
                        amount=p.amount,
                        payment_date=p.payment_date,
                        withholding=p.withholding_amount,
                        release_date=p.withholding_release_date,
                        is_refund=p.is_refund,
                    )
                    for p in pays
                ],
            ),
            as_of=today.isoformat(),
        )
        due_on = _day(bal.effective_due_date) or _day(inv.invoice_date) or today
        source = "receivable_invoice" if direction == "in" else "payable_invoice"
        inp.lines.append(
            CashLine(
                direction=direction,
                source=source,
                on=due_on,
                planned=bal.total - bal.retention_held - bal.retention_released,
                open=bal.due,
                currency=currency,
                ref=str(inv.id),
                label=inv.invoice_number,
                due=due_on,
            )
        )
    return invoiced_claims


async def _client_contracts(
    session: AsyncSession, inp: ProjectInputs, today: date, invoiced_claims: set[uuid.UUID]
) -> None:
    from app.modules.contracts.models import Contract, ContractMilestone, ProgressClaim

    contracts = (
        (
            await session.execute(
                select(Contract).where(Contract.project_id == inp.project_id, Contract.counterparty_type == "client")
            )
        )
        .scalars()
        .all()
    )
    weights: dict[str, Decimal] | None = None
    for c in contracts:
        if c.status in _DEAD_CONTRACT:
            continue
        currency = (c.currency or inp.currency or "").upper()
        terms = _contract_terms_days(c)
        retention_pct = _dec(c.retention_percent)
        total = _dec(c.total_value)
        start = _day(c.start_date) or today
        end = _day(c.end_date) or start
        claims = (await session.execute(select(ProgressClaim).where(ProgressClaim.contract_id == c.id))).scalars().all()
        claimed = sum((_dec(cl.gross_amount) for cl in claims if cl.status not in ("draft", "rejected")), ZERO)
        retention_held = sum(
            (_dec(cl.retention_amount) for cl in claims if cl.status not in ("draft", "rejected")), ZERO
        )
        for cl in claims:
            if cl.status not in _LIVE_CLAIM or cl.id in invoiced_claims:
                continue
            on = (_day(cl.claim_date) or _day(cl.period_end) or today) + timedelta(days=terms)
            amount = q2(_dec(cl.net_due))
            inp.lines.append(
                CashLine("in", "claim", on, amount, amount, currency, ref=str(cl.id), label=cl.claim_number, due=on)
            )
        milestones = (
            (await session.execute(select(ContractMilestone).where(ContractMilestone.contract_id == c.id)))
            .scalars()
            .all()
        )
        open_ms = [m for m in milestones if m.status in ("pending", "reached")]
        future_gross = ZERO
        if milestones:
            for m in open_ms:
                value = _dec(m.value) if m.value is not None else q2(total * _dec(m.percent_of_contract) / HUNDRED)
                gross = q2(value)
                net = q2(gross * (HUNDRED - retention_pct) / HUNDRED)
                m_terms = m.payment_terms_days if m.payment_terms_days is not None else terms
                on = _day(m.forecast_due_date) or (
                    (_day(m.planned_date) or end) + timedelta(days=m_terms + (m.lag_days or 0))
                )
                inp.lines.append(CashLine("in", "milestone", on, net, net, currency, ref=str(m.id), label=m.name))
                future_gross += gross
        else:
            remaining = total - claimed
            if remaining > ZERO:
                months = _spread_months(start, end, today)
                if weights is None:
                    weights = await _schedule_weights(session, inp.project_id)
                w = [weights.get(f"{d.year:04d}-{d.month:02d}", ZERO) for d in months]
                for d, gross in zip(months, spread(remaining, w), strict=True):
                    net = q2(gross * (HUNDRED - retention_pct) / HUNDRED)
                    on = d + timedelta(days=terms)
                    inp.lines.append(CashLine("in", "billing", on, net, net, currency, ref=str(c.id), label=c.code))
                future_gross = remaining
        retention = q2(retention_held + future_gross * retention_pct / HUNDRED)
        if retention > ZERO:
            on = max(end, today) + timedelta(days=terms)
            inp.lines.append(
                CashLine("in", "retention_release", on, retention, retention, currency, ref=str(c.id), label=c.code)
            )


async def _purchase_orders(session: AsyncSession, inp: ProjectInputs, today: date) -> None:
    from app.modules.finance.models import Invoice
    from app.modules.procurement.models import PurchaseOrder

    pos = (
        (await session.execute(select(PurchaseOrder).where(PurchaseOrder.project_id == inp.project_id))).scalars().all()
    )
    live = [p for p in pos if p.status not in _DEAD_PO]
    if not live:
        return
    rows = (
        await session.execute(
            select(Invoice.purchase_order_id, Invoice.amount_total).where(
                Invoice.purchase_order_id.in_([p.id for p in live]), Invoice.status != "cancelled"
            )
        )
    ).all()
    invoiced: dict[uuid.UUID, Decimal] = defaultdict(lambda: ZERO)
    for po_id, amount in rows:
        invoiced[po_id] += _dec(amount)
    for po in live:
        remaining = q2(_dec(po.amount_total) - invoiced.get(po.id, ZERO))
        if remaining <= ZERO:
            continue
        delivery = _day(po.supplier_confirmed_delivery_date) or _day(po.delivery_date) or _day(po.issue_date) or today
        on = delivery + timedelta(days=parse_terms_days(po.payment_terms, DEFAULT_TERMS_DAYS))
        currency = (po.currency_code or inp.currency or "").upper()
        inp.lines.append(
            CashLine("out", "purchase_order", on, remaining, remaining, currency, ref=str(po.id), label=po.po_number)
        )


async def _subcontracts(session: AsyncSession, inp: ProjectInputs, today: date) -> None:
    from app.modules.subcontractors.models import PaymentApplication, SubcontractAgreement

    agreements = (
        (await session.execute(select(SubcontractAgreement).where(SubcontractAgreement.project_id == inp.project_id)))
        .scalars()
        .all()
    )
    for ag in agreements:
        if ag.status in _DEAD_AGREEMENT:
            continue
        currency = (ag.currency or inp.currency or "").upper()
        meta = ag.metadata_ or {}
        terms = parse_terms_days(meta.get("payment_terms_days"), DEFAULT_TERMS_DAYS)
        retention_pct = _dec(ag.retention_percent)
        apps = (
            (await session.execute(select(PaymentApplication).where(PaymentApplication.agreement_id == ag.id)))
            .scalars()
            .all()
        )
        applied = ZERO
        held = ZERO
        for app in apps:
            if app.status == "rejected":
                continue
            applied += _dec(app.gross_amount)
            held += _dec(app.retention_amount)
            if app.status in _LIVE_APPLICATION:
                on = (_day(app.period_end) or today) + timedelta(days=terms)
                net = q2(_dec(app.net_amount))
                inp.lines.append(
                    CashLine(
                        "out",
                        "subcontract_application",
                        on,
                        net,
                        net,
                        currency,
                        ref=str(app.id),
                        label=app.application_number,
                        due=on,
                    )
                )
        remaining = _dec(ag.total_value) - applied
        start = ag.start_date or today
        end = ag.end_date or start
        if remaining > ZERO:
            months = _spread_months(start, end, today)
            for d, gross in zip(months, spread(remaining, [Decimal(1)] * len(months)), strict=True):
                net = q2(gross * (HUNDRED - retention_pct) / HUNDRED)
                inp.lines.append(
                    CashLine(
                        "out",
                        "subcontract",
                        d + timedelta(days=terms),
                        net,
                        net,
                        currency,
                        ref=str(ag.id),
                        label=ag.title,
                    )
                )
        retention = q2(held + max(remaining, ZERO) * retention_pct / HUNDRED)
        if retention > ZERO:
            on = max(end, today) + timedelta(days=terms)
            inp.lines.append(
                CashLine(
                    "out", "subcontract_retention", on, retention, retention, currency, ref=str(ag.id), label=ag.title
                )
            )


async def _payroll(session: AsyncSession, inp: ProjectInputs, today: date, work_end: date | None) -> None:
    from app.modules.field_time.models import FieldTimesheet, FieldTimesheetLine
    from app.modules.resources.models import Resource

    rows = (
        await session.execute(
            select(
                FieldTimesheet.date,
                FieldTimesheetLine.hours,
                FieldTimesheetLine.employer_kind,
                Resource.default_cost_rate,
            )
            .join(FieldTimesheetLine, FieldTimesheetLine.timesheet_id == FieldTimesheet.id)
            .join(Resource, Resource.id == FieldTimesheetLine.resource_id)
            .where(FieldTimesheet.project_id == inp.project_id, FieldTimesheet.status.not_in(_DEAD_TIMESHEET))
        )
    ).all()
    if not rows:
        return
    currency = (inp.currency or "").upper()
    since = today - timedelta(weeks=PAYROLL_LOOKBACK_WEEKS)
    recent = ZERO
    by_month: dict[date, Decimal] = defaultdict(lambda: ZERO)
    for day, hours, kind, rate in rows:
        if kind == "subcontractor":
            continue  # paid through the subcontract, not the payroll
        d = _day(day)
        if d is None or d > today:
            continue
        cost = _dec(hours) * _dec(rate)
        by_month[month_end(d)] += cost
        if d >= since:
            recent += cost
    for on, cost in by_month.items():
        inp.actuals.append(ActualLine("out", min(on, today), q2(cost), currency))
    if recent <= ZERO or work_end is None or work_end <= today:
        return
    monthly = recent / Decimal(PAYROLL_LOOKBACK_WEEKS) * Decimal(52) / Decimal(12)
    months = months_between(today, work_end)
    if months and months[0].month == today.month:
        months = months[1:]  # the running month is already in the actuals
    for d in months:
        amount = q2(monthly)
        inp.lines.append(CashLine("out", "payroll", d, amount, amount, currency, label="payroll"))


async def _guarantee_fees(session: AsyncSession, inp: ProjectInputs, today: date) -> None:
    try:
        from app.modules.guarantees.models import Guarantee  # type: ignore[import-not-found]
    except ImportError:
        return
    rows = (await session.execute(select(Guarantee).where(Guarantee.project_id == inp.project_id))).scalars().all()
    for g in rows:
        rate = _dec(getattr(g, "commission_rate_pct", None))
        if g.status not in ("issued", "active", "extended") or g.direction != "given" or rate <= ZERO:
            continue
        expiry = _day(g.expiry_date)
        if expiry is None or expiry <= today:
            continue
        quarter_fee = q2(_dec(g.amount) * rate / HUNDRED / Decimal(4))
        currency = (g.currency or inp.currency or "").upper()
        on = _day(g.issue_date) or today
        while on <= expiry:
            if on >= today:
                inp.lines.append(
                    CashLine(
                        "out", "guarantee_fee", on, quarter_fee, quarter_fee, currency, ref=str(g.id), label=g.reference
                    )
                )
            on = date(on.year + (on.month + 2) // 12, (on.month + 2) % 12 + 1, min(on.day, 28))


async def _plan_fallback(session: AsyncSession, inp: ProjectInputs, today: date) -> None:
    from app.modules.costmodel.models import CashFlow

    rows = (await session.execute(select(CashFlow).where(CashFlow.project_id == inp.project_id))).scalars().all()
    currency = (inp.currency or "").upper()
    for row in rows:
        try:
            on = month_end(date.fromisoformat(f"{row.period[:7]}-01"))
        except ValueError:
            continue
        future = on >= today
        for direction, planned, actual in (
            ("in", row.planned_inflow, row.actual_inflow),
            ("out", row.planned_outflow, row.actual_outflow),
        ):
            p, a = q2(_dec(planned)), q2(_dec(actual))
            if p:
                inp.lines.append(CashLine(direction, "plan", on, p, p if future else ZERO, currency, label=row.period))
            if a and not future:
                inp.actuals.append(ActualLine(direction, on, a, currency))


async def _work_end(session: AsyncSession, project_id: uuid.UUID) -> date | None:
    from app.modules.contracts.models import Contract
    from app.modules.schedule.models import Activity, Schedule

    ends = [
        _day(v)
        for (v,) in (
            await session.execute(
                select(Activity.end_date)
                .join(Schedule, Schedule.id == Activity.schedule_id)
                .where(Schedule.project_id == project_id)
            )
        ).all()
    ]
    ends += [
        _day(v) for (v,) in (await session.execute(select(Contract.end_date).where(Contract.project_id == project_id)))
    ]
    known = [d for d in ends if d is not None]
    return max(known) if known else None


async def collect_project(session: AsyncSession, project_id: uuid.UUID, today: date) -> ProjectInputs | None:
    """The forecast records of one project, or ``None`` when it does not exist."""
    from app.modules.projects.models import Project

    project = await session.get(Project, project_id)
    if project is None:
        return None
    inp = ProjectInputs(project.id, project.name, (project.currency or "").upper(), project.status)
    meta = project.metadata_ or {}
    inp.threshold = _dec(meta.get("cashflow_threshold"))
    invoiced_claims = await _receivables(session, inp, today)
    await _client_contracts(session, inp, today, invoiced_claims)
    await _purchase_orders(session, inp, today)
    await _subcontracts(session, inp, today)
    await _payroll(session, inp, today, await _work_end(session, project_id))
    await _guarantee_fees(session, inp, today)
    if not inp.lines:
        await _plan_fallback(session, inp, today)
    return inp
