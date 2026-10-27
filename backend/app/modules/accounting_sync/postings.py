# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Neutral​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ sync documents and the double-entry journal built from them.

Every adapter and every file export reads the same :class:`SyncDocument`, so a
receivable invoice, an interim payment certificate, a subcontractor or supplier
bill and a guarantee fee all post the same way whatever the target system. Money
is ``Decimal`` throughout and rounded half-up to cents only where a posting is made.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

CENT = Decimal("0.01")
ZERO = Decimal("0")

#: record_type of a document the platform sends out.
AR_INVOICE = "ar_invoice"
AP_BILL = "ap_bill"
DOCUMENT_TYPES = (AR_INVOICE, AP_BILL)


def money(value: Any) -> Decimal:
    """Exact Decimal of a value, rounded half-up to cents."""
    if value is None or value == "":
        return ZERO
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass
class SyncContact:
    """Counterparty of a document: customer of an AR invoice, supplier of a bill."""

    record_id: str
    name: str
    kind: str  # customer | supplier
    tax_id: str = ""
    country_code: str = ""
    email: str = ""
    is_business: bool = True


@dataclass
class SyncLine:
    """One net amount on a document with its posting category and tax code."""

    description: str
    net: Decimal
    category: str
    tax_code: str
    tax_rate: Decimal | None = None
    quantity: Decimal = Decimal("1")


@dataclass
class SyncDocument:
    """A platform document ready to post: invoice, certificate, bill or fee."""

    record_type: str
    record_id: str
    number: str
    doc_date: date
    contact: SyncContact
    currency: str
    lines: list[SyncLine]
    source: str = "invoice"  # invoice | interim_payment | subcontractor | procurement | guarantee_fee | payroll
    project_id: str = ""
    project_code: str = ""
    project_name: str = ""
    due_date: date | None = None
    recorded_tax: Decimal | None = None
    recorded_total: Decimal | None = None
    reference: str = ""

    @property
    def is_sales(self) -> bool:
        return self.record_type == AR_INVOICE

    @property
    def tax_direction(self) -> str:
        return "sales" if self.is_sales else "purchase"

    def line_tax(self, line: SyncLine) -> Decimal:
        return money(line.net * (line.tax_rate or ZERO) / Decimal("100"))

    @property
    def net_total(self) -> Decimal:
        return sum((money(ln.net) for ln in self.lines), ZERO)

    @property
    def tax_total(self) -> Decimal:
        return sum((self.line_tax(ln) for ln in self.lines), ZERO)

    @property
    def gross_total(self) -> Decimal:
        return self.net_total + self.tax_total

    def payload_hash(self) -> str:
        """Stable hash of what would be sent; an unchanged document is not resent."""
        raw = asdict(self)
        return hashlib.sha256(json.dumps(raw, sort_keys=True, default=str).encode()).hexdigest()


@dataclass
class JournalLine:
    """One debit or credit line of the neutral journal."""

    entry_no: int
    posting_date: date
    document_number: str
    record_type: str
    record_id: str
    source: str
    account: str
    account_name: str
    debit: Decimal
    credit: Decimal
    currency: str
    tax_code: str = ""
    tax_key: str = ""
    tax_rate: Decimal | None = None
    tax_amount: Decimal = ZERO
    cost_centre: str = ""
    project: str = ""
    counterparty: str = ""
    counterparty_id: str = ""
    description: str = ""


@dataclass
class Mapping:
    """Resolved account and tax mapping of one connection."""

    accounts: dict[str, tuple[str, str]] = field(default_factory=dict)  # category -> (code, name)
    tax_keys: dict[tuple[str, str], str] = field(default_factory=dict)  # (tax_code, direction) -> key

    def account(self, category: str) -> tuple[str, str]:
        return self.accounts.get(category, ("", ""))

    def tax_key(self, tax_code: str, direction: str) -> str | None:
        return self.tax_keys.get((tax_code, direction))


def build_journal(doc: SyncDocument, mapping: Mapping, entry_no: int = 1) -> list[JournalLine]:
    """Balanced double-entry lines for one document.

    AR: debit receivable control at gross, credit revenue at net and output tax.
    AP: debit cost at net and input tax, credit payable control at gross.
    """
    lines: list[JournalLine] = []
    control_cat = "ar_control" if doc.is_sales else "ap_control"
    if doc.source == "payroll":
        control_cat = "payroll_liability"
    tax_cat = "output_tax" if doc.is_sales else "input_tax"
    common = {
        "entry_no": entry_no,
        "posting_date": doc.doc_date,
        "document_number": doc.number,
        "record_type": doc.record_type,
        "record_id": doc.record_id,
        "source": doc.source,
        "currency": doc.currency,
        "cost_centre": doc.project_code,
        "project": doc.project_name,
        "counterparty": doc.contact.name,
        "counterparty_id": doc.contact.record_id,
    }

    def side(amount: Decimal, debit: bool) -> dict[str, Decimal]:
        return {"debit": amount, "credit": ZERO} if debit else {"debit": ZERO, "credit": amount}

    code, name = mapping.account(control_cat)
    lines.append(
        JournalLine(
            **common, account=code, account_name=name, description=doc.number, **side(doc.gross_total, doc.is_sales)
        )
    )
    for ln in doc.lines:
        code, name = mapping.account(ln.category)
        tax = doc.line_tax(ln)
        key = mapping.tax_key(ln.tax_code, doc.tax_direction) or ""
        lines.append(
            JournalLine(
                **common,
                account=code,
                account_name=name,
                description=ln.description,
                tax_code=ln.tax_code,
                tax_key=key,
                tax_rate=ln.tax_rate,
                tax_amount=tax,
                **side(money(ln.net), not doc.is_sales),
            )
        )
    tax_total = doc.tax_total
    if tax_total:
        code, name = mapping.account(tax_cat)
        lines.append(
            JournalLine(
                **common, account=code, account_name=name, description=doc.number, **side(tax_total, not doc.is_sales)
            )
        )
    return lines


def journal_for(docs: list[SyncDocument], mapping: Mapping) -> list[JournalLine]:
    """Journal of many documents, one entry number per document."""
    out: list[JournalLine] = []
    for n, doc in enumerate(sorted(docs, key=lambda d: (d.doc_date, d.number)), start=1):
        out.extend(build_journal(doc, mapping, n))
    return out


def personal_accounts(
    contacts: list[SyncContact], debtor_range: tuple[int, int], creditor_range: tuple[int, int]
) -> dict[str, int]:
    """Stable debtor or creditor number per contact, assigned in name order within its range."""
    out: dict[str, int] = {}
    next_no = {"customer": debtor_range[0], "supplier": creditor_range[0]}
    limit = {"customer": debtor_range[1], "supplier": creditor_range[1]}
    for c in sorted(
        {(c.kind, c.name.lower(), c.record_id): c for c in contacts}.values(), key=lambda c: (c.kind, c.name.lower())
    ):
        key = f"{c.kind}:{c.record_id}"
        if key in out:
            continue
        if next_no[c.kind] > limit[c.kind]:
            raise ValueError(f"No {c.kind} account numbers left in the range")
        out[key] = next_no[c.kind]
        next_no[c.kind] += 1
    return out
