# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""AR / AP ageing - pure, dependency-free arithmetic.

How much is owed, to or by whom, and how late, per legal entity. Like
:mod:`app.modules.finance.retention_ledger` this module imports nothing from
SQLAlchemy or FastAPI, so the definitions below are tested against plain data.

**The open balance of an invoice, as of a cutoff.** The platform had no single
definition: the dashboard counts every unpaid invoice at its full total, which
overstates what is owed as soon as one partial payment lands. Here, for an
invoice that is posted and not settled:

* ``cash`` is the sum of its payments dated on or before the cutoff, refunds
  subtracted.
* ``retention`` is the hold-back on it: the larger of the scheduled
  ``retention_amount`` and what payments actually withheld. Holdback is owed
  but not payable until its release date (the lien period, in Ontario), so it
  never ages as overdue. It is reported apart, as *held* until the release
  date on the payment that withheld it and as *released* once that date has
  passed. Scheduled retention that no payment has withheld yet is held.
* ``due`` is ``total - retention - cash``. A negative result is an overpayment
  and is reported as ``credit`` rather than clamped to zero, because a zero
  would print the same line for an exact payment and for a duplicate one.

Posted means ``pending``, ``approved`` or ``sent``. A draft is not yet a claim
on anyone and is counted, not aged; ``paid``, ``cancelled`` and
``credit_note_issued`` are settled. ``paid`` wins over the arithmetic: the
platform marks an invoice paid without requiring a payment row, and an invoice
the accounting team has closed must not reappear as owed.

**Ageing** counts days past the due date; an invoice with no due date falls due
``payment_terms_days`` after its date, or on its date when it has no terms.
Buckets are ``current`` (not past due), ``1_30``, ``31_60``, ``61_90`` and
``over_90``.

Nothing is blended across legal entity, currency or direction: every group and
total is scoped to one (legal entity, currency, direction).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

_ZERO = Decimal("0")
_CENTS = Decimal("0.01")

#: Ageing buckets, in reading order.
BUCKETS: tuple[str, ...] = ("current", "1_30", "31_60", "61_90", "over_90")

#: Statuses that make an invoice a claim on its counterparty.
POSTED_STATUSES = frozenset({"pending", "approved", "sent"})


def _dec(value: object) -> Decimal:
    """A finite Decimal, or zero for anything that is not one."""
    if isinstance(value, Decimal):
        return value if value.is_finite() else _ZERO
    if value is None or isinstance(value, bool):
        return _ZERO
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        return _ZERO
    return parsed if parsed.is_finite() else _ZERO


def _q2(value: Decimal) -> Decimal:
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


def _iso(value: str | None) -> date | None:
    """The date part of an ISO string, or None when there is none."""
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def bucket_for(days_past_due: int) -> str:
    """The ageing bucket of a balance that is ``days_past_due`` days late."""
    if days_past_due <= 0:
        return "current"
    if days_past_due <= 30:
        return "1_30"
    if days_past_due <= 60:
        return "31_60"
    if days_past_due <= 90:
        return "61_90"
    return "over_90"


# -- input records ---------------------------------------------------------------


@dataclass(frozen=True)
class AgeingPayment:
    """One payment against an invoice.

    ``amount`` is the cash paid, ``withholding`` the hold-back kept back at that
    payment and ``release_date`` the date that hold-back becomes payable.
    """

    amount: object = _ZERO
    payment_date: str | None = None
    withholding: object = _ZERO
    release_date: str | None = None
    is_refund: bool = False


@dataclass(frozen=True)
class AgeingInvoice:
    """One invoice with what the report needs of it and of its project."""

    invoice_id: str
    invoice_number: str
    project_id: str
    legal_entity_id: str | None
    contact_id: str | None
    direction: str
    status: str
    currency_code: str
    invoice_date: str | None
    due_date: str | None
    amount_total: object
    retention_amount: object = _ZERO
    payment_terms_days: str | None = None
    payments: Sequence[AgeingPayment] = ()
    # When the payment is planned; distinct from the contractual due date and
    # read by the payment-run proposal, never by the ageing buckets.
    scheduled_payment_date: str | None = None


# -- output records --------------------------------------------------------------


@dataclass(frozen=True)
class OpenBalance:
    """One invoice's open position as of the cutoff. Money is 2dp."""

    invoice_id: str
    invoice_number: str
    project_id: str
    invoice_date: str | None
    effective_due_date: str | None
    days_past_due: int
    bucket: str
    total: Decimal
    paid: Decimal
    due: Decimal
    credit: Decimal
    retention_held: Decimal
    retention_released: Decimal

    @property
    def is_open(self) -> bool:
        """Whether anything is still owed, held or to be recovered on it."""
        return bool(self.due or self.credit or self.retention_held or self.retention_released)


@dataclass
class AgeingRollup:
    """Open balances of one scope: a counterparty line or a total."""

    legal_entity_id: str | None
    currency_code: str
    direction: str
    contact_id: str | None = None
    buckets: dict[str, Decimal] = field(default_factory=lambda: dict.fromkeys(BUCKETS, _ZERO))
    total_due: Decimal = _ZERO
    credit: Decimal = _ZERO
    retention_held: Decimal = _ZERO
    retention_released: Decimal = _ZERO
    invoice_count: int = 0
    oldest_days_past_due: int = 0
    invoices: list[OpenBalance] = field(default_factory=list)

    def add(self, balance: OpenBalance) -> None:
        self.buckets[balance.bucket] = _q2(self.buckets[balance.bucket] + balance.due)
        self.total_due = _q2(self.total_due + balance.due)
        self.credit = _q2(self.credit + balance.credit)
        self.retention_held = _q2(self.retention_held + balance.retention_held)
        self.retention_released = _q2(self.retention_released + balance.retention_released)
        self.invoice_count += 1
        if balance.due:
            self.oldest_days_past_due = max(self.oldest_days_past_due, balance.days_past_due)


@dataclass(frozen=True)
class AgeingReport:
    """Counterparty lines and per-(entity, currency, direction) totals."""

    as_of: str
    groups: list[AgeingRollup]
    totals: list[AgeingRollup]
    drafts_excluded: int


# -- arithmetic ------------------------------------------------------------------


def effective_due_date(invoice: AgeingInvoice) -> date | None:
    """The due date, else the invoice date plus its terms, else the invoice date."""
    due = _iso(invoice.due_date)
    if due is not None:
        return due
    issued = _iso(invoice.invoice_date)
    if issued is None:
        return None
    try:
        terms = int(str(invoice.payment_terms_days).strip()) if invoice.payment_terms_days else 0
    except ValueError:
        terms = 0
    return issued + timedelta(days=max(terms, 0))


def open_balance(invoice: AgeingInvoice, *, as_of: str) -> OpenBalance:
    """The open position of one invoice as of ``as_of`` (an ISO date)."""
    cutoff = _iso(as_of) or date.today()
    total = _dec(invoice.amount_total)

    cash = _ZERO
    withheld = _ZERO
    released = _ZERO
    for pay in invoice.payments:
        paid_on = _iso(pay.payment_date)
        if paid_on is not None and paid_on > cutoff:
            continue
        amount = _dec(pay.amount)
        if pay.is_refund:
            cash -= amount
            continue
        cash += amount
        kept = _dec(pay.withholding)
        withheld += kept
        release = _iso(pay.release_date)
        if release is not None and release <= cutoff:
            released += kept

    retention = max(_dec(invoice.retention_amount), withheld)
    remainder = total - retention - cash
    due = remainder if remainder > _ZERO else _ZERO
    credit = -remainder if remainder < _ZERO else _ZERO

    due_on = effective_due_date(invoice)
    days = (cutoff - due_on).days if due_on is not None else 0
    return OpenBalance(
        invoice_id=invoice.invoice_id,
        invoice_number=invoice.invoice_number,
        project_id=invoice.project_id,
        invoice_date=invoice.invoice_date,
        effective_due_date=due_on.isoformat() if due_on else None,
        days_past_due=max(days, 0),
        bucket=bucket_for(days),
        total=_q2(total),
        paid=_q2(cash),
        due=_q2(due),
        credit=_q2(credit),
        retention_held=_q2(retention - released),
        retention_released=_q2(released),
    )


def build_ageing(invoices: Iterable[AgeingInvoice], *, as_of: str) -> AgeingReport:
    """Age every posted, unsettled invoice and roll it up.

    Lines are keyed by (legal entity, currency, direction, counterparty) and
    totals by (legal entity, currency, direction). Each line lists its invoices
    oldest due first. Lines and totals are ordered with the most overdue first.
    """
    groups: dict[tuple[str | None, str, str, str | None], AgeingRollup] = {}
    totals: dict[tuple[str | None, str, str], AgeingRollup] = {}
    drafts = 0
    for invoice in invoices:
        if invoice.status == "draft":
            drafts += 1
            continue
        if invoice.status not in POSTED_STATUSES:
            continue
        balance = open_balance(invoice, as_of=as_of)
        if not balance.is_open:
            continue
        scope = (invoice.legal_entity_id, invoice.currency_code or "", invoice.direction)
        line_key = (*scope, invoice.contact_id)
        line = groups.get(line_key)
        if line is None:
            line = groups[line_key] = AgeingRollup(*scope, contact_id=invoice.contact_id)
        line.add(balance)
        line.invoices.append(balance)
        total = totals.get(scope)
        if total is None:
            total = totals[scope] = AgeingRollup(*scope)
        total.add(balance)

    for line in groups.values():
        line.invoices.sort(key=lambda b: (b.effective_due_date or "", b.invoice_number))

    def _order(rollup: AgeingRollup) -> tuple:
        overdue = rollup.total_due - rollup.buckets["current"]
        return (rollup.legal_entity_id or "", rollup.currency_code, rollup.direction, -overdue, -rollup.total_due)

    return AgeingReport(
        as_of=(_iso(as_of) or date.today()).isoformat(),
        groups=sorted(groups.values(), key=_order),
        totals=sorted(totals.values(), key=_order),
        drafts_excluded=drafts,
    )


__all__ = [
    "BUCKETS",
    "POSTED_STATUSES",
    "AgeingInvoice",
    "AgeingPayment",
    "AgeingReport",
    "AgeingRollup",
    "OpenBalance",
    "build_ageing",
    "bucket_for",
    "effective_due_date",
    "open_balance",
]
