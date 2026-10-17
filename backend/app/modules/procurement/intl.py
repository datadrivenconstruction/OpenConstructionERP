# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""International, framework-free procurement helpers.

This module holds small, side-effect-free helpers that make procurement money
and delivery math correct and clear for users anywhere in the world. It has no
database, no FastAPI, and no third-party dependency, so it imports and runs the
same in a unit test as it does in the request path.

Design rules that keep the platform usable worldwide:

* No hardcoded currency, tax rate, unit, or locale. Every rate is a parameter
  with a documented default of "no tax / no discount" so a caller in any
  country supplies their own figure.
* Money is Decimal-exact. Amounts never touch ``float`` and never drift.
* Money is never summed across different currency codes. Mixing codes is a
  clean input error, not a silently-wrong total.
* Dates are ISO 8601 (``YYYY-MM-DD``). Quantities always carry an explicit
  unit label so "100" is never ambiguous.
* Bad input (garbage numbers, negative quantities, division by zero) is turned
  into a clear ``ValueError`` or a well-defined zero. It never becomes a 500,
  a NaN, or an infinity.

The service layer keeps its own ``HTTPException``-raising helpers. These
functions raise plain ``ValueError`` so they stay reusable outside a request
(reports, exports, background jobs, tests). A caller in the router can wrap a
``ValueError`` in a 400 if it reaches the API edge.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

# Default money rounding step. Two decimal places suit most currencies; a
# caller working in a zero-decimal or four-decimal currency passes its own
# ``quantum``. This is a default, never a hardcoded assumption.
DEFAULT_MONEY_QUANTUM = Decimal("0.01")

# ISO 8601 calendar date shape used across the module.
ISO_DATE_FORMAT = "YYYY-MM-DD"


# ── Plain-language glossary ───────────────────────────────────────────────────

# One line per procurement concept, in plain words a site engineer or estimator
# understands in a few seconds. Kept here so the API and reports explain every
# figure they show instead of assuming the reader knows the jargon.
CONCEPTS: dict[str, str] = {
    "line_total": "The cost of one order line: quantity multiplied by the unit rate.",
    "subtotal": "The sum of all order line totals, before tax and before any discount.",
    "net": "The amount payable after any discount but before tax is added.",
    "tax": "The tax added on top of the net amount, using the tax rate you set.",
    "gross": "The final amount payable: net plus tax. Also called the total.",
    "purchase_order_total": ("The full amount a purchase order commits to a supplier: net plus tax."),
    "discount": "A percentage taken off the list price before tax is calculated.",
    "lead_time": "The number of days a supplier needs between the order and the delivery.",
    "expected_delivery_date": ("The date delivery is expected: the order date plus the supplier lead time in days."),
    "committed_cost": (
        "Money promised to a supplier by an approved purchase order, whether or not it is paid or delivered yet."
    ),
    "delivered_vs_ordered": ("How much of what you ordered has actually arrived, as a share of the ordered quantity."),
    "coverage": "The share of the ordered quantity that has been delivered, from 0 to 1.",
    "outstanding": "The quantity still to be delivered: ordered minus delivered, never below zero.",
    "over_delivered": "Quantity delivered above what was ordered: delivered minus ordered.",
    "retainage": ("A percentage of the amount held back from the supplier until the work is accepted."),
}


def explain(concept: str) -> str:
    """Return a one-line plain-language explanation of a procurement concept.

    ``concept`` is one of the keys in :data:`CONCEPTS` (for example
    ``"gross"`` or ``"lead_time"``). Raises ``ValueError`` for an unknown key
    so a typo is caught rather than silently returning nothing.
    """
    try:
        return CONCEPTS[concept]
    except KeyError as exc:
        known = ", ".join(sorted(CONCEPTS))
        raise ValueError(f"Unknown procurement concept {concept!r}. Known: {known}.") from exc


# ── Plain-language status labels ──────────────────────────────────────────────

# Purchase-order lifecycle, labelled in plain words. Mirrors the FSM in
# ``service._PO_STATUS_TRANSITIONS`` so the codes stay in step.
PO_STATUS_LABELS: dict[str, str] = {
    "draft": "Draft, not yet approved",
    "approved": "Approved, budget committed",
    "issued": "Issued to the supplier",
    "partially_received": "Part of the order has been delivered",
    "completed": "Fully delivered and closed",
    "cancelled": "Cancelled",
}

# Goods-receipt (delivery) lifecycle in plain words.
DELIVERY_STATUS_LABELS: dict[str, str] = {
    "draft": "Delivery recorded, not yet confirmed",
    "confirmed": "Delivery confirmed and counted",
}

# Material-requisition lifecycle in plain words. Mirrors the FSM in
# ``service._MR_STATUS_TRANSITIONS``.
REQUISITION_STATUS_LABELS: dict[str, str] = {
    "draft": "Draft request, not yet submitted",
    "submitted": "Submitted for approval",
    "approved": "Approved, ready to order",
    "ordered": "Ordered from a supplier",
    "received": "Received on site",
    "consumed": "Used up on the works",
    "rejected": "Rejected, needs revision",
    "cancelled": "Cancelled",
}


def describe_po_status(code: str | None) -> str:
    """Return a plain-language label for a purchase-order status code.

    An unknown or empty code falls back to a readable form of the raw code
    rather than raising, so the UI never shows a blank or crashes on a status
    a newer module introduced.
    """
    return _label(code, PO_STATUS_LABELS)


def describe_delivery_status(code: str | None) -> str:
    """Return a plain-language label for a goods-receipt (delivery) status code."""
    return _label(code, DELIVERY_STATUS_LABELS)


def describe_requisition_status(code: str | None) -> str:
    """Return a plain-language label for a material-requisition status code."""
    return _label(code, REQUISITION_STATUS_LABELS)


def _label(code: str | None, table: dict[str, str]) -> str:
    """Look ``code`` up in ``table``; fall back to a humanised raw code."""
    if not code:
        return "Unknown"
    known = table.get(code)
    if known is not None:
        return known
    # Unknown code from a newer workflow: show it readably, never blank.
    return code.replace("_", " ").strip().capitalize()


# ── Decimal parsing (strict, plain ValueError) ────────────────────────────────


def to_decimal(value: object, field: str = "value") -> Decimal:
    """Parse ``value`` into a finite ``Decimal`` or raise a clear ``ValueError``.

    Rejects ``None``, empty strings, non-numeric text, and non-finite values
    (``NaN`` / infinity) so a bad figure can never turn into a silent NaN in a
    total. ``field`` names the offending input in the error message.
    """
    if value is None:
        raise ValueError(f"{field} is required (got None).")
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{field} is not a valid number: {value!r}.") from exc
    if not parsed.is_finite():
        raise ValueError(f"{field} must be a finite number, got {value!r}.")
    return parsed


def _non_negative(value: Decimal, field: str) -> Decimal:
    """Return ``value`` if it is >= 0, else raise a clear ``ValueError``."""
    if value < 0:
        raise ValueError(f"{field} must not be negative, got {value}.")
    return value


def quantize_money(amount: Decimal, quantum: Decimal = DEFAULT_MONEY_QUANTUM) -> Decimal:
    """Round a money amount to ``quantum`` using commercial half-up rounding.

    Half-up is the rounding people expect on an invoice. The default step is
    two decimal places; pass another ``quantum`` for a currency that uses a
    different number of minor units.
    """
    return amount.quantize(quantum, rounding=ROUND_HALF_UP)


# ── Currency safety ───────────────────────────────────────────────────────────


def normalize_currency(code: str | None) -> str:
    """Return an upper-case, trimmed currency code, or ``""`` if unknown.

    An empty result means "currency not stated". It never guesses a default
    currency such as EUR or USD.
    """
    if not code:
        return ""
    return str(code).strip().upper()


def ensure_single_currency(codes: Iterable[str | None]) -> str:
    """Return the one currency shared by ``codes``, or raise on a mix.

    Empty or missing codes are treated as "not stated" and ignored. If two or
    more different stated currencies appear, a ``ValueError`` is raised so the
    caller never sums amounts that are in different currencies. Returns ``""``
    when no currency is stated at all.
    """
    stated: set[str] = set()
    for code in codes:
        normalized = normalize_currency(code)
        if normalized:
            stated.add(normalized)
    if len(stated) > 1:
        raise ValueError(
            "Cannot combine amounts in different currencies: "
            f"{', '.join(sorted(stated))}. Convert to one currency first."
        )
    return stated.pop() if stated else ""


# ── Quantities (always carry a unit) ──────────────────────────────────────────


def format_quantity(value: object, unit: str | None) -> str:
    """Render a quantity with its unit, for example ``"100 m3"``.

    A missing unit renders the bare number rather than an empty unit, so the
    value is never lost. The number keeps full precision and stays out of
    scientific notation.
    """
    number = to_decimal(value, "quantity")
    text = format(number.normalize(), "f")
    unit_text = (unit or "").strip()
    return f"{text} {unit_text}".strip()


# ── Money math ────────────────────────────────────────────────────────────────


def line_total(quantity: object, unit_rate: object, *, allow_zero: bool = True) -> Decimal:
    """Return one order line total = quantity multiplied by unit rate.

    Both inputs must be non-negative finite numbers. With ``allow_zero=False``
    a zero quantity or zero rate is rejected (useful when a caller wants to
    forbid empty lines). The result is exact and is not rounded here so it can
    be summed without accumulating rounding error; round the subtotal instead.
    """
    qty = _non_negative(to_decimal(quantity, "quantity"), "quantity")
    rate = _non_negative(to_decimal(unit_rate, "unit_rate"), "unit_rate")
    if not allow_zero and (qty == 0 or rate == 0):
        raise ValueError("Quantity and unit rate must both be greater than zero.")
    return qty * rate


def subtotal(line_totals: Iterable[object]) -> Decimal:
    """Sum order line totals into a subtotal.

    An empty list yields a well-defined ``Decimal("0")`` rather than an error.
    Each entry must be a non-negative finite number. The subtotal is exact and
    is not rounded here; round it when you present it.
    """
    total = Decimal("0")
    for index, value in enumerate(line_totals):
        total += _non_negative(to_decimal(value, f"line_totals[{index}]"), f"line_totals[{index}]")
    return total


def subtotal_from_lines(
    lines: Iterable[tuple[object, object]],
    *,
    allow_zero: bool = True,
) -> Decimal:
    """Sum ``(quantity, unit_rate)`` pairs into a subtotal.

    A convenience over :func:`subtotal` that computes each line total for you.
    An empty list yields ``Decimal("0")``.
    """
    return subtotal(line_total(qty, rate, allow_zero=allow_zero) for qty, rate in lines)


def price_breakdown(
    subtotal_amount: object,
    *,
    tax_rate_percent: object = Decimal("0"),
    discount_percent: object = Decimal("0"),
    quantum: Decimal = DEFAULT_MONEY_QUANTUM,
) -> dict[str, str]:
    """Break a subtotal down into discount, net, tax, and gross, all explained.

    Order of operations, the common commercial convention:

        discount_amount = subtotal * discount_percent / 100
        net             = subtotal - discount_amount
        tax_amount      = net * tax_rate_percent / 100
        gross           = net + tax_amount

    ``tax_rate_percent`` and ``discount_percent`` both default to zero, so with
    no rates supplied the gross equals the subtotal. Both must be non-negative,
    and the discount may not exceed 100 percent. Money outputs are rounded to
    ``quantum`` (default two decimals) with half-up rounding and returned as
    Decimal strings, matching the money-as-string contract used across the API.
    Percentages are echoed back so a report can show exactly what was applied.
    """
    base = _non_negative(to_decimal(subtotal_amount, "subtotal_amount"), "subtotal_amount")
    tax_rate = _non_negative(to_decimal(tax_rate_percent, "tax_rate_percent"), "tax_rate_percent")
    discount = _non_negative(to_decimal(discount_percent, "discount_percent"), "discount_percent")
    if discount > Decimal("100"):
        raise ValueError(f"discount_percent must be between 0 and 100, got {discount}.")

    hundred = Decimal("100")
    discount_amount = base * discount / hundred
    net = base - discount_amount
    tax_amount = net * tax_rate / hundred
    gross = net + tax_amount

    return {
        "subtotal": str(quantize_money(base, quantum)),
        "discount_percent": str(discount),
        "discount_amount": str(quantize_money(discount_amount, quantum)),
        "net": str(quantize_money(net, quantum)),
        "tax_rate_percent": str(tax_rate),
        "tax_amount": str(quantize_money(tax_amount, quantum)),
        "gross": str(quantize_money(gross, quantum)),
    }


def tax_and_gross(
    net_amount: object,
    tax_rate_percent: object = Decimal("0"),
    *,
    quantum: Decimal = DEFAULT_MONEY_QUANTUM,
) -> dict[str, str]:
    """Return tax and gross for a net amount at a given tax rate.

    ``tax_rate_percent`` defaults to zero (no tax), so a caller in a
    tax-exempt context or a country whose rate you do not assume gets a gross
    equal to the net. The rate must be non-negative. Outputs are rounded money
    Decimal strings.
    """
    net = _non_negative(to_decimal(net_amount, "net_amount"), "net_amount")
    tax_rate = _non_negative(to_decimal(tax_rate_percent, "tax_rate_percent"), "tax_rate_percent")
    tax_amount = net * tax_rate / Decimal("100")
    gross = net + tax_amount
    return {
        "net": str(quantize_money(net, quantum)),
        "tax_rate_percent": str(tax_rate),
        "tax_amount": str(quantize_money(tax_amount, quantum)),
        "gross": str(quantize_money(gross, quantum)),
    }


# ── Delivery timing ───────────────────────────────────────────────────────────


def expected_delivery_date(order_date: str | None, lead_time_days: object) -> str | None:
    """Return the expected delivery date = order date plus lead-time days.

    This is the forward-looking companion to the service helper
    ``_latest_order_date`` (which subtracts a lead time from a required
    date to find the latest order date). Here you know when you ordered and how
    many days the supplier needs, and you want the arrival date.

    ``order_date`` is an ISO 8601 ``YYYY-MM-DD`` string. ``lead_time_days`` must
    be a non-negative whole number of calendar days (not working days). A zero
    lead time means same-day delivery and returns the order date unchanged.
    Returns ``None`` when the order date is missing or unparseable, so a bad
    stored date degrades to "unknown" rather than raising. A negative lead time
    is a genuine input error and raises ``ValueError``.
    """
    days = to_decimal(lead_time_days, "lead_time_days")
    if days < 0:
        raise ValueError(f"lead_time_days must not be negative, got {days}.")
    if days != days.to_integral_value():
        raise ValueError(f"lead_time_days must be a whole number of days, got {days}.")
    if not order_date:
        return None
    try:
        ordered = date.fromisoformat(str(order_date).strip())
    except (ValueError, TypeError):
        return None
    return (ordered + timedelta(days=int(days))).isoformat()


# ── Delivered vs ordered coverage ─────────────────────────────────────────────


def delivery_coverage(delivered: object, ordered: object) -> dict[str, str]:
    """Compare delivered quantity against ordered quantity, with a zero guard.

    Returns a small report a UI can show directly:

        * ``ordered`` / ``delivered``  - the two input quantities, echoed.
        * ``outstanding``   - ordered minus delivered, never below zero.
        * ``over_delivered``- delivered minus ordered, never below zero.
        * ``coverage``      - delivered divided by ordered, from 0 to 1.
        * ``coverage_percent`` - the same figure as a 0 to 100 percentage.
        * ``is_complete``   - true once delivered covers the full order.

    Both inputs must be non-negative finite numbers. Ordering zero is not an
    error: coverage is defined as ``1`` (fully covered, nothing was due) when
    nothing was ordered, guarding against division by zero. Coverage never
    exceeds 1 even when more was delivered than ordered; the surplus shows up
    in ``over_delivered`` instead.
    """
    ordered_qty = _non_negative(to_decimal(ordered, "ordered"), "ordered")
    delivered_qty = _non_negative(to_decimal(delivered, "delivered"), "delivered")

    outstanding = max(ordered_qty - delivered_qty, Decimal("0"))
    over_delivered = max(delivered_qty - ordered_qty, Decimal("0"))

    if ordered_qty == 0:
        # Nothing was ordered, so there is nothing left to deliver. Coverage is
        # fully met by definition; this is the division-by-zero guard.
        coverage = Decimal("1")
    else:
        coverage = min(delivered_qty / ordered_qty, Decimal("1"))

    coverage = coverage.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    coverage_percent = (coverage * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    is_complete = delivered_qty >= ordered_qty

    return {
        "ordered": format(ordered_qty.normalize(), "f"),
        "delivered": format(delivered_qty.normalize(), "f"),
        "outstanding": format(outstanding.normalize(), "f"),
        "over_delivered": format(over_delivered.normalize(), "f"),
        "coverage": str(coverage),
        "coverage_percent": str(coverage_percent),
        "is_complete": "true" if is_complete else "false",
    }
