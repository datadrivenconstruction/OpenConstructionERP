# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure arithmetic and completeness checks for a purchase order.

Validation is first-class for this module (platform principle #4), and a purchase
order is the moment a project turns an estimate into committed money. Approval is
where the commitment is published to finance (``procurement.po.approved``), so
approval is where these checks run: a PO whose own arithmetic disagrees with
itself would otherwise commit one number to the budget and show another to the
buyer, and nothing downstream re-derives it.

This module is deliberately **dependency-free** in the same spirit as
``field_time/field_time_math.py``: standard library plus :class:`~decimal.Decimal`
only, no ORM, no FastAPI, no session. The rule classes in
``app.core.validation.rules`` stay thin wrappers that translate these outcomes
into :class:`RuleResult` rows, and the checks themselves are unit-tested without a
database.

Money discipline
----------------
Every amount on the PO model is a Decimal *string* (``amount_total``,
``unit_rate``, ...). Parsing is total: an unparseable amount is reported as a
finding rather than raised, because a rule that explodes on bad data hides the
very row the user needs to see. Comparison tolerance is one cent
(:data:`MONEY_TOLERANCE`), which absorbs per-line rounding without absorbing a
real discrepancy.

Currency is never blended: every value on a PO is in that PO's own
``currency_code``, so these checks compare numbers that are already in one
currency and never convert.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

# The one spelling an amount gets anywhere in this platform. It lives in its own
# module precisely so that this file can keep the standard-library-only contract
# its docstring declares: the same function is what the core validation rules
# call, and a second spelling here would disagree with them on every currency
# that does not have two decimals.
from app.core.currency_registry import sentence_amount

#: Amounts closer than this are equal. One cent absorbs per-line rounding
#: (a 3-decimal unit rate quantised to 2) without absorbing a real mismatch.
MONEY_TOLERANCE = Decimal("0.01")

#: Retention above this is almost certainly a data-entry error (a rate typed as
#: an amount). The construction norm sits at 5-10%; anything past half the
#: commitment is not retention any more.
MAX_SANE_RETENTION_PERCENT = Decimal("50")


@dataclass(frozen=True)
class Finding:
    """One failed check on one element.

    :param element_ref: what the user should look at -- a line label or the PO
        number. Never ``None``: a finding the UI cannot anchor is a finding the
        user cannot act on.
    :param params: placeholders for the translated message, all pre-formatted as
        strings so the message layer never formats money itself.
    :param details: machine-readable context for the report payload.
    """

    element_ref: str
    params: dict[str, str] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)


def parse_money(raw: Any) -> Decimal | None:
    """Parse a Decimal-string amount, or ``None`` when it is not a number.

    Returning ``None`` rather than raising is deliberate: an unparseable amount
    is itself a finding, and the caller decides how to report it.
    """
    if raw is None:
        return None
    if isinstance(raw, Decimal):
        return raw
    try:
        return Decimal(str(raw).strip())
    except (InvalidOperation, ValueError, TypeError):
        return None


def _money(raw: Any) -> Decimal:
    """Parse an amount, treating anything unparseable as zero."""
    parsed = parse_money(raw)
    return parsed if parsed is not None else Decimal("0")


def _fmt(value: Decimal) -> str:
    """Render a *percentage* for a user-facing message, two decimals, no exponent.

    Not for money, despite the name it has always had. Money goes through
    :func:`_amount`, which asks the currency how many decimals it keeps and
    writes the code beside the digits. The retention template glues ``%`` onto
    its slot, so an amount rendered through this function would read
    ``50.00 EUR%``, and grouping a percentage gains a reader nothing.
    """
    return f"{value.quantize(Decimal('0.01')):f}"


def _currency(po: dict[str, Any]) -> str:
    """The code this purchase order states, never a default.

    Blank stays blank: the renderer then groups the digits and writes no code.
    :func:`check_currency_set` is the rule that complains about a missing
    currency, so nothing is lost by declining to guess one here, and a guessed
    code would read as authoritative and be wrong whenever the project is not in
    it.
    """
    return str(po.get("currency_code") or "").strip()


def _amount(value: Decimal, po: dict[str, Any]) -> str:
    """Render an amount for a message, in the purchase order's own currency."""
    return sentence_amount(value, _currency(po))


def line_label(index: int, item: dict[str, Any]) -> str:
    """A human line label: the 1-based row number plus a trimmed description."""
    description = str(item.get("description") or "").strip()
    if not description:
        return str(index + 1)
    if len(description) > 40:
        description = description[:37] + "..."
    return f"{index + 1} ({description})"


def _items(po: dict[str, Any]) -> list[dict[str, Any]]:
    items = po.get("items")
    return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []


def _po_ref(po: dict[str, Any]) -> str:
    return str(po.get("po_number") or po.get("id") or "?")


# ── Checks ───────────────────────────────────────────────────────────────────


def check_has_lines(po: dict[str, Any]) -> list[Finding]:
    """A PO with no lines commits an amount nothing accounts for."""
    if _items(po):
        return []
    return [Finding(element_ref=_po_ref(po), details={"item_count": 0})]


def check_line_amount(po: dict[str, Any]) -> list[Finding]:
    """Each line's ``amount`` must equal ``quantity x unit_rate``."""
    findings: list[Finding] = []
    for index, item in enumerate(_items(po)):
        quantity = parse_money(item.get("quantity"))
        rate = parse_money(item.get("unit_rate"))
        amount = parse_money(item.get("amount"))
        if quantity is None or rate is None or amount is None:
            findings.append(
                Finding(
                    element_ref=line_label(index, item),
                    params={"line": line_label(index, item), "expected": "?", "actual": "?"},
                    details={"reason": "unparseable_amount"},
                )
            )
            continue
        expected = quantity * rate
        if abs(expected - amount) > MONEY_TOLERANCE:
            findings.append(
                Finding(
                    element_ref=line_label(index, item),
                    params={
                        "line": line_label(index, item),
                        "expected": _amount(expected, po),
                        "actual": _amount(amount, po),
                    },
                    details={
                        "quantity": str(quantity),
                        "unit_rate": str(rate),
                        "expected": str(expected),
                        "actual": str(amount),
                    },
                )
            )
    return findings


def check_subtotal_matches_lines(po: dict[str, Any]) -> list[Finding]:
    """``amount_subtotal`` must equal the sum of the line amounts.

    Skipped for a PO with no lines: :func:`check_has_lines` already owns that
    case, and reporting it twice would double-count one problem.
    """
    items = _items(po)
    if not items:
        return []
    lines_total = sum((_money(i.get("amount")) for i in items), Decimal("0"))
    subtotal = _money(po.get("amount_subtotal"))
    if abs(lines_total - subtotal) <= MONEY_TOLERANCE:
        return []
    return [
        Finding(
            element_ref=_po_ref(po),
            params={"expected": _amount(lines_total, po), "actual": _amount(subtotal, po)},
            details={"lines_total": str(lines_total), "amount_subtotal": str(subtotal)},
        )
    ]


def check_total_matches_subtotal_plus_tax(po: dict[str, Any]) -> list[Finding]:
    """``amount_total`` must equal ``amount_subtotal + tax_amount``.

    This is the number finance commits, so a mismatch here is the one that moves
    real money.
    """
    subtotal = _money(po.get("amount_subtotal"))
    tax = _money(po.get("tax_amount"))
    total = _money(po.get("amount_total"))
    expected = subtotal + tax
    if abs(expected - total) <= MONEY_TOLERANCE:
        return []
    return [
        Finding(
            element_ref=_po_ref(po),
            params={"expected": _amount(expected, po), "actual": _amount(total, po)},
            details={
                "amount_subtotal": str(subtotal),
                "tax_amount": str(tax),
                "amount_total": str(total),
            },
        )
    ]


def check_no_negative_line(po: dict[str, Any]) -> list[Finding]:
    """Quantity must be positive and the unit rate must not be negative.

    A credit belongs on its own document, not as a negative line hidden inside a
    commitment; a negative quantity here silently reduces the committed total.
    """
    findings: list[Finding] = []
    for index, item in enumerate(_items(po)):
        quantity = parse_money(item.get("quantity"))
        rate = parse_money(item.get("unit_rate"))
        reasons: list[str] = []
        if quantity is not None and quantity <= 0:
            reasons.append("quantity_not_positive")
        if rate is not None and rate < 0:
            reasons.append("rate_negative")
        if reasons:
            findings.append(
                Finding(
                    element_ref=line_label(index, item),
                    params={"line": line_label(index, item)},
                    details={"reasons": reasons, "quantity": str(quantity), "unit_rate": str(rate)},
                )
            )
    return findings


def check_currency_set(po: dict[str, Any]) -> list[Finding]:
    """The PO must carry a currency.

    The column defaults to an empty string and the service inherits the project
    currency; an empty value that reaches approval means neither happened, and an
    amount without a currency cannot be rolled up or paid.
    """
    if str(po.get("currency_code") or "").strip():
        return []
    return [Finding(element_ref=_po_ref(po), details={"currency_code": ""})]


def check_vendor_assigned(po: dict[str, Any]) -> list[Finding]:
    """An approved commitment must name the party it is committed to."""
    if str(po.get("vendor_contact_id") or "").strip():
        return []
    return [Finding(element_ref=_po_ref(po), details={"vendor_contact_id": None})]


def check_retention_within_bounds(po: dict[str, Any]) -> list[Finding]:
    """Retention must be a percentage, and a plausible one."""
    percent = parse_money(po.get("retention_percent"))
    if percent is None:
        return [
            Finding(
                element_ref=_po_ref(po),
                params={"percent": "?", "max": _fmt(MAX_SANE_RETENTION_PERCENT)},
                details={"reason": "unparseable_percent"},
            )
        ]
    if Decimal("0") <= percent <= MAX_SANE_RETENTION_PERCENT:
        return []
    return [
        Finding(
            element_ref=_po_ref(po),
            params={"percent": _fmt(percent), "max": _fmt(MAX_SANE_RETENTION_PERCENT)},
            details={"retention_percent": str(percent), "max": str(MAX_SANE_RETENTION_PERCENT)},
        )
    ]


def _parse_date(raw: Any) -> date | None:
    """Parse the leading ``YYYY-MM-DD`` of a date column, or ``None``.

    The date columns are free-form strings, so anything that is not an ISO date
    is treated as absent rather than as a finding: this check is about ordering,
    not about format.
    """
    text = str(raw or "").strip()
    if len(text) < 10:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def check_delivery_not_before_issue(po: dict[str, Any]) -> list[Finding]:
    """Delivery cannot be scheduled before the PO goes out."""
    issue = _parse_date(po.get("issue_date"))
    delivery = _parse_date(po.get("delivery_date"))
    if issue is None or delivery is None or delivery >= issue:
        return []
    return [
        Finding(
            element_ref=_po_ref(po),
            params={"issue": issue.isoformat(), "delivery": delivery.isoformat()},
            details={"issue_date": issue.isoformat(), "delivery_date": delivery.isoformat()},
        )
    ]


def check_line_cost_coded(po: dict[str, Any]) -> list[Finding]:
    """Each line should carry a WBS, a cost category or a cost-line link.

    An uncoded commitment cannot be reported against a budget: it lands in the
    project total and nowhere in the breakdown. WARNING rather than ERROR --
    plenty of real POs are raised before the coding is decided.
    """
    findings: list[Finding] = []
    for index, item in enumerate(_items(po)):
        coded = any(str(item.get(key) or "").strip() for key in ("wbs_id", "cost_category", "cost_line_id"))
        if not coded:
            findings.append(
                Finding(
                    element_ref=line_label(index, item),
                    params={"line": line_label(index, item)},
                    details={"wbs_id": None, "cost_category": None, "cost_line_id": None},
                )
            )
    return findings


# ── Invoice against its purchase order (simple three-way match) ─────────────
#
# A supplier invoice linked to an order is checked against what is left on the
# order and, once goods have been received, against what arrived. Both are
# WARNINGS: an invoice above the order can be a legitimate extra the site
# agreed by phone, and a delivery note can reach the office after the invoice.
# The person approving the invoice reads the warning and decides; nothing here
# blocks the save. This is deliberately not an accounts-payable matching
# engine: price variance per unit, tolerances per supplier and partial-line
# splits are out of scope.
#
# The payload is built by ``ProcurementService.invoice_match_payload``:
#
#     {"po_number", "currency_code", "po_net", "invoiced_before_net",
#      "invoice_net", "invoice_ref", "has_receipts", "received_net",
#      "lines": [{"label", "unit", "ordered", "received", "invoiced_before",
#                 "invoiced"}]}
#
# Money is net of VAT on both sides; quantities are per order line.

#: Quantities closer than this are equal (a rounded metre of cable, a kilo).
QUANTITY_TOLERANCE = Decimal("0.001")


def check_invoice_within_order(payload: dict[str, Any]) -> list[Finding]:
    """The invoice should not exceed what is still open on its order, net of VAT."""
    po_net = _money(payload.get("po_net"))
    before = _money(payload.get("invoiced_before_net"))
    invoice = _money(payload.get("invoice_net"))
    remaining = po_net - before
    if invoice <= remaining + MONEY_TOLERANCE:
        return []
    return [
        Finding(
            element_ref=str(payload.get("invoice_ref") or _po_ref(payload)),
            params={
                "po": _po_ref(payload),
                "invoice": _amount(invoice, payload),
                "remaining": _amount(max(remaining, Decimal("0")), payload),
                "excess": _amount(invoice - max(remaining, Decimal("0")), payload),
            },
            details={
                "po_net": str(po_net),
                "invoiced_before_net": str(before),
                "invoice_net": str(invoice),
                "remaining_net": str(remaining),
            },
        )
    ]


def check_invoice_quantity_received(payload: dict[str, Any]) -> list[Finding]:
    """Invoiced quantity per order line should not run ahead of goods received.

    Only once the order has a confirmed goods receipt: an order for services,
    or one whose deliveries are not booked in the system, has nothing to match
    and gets no warning. Lines the invoice does not bill are skipped.
    """
    if not payload.get("has_receipts"):
        return []
    findings: list[Finding] = []
    for line in payload.get("lines") or []:
        if not isinstance(line, dict):
            continue
        invoiced_now = _money(line.get("invoiced"))
        if invoiced_now <= 0:
            continue
        total = _money(line.get("invoiced_before")) + invoiced_now
        received = _money(line.get("received"))
        if total <= received + QUANTITY_TOLERANCE:
            continue
        label = str(line.get("label") or "?")
        unit = str(line.get("unit") or "").strip()
        findings.append(
            Finding(
                element_ref=label,
                params={
                    "line": label,
                    "invoiced": f"{total.normalize():f} {unit}".strip(),
                    "received": f"{received.normalize():f} {unit}".strip(),
                },
                details={
                    "invoiced_total": str(total),
                    "received": str(received),
                    "ordered": str(_money(line.get("ordered"))),
                },
            )
        )
    return findings


def check_invoice_value_received(payload: dict[str, Any]) -> list[Finding]:
    """An invoice billed as one sum should not run ahead of the value received.

    The quantity check needs invoice lines that name an order line. An invoice
    entered as a single amount has none, so it is weighed by value instead:
    everything invoiced on the order so far, this invoice included, against
    the confirmed receipts priced at the order's unit rates. Silent when the
    invoice carries matched quantities (the quantity check speaks then) or
    when nothing has been received yet.
    """
    if not payload.get("has_receipts"):
        return []
    lines = [line for line in payload.get("lines") or [] if isinstance(line, dict)]
    if any(_money(line.get("invoiced")) > 0 for line in lines):
        return []
    total = _money(payload.get("invoiced_before_net")) + _money(payload.get("invoice_net"))
    received = _money(payload.get("received_net"))
    if total <= received + MONEY_TOLERANCE:
        return []
    return [
        Finding(
            element_ref=str(payload.get("invoice_ref") or _po_ref(payload)),
            params={
                "po": _po_ref(payload),
                "invoiced": _amount(total, payload),
                "received": _amount(received, payload),
            },
            details={"invoiced_total_net": str(total), "received_net": str(received)},
        )
    ]
