# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Booking batch export core: approved supplier invoices to posting rows, any file format.

Pure functions, no I/O. A format writer (generic CSV here, an accountant's exchange format in a
country pack) receives the planned rows and renders them. Account numbers, tax keys and cost
centres come only from the customer's mapping; nothing here ships a chart of accounts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, ClassVar

CENT = Decimal("0.01")
EXPORTABLE = frozenset({"approved", "posted"})


def q(value: Any) -> Decimal:
    return Decimal(str(value or 0)).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class InvoiceIn:
    id: str
    number: str
    date: date | None
    currency: str
    supplier: str
    supplier_key: str
    net: Decimal
    tax: Decimal
    gross: Decimal
    status: str
    lines: tuple[dict[str, Any], ...] = ()
    expense_account: str = ""
    project_code: str = ""
    cost_code: str = ""
    exported_in: str | None = None


@dataclass(frozen=True)
class Mapping:
    """Customer configuration: internal account code -> external account and tax key."""

    accounts: dict[str, dict[str, str]] = field(default_factory=dict)
    creditors: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_settings(cls, settings: dict[str, Any]) -> Mapping:
        """Read the maps; the connector form stores them as JSON text, an API client may send objects."""
        import json

        def as_dict(raw: Any) -> dict[str, Any]:
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw or "{}")
                except ValueError:
                    return {}
            return raw if isinstance(raw, dict) else {}

        accounts = {
            str(k): {kk: str(vv) for kk, vv in v.items()}
            for k, v in as_dict(settings.get("account_map")).items()
            if isinstance(v, dict)
        }
        creditors = {str(k): str(v) for k, v in as_dict(settings.get("creditor_accounts")).items()}
        return cls(accounts=accounts, creditors=creditors)


@dataclass(frozen=True)
class BookingRow:
    invoice_id: str
    invoice_number: str
    date: date | None
    amount: Decimal  # always positive
    side: str  # "S" debit, "H" credit, referring to ``account``
    currency: str
    account: str  # the creditor
    counter_account: str  # the expense side
    tax_key: str
    text: str
    cost1: str
    cost2: str


@dataclass
class BatchPlan:
    rows: list[BookingRow]
    included: list[str]  # invoice ids that produced rows
    findings: list[dict[str, Any]]

    @property
    def blocked(self) -> bool:
        return any(f["severity"] == "error" for f in self.findings)


def _finding(prefix: str, key: str, severity: str, number: str = "", **details: Any) -> dict[str, Any]:
    return {"rule_id": f"{prefix}.{key}", "severity": severity, "invoice": number, "details": dict(details)}


def split_lines(inv: InvoiceIn) -> list[tuple[str, Decimal, Decimal]]:
    """Return ``(internal account, net, tax)`` groups of one invoice.

    Lines naming an ``account`` are grouped by account and ``tax_rate`` (percent). An invoice
    without such lines is one group over its totals.
    """
    groups: dict[tuple[str, str], list[Decimal]] = {}
    for line in inv.lines:
        account = str(line.get("account") or "")
        if not account:
            continue
        rate = str(line.get("tax_rate") if line.get("tax_rate") is not None else "")
        net = q(line.get("amount"))
        tax = (
            q(line["tax_amount"])
            if line.get("tax_amount") is not None
            else (q(net * Decimal(rate) / 100) if rate else Decimal("0"))
        )
        slot = groups.setdefault((account, rate), [Decimal("0"), Decimal("0")])
        slot[0] += net
        slot[1] += tax
    if not groups:
        return [(inv.expense_account, inv.net, inv.tax)]
    return [(acc, n, t) for (acc, _r), (n, t) in groups.items()]


def plan_batch(
    invoices: list[InvoiceIn],
    mapping: Mapping,
    period_from: date,
    period_to: date,
    *,
    reexport: bool = False,
    prefix: str = "booking",
    base_currency: str = "",
    text_limit: int | None = None,
) -> BatchPlan:
    rows: list[BookingRow] = []
    included: list[str] = []
    findings: list[dict[str, Any]] = []
    for inv in sorted(invoices, key=lambda i: (i.date or date.min, i.number)):
        if inv.date is None or not (period_from <= inv.date <= period_to):
            continue
        if inv.status not in EXPORTABLE:
            findings.append(_finding(prefix, "not_approved", "info", inv.number))
            continue
        if inv.exported_in and not reexport:
            findings.append(_finding(prefix, "already_exported", "warning", inv.number, batch=inv.exported_in))
            continue
        groups = split_lines(inv)
        gross_sum = sum((n + t for _a, n, t in groups), Decimal("0"))
        if gross_sum != inv.gross or q(inv.net + inv.tax) != inv.gross:
            findings.append(_finding(prefix, "amounts_inconsistent", "error", inv.number))
            continue
        creditor = mapping.creditors.get(inv.supplier_key) or mapping.creditors.get(inv.supplier)
        bad = [a for a, _n, _t in groups if a not in mapping.accounts or not mapping.accounts[a].get("account")]
        if creditor is None or bad:
            for account in bad or [""]:
                findings.append(
                    _finding(prefix, "account_unmapped", "error", inv.number, account=account or inv.supplier)
                )
            continue
        if base_currency and inv.currency and inv.currency != base_currency:
            findings.append(_finding(prefix, "foreign_currency", "warning", inv.number, currency=inv.currency))
        text = inv.supplier or inv.number
        if text_limit is not None and len(text) > text_limit:
            text = text[:text_limit]
            findings.append(_finding(prefix, "text_truncated", "warning", inv.number))
        credit_note = inv.gross < 0
        for account, net, tax in groups:
            target = mapping.accounts[account]
            amount = net + tax
            rows.append(
                BookingRow(
                    invoice_id=inv.id,
                    invoice_number=inv.number,
                    date=inv.date,
                    amount=abs(amount),
                    side="S" if credit_note else "H",
                    currency=inv.currency,
                    account=creditor,
                    counter_account=target["account"],
                    tax_key=target.get("tax_key", ""),
                    text=text,
                    cost1=inv.project_code,
                    cost2=inv.cost_code,
                )
            )
        included.append(inv.id)
    return BatchPlan(rows=rows, included=included, findings=findings)


class BookingWriter:
    """A file format: turns planned rows into bytes. Registered by connector type."""

    connector_type: ClassVar[str] = ""
    required_markets: ClassVar[tuple[str, ...]] = ()
    rule_prefix: ClassVar[str] = "booking"
    text_limit: ClassVar[int | None] = None
    file_extension: ClassVar[str] = "csv"
    encoding: ClassVar[str] = "utf-8"

    @classmethod
    def check_settings(cls, settings: dict[str, Any], period_from: date, period_to: date) -> list[dict[str, Any]]:
        return []

    @classmethod
    def render(cls, rows: list[BookingRow], settings: dict[str, Any], period_from: date, period_to: date) -> bytes:
        raise NotImplementedError


class GenericCsvWriter(BookingWriter):
    connector_type = "booking_csv"

    @classmethod
    def render(cls, rows: list[BookingRow], settings: dict[str, Any], period_from: date, period_to: date) -> bytes:
        from app.core.csv_safety import neutralise_formula

        delimiter = str(settings.get("delimiter") or ";")
        decimal = str(settings.get("decimal") or ",")

        def cell(value: str) -> str:
            text = neutralise_formula(value).replace('"', '""')
            return f'"{text}"' if (delimiter in text or '"' in text or "\n" in text) else text

        header = [
            "date",
            "document",
            "amount",
            "side",
            "currency",
            "account",
            "counter_account",
            "tax_key",
            "text",
            "cost1",
            "cost2",
        ]
        out = [delimiter.join(header)]
        for r in rows:
            amount = f"{r.amount:.2f}".replace(".", decimal)
            fields = [
                r.date.isoformat() if r.date else "",
                r.invoice_number,
                amount,
                r.side,
                r.currency,
                r.account,
                r.counter_account,
                r.tax_key,
                r.text,
                r.cost1,
                r.cost2,
            ]
            out.append(delimiter.join(cell(f) for f in fields))
        return ("\r\n".join(out) + "\r\n").encode(str(settings.get("encoding") or cls.encoding), errors="replace")


WRITERS: dict[str, type[BookingWriter]] = {}


def register_writer(cls: type[BookingWriter]) -> type[BookingWriter]:
    WRITERS[cls.connector_type] = cls
    return cls


register_writer(GenericCsvWriter)
