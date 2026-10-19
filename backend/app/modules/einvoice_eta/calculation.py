# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The ETA line and document equations, computed and checked.

Source: https://sdk.invoicing.eta.gov.eg/document-validation-rules/ (simple
field validator). Rates are percentages: a ``rate`` of 14 is 14 per cent.

Per line, in this order because each step feeds the next:

    salesTotal        = quantity x unitValue.amountEGP
    discount.amount   = discount.rate x salesTotal        (only when the rate is not 0)
    netTotal          = salesTotal - discount.amount
    T5..T12 amount    = rate x netTotal                   (taxable fees, when a rate is given)
    totalTaxableFees  = sum of T5..T12 amounts
    T13..T20 amount   = rate x netTotal                   (non-taxable fees)
    T3                = a fixed amount, rate 0
    T2                = rate x (netTotal + totalTaxableFees + valueDifference + T3)
    T1 (VAT)          = rate x (netTotal + totalTaxableFees + valueDifference + T2 + T3)
    T4 (withholding)  = rate x (netTotal - itemsDiscount)
    total             = netTotal + T1 + T2 + T3 + totalTaxableFees + T13..T20
                        - itemsDiscount - T4

Per document: the sums of the line figures, tax totals per type with subtypes
ignored, and ``totalAmount = sum(line total) - extraDiscountAmount``.

The SDK's own sample satisfies every equation and is the test of this file.

Two halves. :func:`compute_line` and :func:`compute_document` build the
figures, rounding each to 5 decimals half up as ETA allows. :func:`check_document`
reads a finished document and reports every equation it breaks, comparing at
the precision the document itself wrote, with one unit in the last written
place allowed (never more than 0.01), because ETA publishes no tolerance and its
own sample is rounded to 2 places.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from app.modules.einvoice_eta.codes import (
    EGP,
    FIXED_AMOUNT_TYPES,
    NON_TAXABLE_FEES,
    TAX_TABLE_FIXED,
    TAX_TABLE_PERCENT,
    TAX_VAT,
    TAX_WITHHOLDING,
    TAXABLE_FEES,
    fixed_amount_subtypes,
)

PLACES = Decimal("0.00001")
ZERO = Decimal("0")
HUNDRED = Decimal("100")
MAX_TOLERANCE = Decimal("0.01")


def round5(value: Decimal) -> Decimal:
    """Round to the 5 decimals ETA accepts, half up."""
    return value.quantize(PLACES, rounding=ROUND_HALF_UP)


def _pct(rate: Decimal | None, base: Decimal) -> Decimal:
    return (rate or ZERO) * base / HUNDRED


@dataclass(frozen=True)
class TaxInput:
    """One taxable item asked for on a line."""

    tax_type: str
    sub_type: str
    rate: Decimal | None = None
    # For a fixed amount item (T3, T6, the "(amount)" subtypes) or a fee stated
    # as a sum rather than a rate.
    amount: Decimal | None = None

    def is_fixed(self) -> bool:
        return (
            self.tax_type in FIXED_AMOUNT_TYPES
            or self.sub_type in fixed_amount_subtypes()
            or (self.rate in (None, ZERO) and self.amount is not None)
        )


@dataclass(frozen=True)
class LineFigures:
    """The inputs of one line, all in EGP except ``unit_amount_sold``."""

    quantity: Decimal
    unit_amount_egp: Decimal
    discount_rate: Decimal | None = None
    discount_amount: Decimal | None = None
    items_discount: Decimal = ZERO
    value_difference: Decimal = ZERO
    taxes: tuple[TaxInput, ...] = ()


@dataclass(frozen=True)
class ComputedTax:
    tax_type: str
    sub_type: str
    rate: Decimal
    amount: Decimal


@dataclass(frozen=True)
class ComputedLine:
    sales_total: Decimal
    discount_rate: Decimal | None
    discount_amount: Decimal
    net_total: Decimal
    total_taxable_fees: Decimal
    total_non_taxable_fees: Decimal
    items_discount: Decimal
    value_difference: Decimal
    taxes: tuple[ComputedTax, ...]
    total: Decimal


@dataclass(frozen=True)
class ComputedDocument:
    total_sales_amount: Decimal
    total_discount_amount: Decimal
    net_amount: Decimal
    total_items_discount_amount: Decimal
    tax_totals: tuple[tuple[str, Decimal], ...]
    extra_discount_amount: Decimal
    total_amount: Decimal


def compute_line(figures: LineFigures) -> ComputedLine:
    """Every figure of one line, in the SDK's order, rounded to 5 places."""
    sales = round5(figures.quantity * figures.unit_amount_egp)
    if figures.discount_rate not in (None, ZERO):
        discount = round5(_pct(figures.discount_rate, sales))
    else:
        discount = round5(figures.discount_amount or ZERO)
    net = sales - discount

    by_type: dict[str, ComputedTax] = {}

    def fee(item: TaxInput) -> ComputedTax:
        if item.is_fixed():
            return ComputedTax(item.tax_type, item.sub_type, ZERO, round5(item.amount or ZERO))
        return ComputedTax(item.tax_type, item.sub_type, item.rate or ZERO, round5(_pct(item.rate, net)))

    for item in figures.taxes:
        if item.tax_type in TAXABLE_FEES or item.tax_type in NON_TAXABLE_FEES or item.tax_type == TAX_TABLE_FIXED:
            by_type[item.tax_type] = fee(item)

    taxable_fees = round5(sum((by_type[t].amount for t in TAXABLE_FEES if t in by_type), ZERO))
    non_taxable = round5(sum((by_type[t].amount for t in NON_TAXABLE_FEES if t in by_type), ZERO))
    t3 = by_type[TAX_TABLE_FIXED].amount if TAX_TABLE_FIXED in by_type else ZERO

    wanted = {item.tax_type: item for item in figures.taxes}
    t2 = ZERO
    if TAX_TABLE_PERCENT in wanted:
        item = wanted[TAX_TABLE_PERCENT]
        t2 = round5(_pct(item.rate, net + taxable_fees + figures.value_difference + t3))
        by_type[TAX_TABLE_PERCENT] = ComputedTax(item.tax_type, item.sub_type, item.rate or ZERO, t2)
    t1 = ZERO
    if TAX_VAT in wanted:
        item = wanted[TAX_VAT]
        t1 = round5(_pct(item.rate, net + taxable_fees + figures.value_difference + t2 + t3))
        by_type[TAX_VAT] = ComputedTax(item.tax_type, item.sub_type, item.rate or ZERO, t1)
    t4 = ZERO
    if TAX_WITHHOLDING in wanted:
        item = wanted[TAX_WITHHOLDING]
        t4 = round5(_pct(item.rate, net - figures.items_discount))
        by_type[TAX_WITHHOLDING] = ComputedTax(item.tax_type, item.sub_type, item.rate or ZERO, t4)

    total = net + t1 + t2 + t3 + taxable_fees + non_taxable - figures.items_discount - t4
    # Keep the order the caller asked for, which is the order they are written.
    ordered = tuple(by_type[item.tax_type] for item in figures.taxes if item.tax_type in by_type)
    return ComputedLine(
        sales_total=sales,
        discount_rate=figures.discount_rate,
        discount_amount=discount,
        net_total=net,
        total_taxable_fees=taxable_fees,
        total_non_taxable_fees=non_taxable,
        items_discount=figures.items_discount,
        value_difference=figures.value_difference,
        taxes=ordered,
        total=total,
    )


def compute_document(lines: list[ComputedLine], *, extra_discount_amount: Decimal = ZERO) -> ComputedDocument:
    """The document totals from its computed lines."""
    totals: dict[str, Decimal] = {}
    for line in lines:
        for tax in line.taxes:
            totals[tax.tax_type] = totals.get(tax.tax_type, ZERO) + tax.amount
    return ComputedDocument(
        total_sales_amount=sum((line.sales_total for line in lines), ZERO),
        total_discount_amount=sum((line.discount_amount for line in lines), ZERO),
        net_amount=sum((line.net_total for line in lines), ZERO),
        total_items_discount_amount=sum((line.items_discount for line in lines), ZERO),
        tax_totals=tuple(totals.items()),
        extra_discount_amount=extra_discount_amount,
        total_amount=sum((line.total for line in lines), ZERO) - extra_discount_amount,
    )


# ── Checking a finished document ─────────────────────────────────────────────


@dataclass(frozen=True)
class EquationBreak:
    """One equation a document does not satisfy."""

    path: str
    field: str
    expected: Decimal
    found: Decimal
    rule: str

    def message(self) -> str:
        return f"{self.path}: {self.field} is {self.found} but {self.rule} gives {round5(self.expected).normalize()}"


def _dec(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _tolerance(found: Decimal) -> Decimal:
    exponent = found.as_tuple().exponent
    places = -exponent if isinstance(exponent, int) and exponent < 0 else 0
    return min(Decimal(1).scaleb(-places), MAX_TOLERANCE)


def _close(found: Decimal, expected: Decimal) -> bool:
    return abs(found - expected) <= _tolerance(found)


def check_document(doc: dict[str, Any]) -> list[EquationBreak]:
    """Every line and document equation the document breaks.

    ``doc`` is the parsed document with numbers as :class:`~decimal.Decimal`
    (``json.loads(text, parse_float=Decimal, parse_int=Decimal)``). A field that
    is missing or not a number is not reported here: that is a structure
    finding, raised by the line and header checks, and reporting it twice
    would bury the arithmetic.
    """
    breaks: list[EquationBreak] = []

    def expect(path: str, field: str, found: Any, expected: Decimal, rule: str) -> None:
        value = _dec(found)
        if value is None:
            return
        if not _close(value, expected):
            breaks.append(EquationBreak(path, field, expected, value, rule))

    lines = doc.get("invoiceLines") if isinstance(doc.get("invoiceLines"), list) else []
    line_totals: list[Decimal] = []
    sums = {"salesTotal": ZERO, "discount": ZERO, "netTotal": ZERO, "itemsDiscount": ZERO}
    tax_sums: dict[str, Decimal] = {}

    for index, line in enumerate(lines):
        if not isinstance(line, dict):
            continue
        path = f"invoiceLines[{index}]"
        quantity = _dec(line.get("quantity")) or ZERO
        unit = line.get("unitValue") if isinstance(line.get("unitValue"), dict) else {}
        amount_egp = _dec(unit.get("amountEGP")) or ZERO
        currency = str(unit.get("currencySold") or "").strip().upper()
        if currency and currency != EGP:
            sold = _dec(unit.get("amountSold"))
            rate = _dec(unit.get("currencyExchangeRate"))
            if sold is not None and rate is not None:
                expect(path, "unitValue.amountEGP", unit.get("amountEGP"), sold * rate, "amountSold x exchange rate")

        sales = _dec(line.get("salesTotal")) or ZERO
        expect(path, "salesTotal", line.get("salesTotal"), quantity * amount_egp, "quantity x amountEGP")

        discount = line.get("discount") if isinstance(line.get("discount"), dict) else {}
        discount_amount = _dec(discount.get("amount")) or ZERO
        discount_rate = _dec(discount.get("rate"))
        if discount_rate not in (None, ZERO):
            expect(
                path,
                "discount.amount",
                discount.get("amount"),
                _pct(discount_rate, sales),
                "discount rate x salesTotal",
            )

        net = _dec(line.get("netTotal")) or ZERO
        expect(path, "netTotal", line.get("netTotal"), sales - discount_amount, "salesTotal - discount")

        items = line.get("taxableItems") if isinstance(line.get("taxableItems"), list) else []
        by_type: dict[str, dict[str, Any]] = {}
        for item in items:
            if isinstance(item, dict):
                by_type.setdefault(str(item.get("taxType") or "").strip(), item)

        def amount_of(tax_type: str, _by_type: dict[str, dict[str, Any]] = by_type) -> Decimal:
            item = _by_type.get(tax_type)
            return (_dec(item.get("amount")) or ZERO) if item else ZERO

        for tax_type in (*TAXABLE_FEES, *NON_TAXABLE_FEES):
            item = by_type.get(tax_type)
            if not item:
                continue
            rate = _dec(item.get("rate"))
            if rate not in (None, ZERO) and str(item.get("subType") or "") not in fixed_amount_subtypes():
                expect(path, f"{tax_type}.amount", item.get("amount"), _pct(rate, net), f"{tax_type} rate x netTotal")

        taxable_fees = sum((amount_of(t) for t in TAXABLE_FEES), ZERO)
        non_taxable = sum((amount_of(t) for t in NON_TAXABLE_FEES), ZERO)
        expect(path, "totalTaxableFees", line.get("totalTaxableFees"), taxable_fees, "the sum of T5-T12")

        value_difference = _dec(line.get("valueDifference")) or ZERO
        items_discount = _dec(line.get("itemsDiscount")) or ZERO
        t3 = amount_of(TAX_TABLE_FIXED)
        t2 = amount_of(TAX_TABLE_PERCENT)
        if TAX_TABLE_PERCENT in by_type:
            rate = _dec(by_type[TAX_TABLE_PERCENT].get("rate")) or ZERO
            expect(
                path,
                "T2.amount",
                by_type[TAX_TABLE_PERCENT].get("amount"),
                _pct(rate, net + taxable_fees + value_difference + t3),
                "T2 rate x (netTotal + taxable fees + valueDifference + T3)",
            )
        t1 = amount_of(TAX_VAT)
        if TAX_VAT in by_type:
            rate = _dec(by_type[TAX_VAT].get("rate")) or ZERO
            expect(
                path,
                "T1.amount",
                by_type[TAX_VAT].get("amount"),
                _pct(rate, net + taxable_fees + value_difference + t2 + t3),
                "T1 rate x (netTotal + taxable fees + valueDifference + T2 + T3)",
            )
        t4 = amount_of(TAX_WITHHOLDING)
        if TAX_WITHHOLDING in by_type:
            rate = _dec(by_type[TAX_WITHHOLDING].get("rate")) or ZERO
            expect(
                path,
                "T4.amount",
                by_type[TAX_WITHHOLDING].get("amount"),
                _pct(rate, net - items_discount),
                "T4 rate x (netTotal - itemsDiscount)",
            )

        expected_total = net + t1 + t2 + t3 + taxable_fees + non_taxable - items_discount - t4
        expect(
            path,
            "total",
            line.get("total"),
            expected_total,
            "netTotal + taxes and fees - itemsDiscount - withholding",
        )
        line_totals.append(_dec(line.get("total")) or ZERO)
        sums["salesTotal"] += sales
        sums["discount"] += discount_amount
        sums["netTotal"] += net
        sums["itemsDiscount"] += items_discount
        for tax_type in by_type:
            tax_sums[tax_type] = tax_sums.get(tax_type, ZERO) + amount_of(tax_type)

    expect("document", "totalSalesAmount", doc.get("totalSalesAmount"), sums["salesTotal"], "the sum of salesTotal")
    expect(
        "document", "totalDiscountAmount", doc.get("totalDiscountAmount"), sums["discount"], "the sum of line discounts"
    )
    expect("document", "netAmount", doc.get("netAmount"), sums["netTotal"], "the sum of netTotal")
    expect(
        "document",
        "totalItemsDiscountAmount",
        doc.get("totalItemsDiscountAmount"),
        sums["itemsDiscount"],
        "the sum of itemsDiscount",
    )
    totals = doc.get("taxTotals") if isinstance(doc.get("taxTotals"), list) else []
    for entry in totals:
        if not isinstance(entry, dict):
            continue
        tax_type = str(entry.get("taxType") or "").strip()
        expect(
            "document",
            f"taxTotals[{tax_type}]",
            entry.get("amount"),
            tax_sums.get(tax_type, ZERO),
            f"the sum of {tax_type} over the lines",
        )
    listed = {str(e.get("taxType") or "").strip() for e in totals if isinstance(e, dict)}
    for tax_type, amount in tax_sums.items():
        if tax_type and tax_type not in listed and amount != ZERO:
            breaks.append(
                EquationBreak(
                    "document", f"taxTotals[{tax_type}]", amount, ZERO, f"the sum of {tax_type} over the lines"
                )
            )
    extra = _dec(doc.get("extraDiscountAmount")) or ZERO
    expect(
        "document",
        "totalAmount",
        doc.get("totalAmount"),
        sum(line_totals, ZERO) - extra,
        "the sum of line totals - extraDiscountAmount",
    )
    return breaks


__all__ = [
    "ComputedDocument",
    "ComputedLine",
    "ComputedTax",
    "EquationBreak",
    "LineFigures",
    "TaxInput",
    "check_document",
    "compute_document",
    "compute_line",
    "round5",
]
