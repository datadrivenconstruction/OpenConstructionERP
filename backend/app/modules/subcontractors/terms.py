# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Levies and payment discount on a subcontractor invoice (pure arithmetic).

A general contractor charges its subcontractors for shared site costs
(construction insurance, site cleaning, site power, waste) as a percentage of
the work they bill, holds back retention, and takes a payment discount when it
pays within the agreed days. This module turns one invoice's work value and the
subcontract's terms into the deduction lines a person can check by hand.

How the deductions combine
--------------------------
Retention and every percentage levy are computed independently on the same
gross (certified) work value, so their order never changes the result::

    payable = gross - retention % of gross - each levy % of gross
    payment discount = discount % of payable, when paid by the due date

A levy whose ``levy_base`` is ``net_after_retention`` is taken on gross less
retention instead, for markets that agree it that way.

Every amount rounds half up to 0.01 at the step that produces it, so each line
is the figure printed and the lines add up to the payable exactly.

Standard library and Decimal only: no ORM, no session, no clock.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

CENT = Decimal("0.01")
ZERO = Decimal("0")
HUNDRED = Decimal("100")

GROSS = "gross"
NET_AFTER_RETENTION = "net_after_retention"
#: What a percentage levy is computed on.
LEVY_BASES_OF: tuple[str, ...] = (GROSS, NET_AFTER_RETENTION)

#: A levy is a percentage of the work value or a fixed amount.
LEVY_BASES: tuple[str, ...] = ("percent", "fixed")
#: A levy is charged on every invoice, or once on the final account.
LEVY_APPLIES_AT: tuple[str, ...] = ("each_invoice", "final_account")


def money(raw: Any) -> Decimal:
    """Parse a money-ish value into Decimal; blank or junk is zero."""
    if raw is None or raw == "":
        return ZERO
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return ZERO


def opt_decimal(raw: Any) -> Decimal | None:
    """Parse a Decimal or return ``None`` for blank."""
    if raw is None or raw == "":
        return None
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None


def round_cent(value: Decimal) -> Decimal:
    """Round half up to 0.01."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def percent_of(base: Decimal, rate_percent: Decimal) -> Decimal:
    """``rate_percent`` of ``base``, rounded half up to 0.01."""
    return round_cent(base * rate_percent / HUNDRED)


@dataclass(frozen=True)
class LevyTerm:
    """One levy agreed on a subcontract."""

    code: str
    name: str
    basis: str = "percent"
    rate_percent: Decimal | None = None
    fixed_amount: Decimal | None = None
    applies_at: str = "each_invoice"
    levy_base: str = GROSS


@dataclass(frozen=True)
class PaymentTerms:
    """The deduction terms of one subcontract."""

    retention_percent: Decimal = ZERO
    retention_cap_amount: Decimal | None = None
    payment_discount_percent: Decimal | None = None
    payment_discount_days: int | None = None
    payment_discount_agreed: bool = False
    levies: tuple[LevyTerm, ...] = field(default_factory=tuple)


def retention_cap_amount(contract_sum: Decimal, cap_percent: Decimal | None) -> Decimal | None:
    """The retention cap as an amount: ``cap_percent`` of the contract sum."""
    if cap_percent is None:
        return None
    return percent_of(contract_sum, cap_percent)


def _levy_amount(levy: LevyTerm, base: Decimal) -> Decimal:
    if levy.basis == "fixed":
        return round_cent(levy.fixed_amount or ZERO)
    return percent_of(base, levy.rate_percent or ZERO)


def _levy_lines(
    levies: tuple[LevyTerm, ...], gross: Decimal, net: Decimal, *, final_account: bool
) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    for levy in levies:
        if levy.applies_at == "final_account" and not final_account:
            continue
        on_net = levy.levy_base == NET_AFTER_RETENTION
        base = net if on_net else gross
        lines.append(
            {
                "code": levy.code,
                "name": levy.name,
                "basis": levy.basis,
                "rate_percent": levy.rate_percent,
                "fixed_amount": levy.fixed_amount,
                "applies_at": levy.applies_at,
                "levy_base": NET_AFTER_RETENTION if on_net else GROSS,
                "base": base,
                "amount": _levy_amount(levy, base),
            }
        )
    return lines


def _retention(base: Decimal, terms: PaymentTerms, retained_to_date: Decimal) -> tuple[Decimal, bool]:
    computed = percent_of(base, terms.retention_percent)
    if terms.retention_cap_amount is None:
        return computed, False
    room = max(terms.retention_cap_amount - retained_to_date, ZERO)
    if computed > room:
        return round_cent(room), True
    return computed, False


def build_deductions(
    work_value: Any,
    terms: PaymentTerms,
    *,
    retained_to_date: Any = ZERO,
    final_account: bool = False,
    invoice_date: date | None = None,
    paid_on: date | None = None,
) -> dict[str, Any]:
    """Compute the deduction statement of one invoice.

    Args:
        work_value: Net work value of the invoice (before any deduction).
        terms: The subcontract's deduction terms.
        retained_to_date: Retention already held on earlier invoices, so the
            cap stops the hold at the agreed amount.
        final_account: ``True`` on the final account, where levies agreed
            ``final_account`` are charged once.
        invoice_date: Start of the payment discount period.
        paid_on: Payment date, when known; decides whether the discount applies.

    Returns:
        A dict with the levy lines, the retention, the payable amount, the
        payment discount with its due date, and ``lines``: every step in the
        order shown with the running amount after it.
    """
    work = round_cent(money(work_value))
    held = money(retained_to_date)
    retention, capped = _retention(work, terms, held)
    levy_lines = _levy_lines(terms.levies, work, work - retention, final_account=final_account)
    levies_total = sum((line["amount"] for line in levy_lines), ZERO)

    lines: list[dict[str, Any]] = [{"kind": "work_value", "amount": work, "running": work}]
    running = work - retention
    lines.append({"kind": "retention", "amount": retention, "running": running})
    for line in levy_lines:
        running -= line["amount"]
        lines.append(
            {"kind": "levy", "code": line["code"], "name": line["name"], "amount": line["amount"], "running": running}
        )
    payable = running
    lines.append({"kind": "payable", "amount": payable, "running": payable})

    rate = terms.payment_discount_percent
    discount = percent_of(payable, rate) if rate is not None and rate > ZERO else ZERO
    due_date = (
        invoice_date + timedelta(days=terms.payment_discount_days)
        if invoice_date is not None and terms.payment_discount_days is not None and discount > ZERO
        else None
    )
    discount_applies: bool | None = None
    if discount > ZERO and paid_on is not None and due_date is not None:
        discount_applies = paid_on <= due_date
    payable_with_discount = payable - discount
    if discount > ZERO:
        lines.append({"kind": "payment_discount", "amount": discount, "running": payable_with_discount})
    # Unknown payment date: the discount is shown as offered, not taken.
    amount_to_pay = payable_with_discount if discount_applies else payable

    return {
        "work_value": work,
        "final_account": final_account,
        "levies": levy_lines,
        "levies_total": levies_total,
        "retention_base": work,
        "retention_percent": terms.retention_percent,
        "retention_amount": retention,
        "retention_capped": capped,
        "retention_cap_amount": terms.retention_cap_amount,
        "retained_to_date": held,
        "payable": payable,
        "payment_discount_percent": rate,
        "payment_discount_days": terms.payment_discount_days,
        "payment_discount_agreed": terms.payment_discount_agreed,
        "payment_discount_amount": discount,
        "payable_with_discount": payable_with_discount,
        "discount_due_date": due_date,
        "discount_applies": discount_applies,
        "amount_to_pay": amount_to_pay,
        "lines": lines,
    }


__all__ = [
    "GROSS",
    "LEVY_APPLIES_AT",
    "LEVY_BASES",
    "LEVY_BASES_OF",
    "NET_AFTER_RETENTION",
    "LevyTerm",
    "PaymentTerms",
    "build_deductions",
    "money",
    "opt_decimal",
    "percent_of",
    "retention_cap_amount",
    "round_cent",
]
