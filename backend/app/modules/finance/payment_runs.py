# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Payment runs - pure, dependency-free rules.

A payment run is the accounting team's weekly "what do we pay on Friday": the
approved supplier invoices of one legal entity, in one currency, that fall due
by a date, each with the amount to pay on it. A person proposes it, edits it,
approves it and executes it; executing records one ordinary payment per item.

This module holds the decisions and imports nothing from SQLAlchemy or FastAPI,
so they are tested against plain data:

* :func:`propose` picks the invoices. It uses the open balance of
  :mod:`app.modules.finance.ageing` as of the payment date, so an invoice is
  proposed for what is still owed on it, never its full total after a partial
  payment, and retention that is held stays out of the run.
* :func:`check_run` is the validation the service runs before approving and
  again before executing, because invoices change between the two: a payment
  recorded by hand, an invoice cancelled, or the same invoice put in another
  run. Errors block; warnings are shown and do not.
* :func:`bank_csv` writes the remittance list handed to the bank.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from app.modules.finance.ageing import POSTED_STATUSES, AgeingInvoice, OpenBalance, open_balance

_ZERO = Decimal("0")

ERROR = "error"
WARNING = "warning"


@dataclass(frozen=True)
class Proposal:
    """One invoice a run would pay, and how much."""

    invoice_id: str
    project_id: str
    contact_id: str | None
    amount: Decimal
    due_date: str | None


@dataclass(frozen=True)
class RunLine:
    """One item of a run as the checks see it."""

    item_id: str
    invoice_id: str
    invoice_number: str
    amount: Decimal


@dataclass(frozen=True)
class RunIssue:
    """A finding on a run or on one of its items."""

    severity: str
    code: str
    message: str
    item_id: str | None = None
    invoice_id: str | None = None


def is_payable(invoice: AgeingInvoice) -> bool:
    """A supplier invoice that is posted and not settled."""
    return invoice.direction == "payable" and invoice.status in POSTED_STATUSES


def propose(
    invoices: Iterable[AgeingInvoice],
    *,
    currency_code: str,
    payment_date: str,
    due_by: str,
    taken: Iterable[str] = (),
) -> list[Proposal]:
    """The invoices to pay on ``payment_date``: payable, in the currency, due by ``due_by``.

    The amount is what is open on the invoice as of the payment date, holdback
    excluded. An invoice already in another draft or approved run (``taken``)
    is left out, so two runs never pay the same invoice. Oldest due first.
    """
    taken_ids = set(taken)
    picked: list[tuple[str, Proposal]] = []
    for invoice in invoices:
        if not is_payable(invoice) or invoice.invoice_id in taken_ids:
            continue
        if (invoice.currency_code or "") != currency_code:
            continue
        balance = open_balance(invoice, as_of=payment_date)
        if balance.due <= _ZERO:
            continue
        # A planned payment date wins over the due date: the payer has already
        # said when this one goes out.
        pay_on = invoice.scheduled_payment_date or balance.effective_due_date
        if pay_on is not None and pay_on > due_by:
            continue
        picked.append(
            (
                pay_on or "",
                Proposal(
                    invoice_id=invoice.invoice_id,
                    project_id=invoice.project_id,
                    contact_id=invoice.contact_id,
                    amount=balance.due,
                    due_date=balance.effective_due_date,
                ),
            )
        )
    picked.sort(key=lambda pair: (pair[0], pair[1].invoice_id))
    return [proposal for _, proposal in picked]


def check_run(
    lines: Sequence[RunLine],
    *,
    currency_code: str,
    payment_date: str,
    invoices: Mapping[str, AgeingInvoice],
    taken_elsewhere: Iterable[str] = (),
    created_by: str | None = None,
    approver: str | None = None,
) -> list[RunIssue]:
    """Every reason not to pay this run as it stands.

    ``invoices`` maps an invoice id to its current state (with payments), and
    ``taken_elsewhere`` names invoices in another active run. ``approver`` is
    the person about to approve; when it is the person who drew the run up the
    result carries a warning, because paying on one person's say-so is the
    control an accounting team most often asks a system to show.
    """
    issues: list[RunIssue] = []
    if not lines:
        issues.append(RunIssue(ERROR, "empty_run", "The run has no invoices to pay."))
    elsewhere = set(taken_elsewhere)
    for line in lines:
        ref = line.invoice_number or line.invoice_id

        def issue(code: str, message: str, severity: str = ERROR, _line: RunLine = line) -> None:
            issues.append(RunIssue(severity, code, message, item_id=_line.item_id, invoice_id=_line.invoice_id))

        if line.amount <= _ZERO:
            issue("amount_not_positive", f"Invoice {ref}: the amount to pay must be more than zero.")
        invoice = invoices.get(line.invoice_id)
        if invoice is None:
            issue("invoice_missing", f"Invoice {ref} no longer exists.")
            continue
        if line.invoice_id in elsewhere:
            issue("in_another_run", f"Invoice {ref} is also in another payment run that is not yet paid.")
        if invoice.direction != "payable":
            issue("not_a_supplier_invoice", f"Invoice {ref} is not a supplier invoice.")
            continue
        if invoice.status not in POSTED_STATUSES:
            issue("invoice_not_payable", f"Invoice {ref} is {invoice.status}, so it cannot be paid in a run.")
            continue
        if (invoice.currency_code or "") != currency_code:
            issue(
                "currency_mismatch",
                f"Invoice {ref} is in {invoice.currency_code or 'no currency'}, the run pays in {currency_code}.",
            )
            continue
        balance: OpenBalance = open_balance(invoice, as_of=payment_date)
        if line.amount > balance.due:
            issue(
                "amount_over_open",
                f"Invoice {ref}: {line.amount} is more than the {balance.due} still open on it.",
            )
    if created_by and approver and created_by == approver:
        issues.append(
            RunIssue(
                WARNING,
                "same_person",
                "The person approving this run also drew it up.",
            )
        )
    return issues


def has_errors(issues: Iterable[RunIssue]) -> bool:
    """Whether any finding blocks the run."""
    return any(issue.severity == ERROR for issue in issues)


#: Columns of the remittance list, in order.
BANK_CSV_COLUMNS = (
    "run_number",
    "payment_date",
    "payee",
    "payee_id",
    "invoice_number",
    "amount",
    "currency",
    "reference",
)


def bank_csv(rows: Iterable[Mapping[str, object]]) -> str:
    """The remittance list of a run as CSV, one line per invoice paid.

    A cell that a spreadsheet would read as a formula is prefixed with a quote,
    because the file is opened by people as well as imported by banks.
    """
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(BANK_CSV_COLUMNS)
    for row in rows:
        writer.writerow([_cell(row.get(column)) for column in BANK_CSV_COLUMNS])
    return out.getvalue()


def _cell(value: object) -> str:
    text = "" if value is None else str(value)
    if text and text[0] in "=+-@\t\r":
        return "'" + text
    return text


__all__ = [
    "BANK_CSV_COLUMNS",
    "ERROR",
    "WARNING",
    "Proposal",
    "RunIssue",
    "RunLine",
    "bank_csv",
    "check_run",
    "has_errors",
    "is_payable",
    "propose",
]
