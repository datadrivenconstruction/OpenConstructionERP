# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The hakediş (Turkish progress payment certificate) as a pure computation.

:func:`compute_certificate` turns a :class:`CertificateInput` into a
:class:`Certificate`: one result per work line and one per summary line. No
database, no I/O, no knowledge of where the input came from, so the claim a
subcontractor submits upward and the application it certifies downward are the
same calculation over two adapters.

Rounding. Every amount is rounded half up to the currency's own quantum
(:func:`app.core.currency_registry.money_quantum`), once, at the line:

* a unit-price row prints cumulative ``q(cumulative quantity x unit price)`` and
  previous ``q(previous quantity x unit price)``; the period amount is their
  difference and is never rounded on its own. The previous amount of one
  certificate is therefore to the cent the cumulative amount of the one before,
  and a row always adds up across its three money columns;
* a lump-sum row prints ``q(contract amount x percent / 100)``, with the row's
  own contract amount taken whole at one hundred percent, and its period amount
  by the same subtraction. A finished job lands exactly on the contract amount
  however the percentages were split on the way;
* column totals are the sums of the printed rows, and line A of the summary is
  the cumulative column total, so the summary and the works list cannot differ.

Value, not applicable, held. A figure nobody can vouch for is ``held``: it has
no amount, it prints a marker instead of a number, and every total that would
have included it is held too, with a basis naming which operand held it. A
figure that does not apply prints a dash and adds nothing. Nothing here falls
back to a plausible zero.

The second half of the module is the print model: the rows, labels, formulas
and number formats the PDF and the workbook both draw, so the two documents
cannot disagree about what a line says.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal
from types import MappingProxyType
from typing import Any, Literal

from app.core.currency_registry import minor_units, money_quantum
from app.core.payment_taxes import Figure, PaymentTaxResult
from app.core.regional_format import NumberStyle, format_date, format_number, number_style
from app.modules.contracts.hakedis_layout import (
    HAKEDIS_LABELS,
    WORKS_COLUMNS,
    WORKS_DEFAULT_COLUMNS,
    ColumnDef,
    HakedisSettings,
    SummaryLineDef,
    evaluation_order,
    label,
    label_filled,
    line_formula,
    locale_languages,
    validate_layout,
)

__all__ = [
    "Certificate",
    "CertificateInput",
    "CertificateParty",
    "CertificateWorkLine",
    "DocumentNote",
    "ManualLine",
    "PrintedSummaryLine",
    "PrintedWorkRow",
    "SummaryLine",
    "WorkLineResult",
    "WorkTotals",
    "compute_certificate",
    "document_notes",
    "expected_tax_bases",
    "format_money",
    "format_percent",
    "format_quantity",
    "header_columns",
    "header_rows",
    "reason_text",
    "lump_sum_line_amounts",
    "manual_lines_for",
    "note_text",
    "printed_summary",
    "printed_works",
    "works_columns",
]

DEC_ZERO = Decimal("0")
DEC_HUNDRED = Decimal("100")

Status = Literal["value", "not_applicable", "held"]

#: Printed in place of an amount that does not apply.
DASH = "-"


# ── Input ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CertificateParty:
    """A party named in the header: the employer or the contractor."""

    name: str
    tax_number: str = ""
    tax_office: str = ""
    address: str = ""


@dataclass(frozen=True)
class CertificateWorkLine:
    """One row of the works list, before any arithmetic.

    A unit-price row carries ``previous_quantity``, ``period_quantity`` and
    ``unit_price``; ``contract_quantity`` is optional and only feeds the
    over-measurement flag. A lump-sum row carries ``contract_amount`` (the
    row's own share of the contract price, not the whole price),
    ``previous_pct`` and ``period_pct`` as the row's own completion from 0 to
    100; ``weight_pct`` (pursantaj) is printed, not computed with.

    A period quantity or percent may be negative: that is how an earlier
    over-measurement is corrected.

    ``stated_previous_amount`` and ``stated_period_amount`` are the amounts
    the source document already carries for the row: what the certificates
    before this one billed on it, and what this one bills. A certificate
    printed from a stored claim has to say what the claim says, because the
    invoice is raised from the claim; a product worked out again here can
    differ from it by a rounding step, or by more once a rate was changed
    between two claims. When both are given they are the row's money, the
    quantities or percents are printed beside them, and the product they would
    have given is kept on the result so the difference can be reported. A row
    with stated amounts needs no quantity, price or percent at all: that is
    how money billed outside the schedule gets a row.
    """

    code: str
    description: str
    unit: str
    contract_quantity: Decimal | None
    previous_quantity: Decimal | None
    period_quantity: Decimal | None
    unit_price: Decimal | None
    contract_amount: Decimal | None
    weight_pct: Decimal | None
    previous_pct: Decimal | None
    period_pct: Decimal | None
    section: str = ""
    stated_previous_amount: Decimal | None = None
    stated_period_amount: Decimal | None = None


@dataclass(frozen=True)
class ManualLine:
    """What a person entered for one manual summary line.

    ``pct`` is an addition to the binding design's shape, defaulted so every
    call written against that shape still holds: with ``status="value"`` and
    no ``amount``, the amount is ``pct`` percent of the line's base (the
    operands of its definition), which is how an advance is recovered pro rata
    without the caller having to know this certificate's amount first.
    """

    key: str
    status: Status
    amount: Decimal | None
    note: str = ""
    pct: Decimal | None = None


@dataclass(frozen=True)
class CertificateInput:
    """Everything one certificate is computed and printed from.

    ``previous_certified_total`` is line C (work plus price adjustment, both
    cumulative) of the previous certificate: ``Decimal("0")`` for the first
    certificate, ``None`` when it is not known, which holds the line. A manual
    price adjustment is entered cumulative, like line A.

    ``taxes`` is one run of the shared calculation, and one run has one net
    amount. A tax line whose base is another amount (on the standard Turkish
    form the stamp duty, charged on line E less the advance recovered) takes
    its figure from ``taxes_by_line[<line key>]`` instead: a second run of the
    same calculation on that line's own base, which
    :func:`expected_tax_bases` gives. A line with no entry there reads
    ``taxes``.

    ``tax_conditions`` is the condition a rate row is subject to, by line key
    and already in the document's language. A figure does not carry it, so
    whoever looked the row up passes it here and it is printed under the line.

    ``tax_status`` says whether a person has signed the tax figures:
    ``"draft"``, ``"confirmed"``, or empty when the caller does not know. A
    result cannot say it, and the document has to: with ``"draft"`` it carries
    a note that the taxes are not confirmed and so prints as a draft. With
    ``"confirmed"`` a rate that is unconfirmed at its source, or an amount
    entered by hand, no longer makes the document a draft, because confirming
    is where a person accepted both.

    ``previous_held_reason`` is the reason printed when
    ``previous_certified_total`` is ``None``: nobody knows it, or a previous
    certificate exists and has not been certified yet.
    """

    flavour: Literal["unit_price", "lump_sum"]
    certificate_number: int
    is_final: bool
    period_start: date
    period_end: date
    currency: str
    country_code: str
    project_name: str
    contract_number: str
    contract_title: str
    employer: CertificateParty
    contractor: CertificateParty
    lines: Sequence[CertificateWorkLine]
    previous_certified_total: Decimal | None
    manual_lines: Mapping[str, ManualLine]
    retention_pct: Decimal | None
    taxes: PaymentTaxResult | None
    layout: Sequence[SummaryLineDef]
    signature_roles: Sequence[str]
    taxes_by_line: Mapping[str, PaymentTaxResult] = field(default_factory=dict)
    tax_conditions: Mapping[str, str] = field(default_factory=dict)
    tax_status: str = ""
    previous_held_reason: str = "previous_unknown"
    previous_held_params: Mapping[str, str] = field(default_factory=dict)


# ── Result ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class WorkLineResult:
    """One works list row with its previous, period and cumulative figures.

    Attributes:
        line: The input row.
        index: Position in the input, from 1: the printed "Sıra No".
        status: ``held`` when the row lacks a figure it cannot be computed
            without; its amounts are then ``None`` and line A is held.
        reason: Which figure is missing, for a held row.
        previous_quantity: Quantity up to the previous certificate (unit price).
        period_quantity: Quantity of this certificate.
        cumulative_quantity: Their sum.
        previous_pct: Completion up to the previous certificate (lump sum).
        period_pct: Completion added by this certificate.
        cumulative_pct: Their sum.
        contract_amount: The row's contract value where it is known.
        previous_amount: Amount up to the previous certificate.
        period_amount: Cumulative less previous.
        cumulative_amount: Amount to date.
        over_measured: The cumulative quantity is above the contract quantity,
            or the cumulative percent above one hundred. Not blocked here; a
            validation rule reads the flag.
        over_by: By how much, in the unit of the quantity or in percent points.
        computed_cumulative_amount: What quantity times price, or contract
            amount times percent, gives for the row to date, where the row's
            money was stated by its source instead. ``None`` when the row was
            computed here, or cannot be.
    """

    line: CertificateWorkLine
    index: int
    status: Literal["value", "held"]
    reason: str
    previous_quantity: Decimal | None
    period_quantity: Decimal | None
    cumulative_quantity: Decimal | None
    previous_pct: Decimal | None
    period_pct: Decimal | None
    cumulative_pct: Decimal | None
    contract_amount: Decimal | None
    previous_amount: Decimal | None
    period_amount: Decimal | None
    cumulative_amount: Decimal | None
    over_measured: bool = False
    over_by: Decimal | None = None
    computed_cumulative_amount: Decimal | None = None

    # The input's descriptive fields, so a column can be read off the result alone.
    @property
    def code(self) -> str:
        return self.line.code

    @property
    def description(self) -> str:
        return self.line.description

    @property
    def unit(self) -> str:
        return self.line.unit

    @property
    def section(self) -> str:
        return self.line.section

    @property
    def unit_price(self) -> Decimal | None:
        return self.line.unit_price

    @property
    def contract_quantity(self) -> Decimal | None:
        return self.line.contract_quantity

    @property
    def weight_pct(self) -> Decimal | None:
        return self.line.weight_pct

    @property
    def seq(self) -> int:
        return self.index


@dataclass(frozen=True)
class WorkTotals:
    """Column totals of a set of work rows: the sums of the printed amounts."""

    previous_amount: Decimal
    period_amount: Decimal
    cumulative_amount: Decimal
    contract_amount: Decimal | None


@dataclass(frozen=True)
class SummaryLine:
    """One computed line of the summary.

    ``basis`` is what an accountant needs to check the figure, as strings:
    ``base``, ``rate_pct`` or ``numerator`` and ``denominator``, ``code``,
    ``legal_reference``, ``effective_from``, ``review_status``, ``overridden``
    (``"true"`` or ``"false"``), and for a held line ``reason`` with its
    ``reason.<name>`` parameters and ``held_operands``.
    """

    key: str
    letter: str
    status: Status
    amount: Decimal | None
    basis: Mapping[str, str]
    section: str


@dataclass(frozen=True)
class DocumentNote:
    """Why the document is a draft: one numbered note of the footnote block."""

    number: int
    line_key: str
    letter: str
    reason_key: str
    params: Mapping[str, str]


@dataclass(frozen=True)
class Certificate:
    """A computed certificate: its input, its work rows and its summary."""

    inp: CertificateInput
    work_lines: Sequence[WorkLineResult]
    summary: Sequence[SummaryLine]
    payable: SummaryLine

    def line(self, key: str) -> SummaryLine:
        """The summary line with this key.

        Raises:
            KeyError: The layout has no such line.
        """
        for item in self.summary:
            if item.key == key:
                return item
        raise KeyError(key)

    @property
    def totals(self) -> WorkTotals:
        """Column totals over every work row that has amounts."""
        return _totals(self.work_lines)

    @property
    def notes(self) -> tuple[DocumentNote, ...]:
        """The numbered reasons this document is not final, empty when it is."""
        return document_notes(self)

    @property
    def is_draft(self) -> bool:
        """True when any line is held, or any figure is unconfirmed or overridden."""
        return bool(self.notes)


# ── Arithmetic ────────────────────────────────────────────────────────────


def _q(value: Decimal, currency: str) -> Decimal:
    """Round money half up to the currency's quantum."""
    return value.quantize(money_quantum(currency), rounding=ROUND_HALF_UP)


def lump_sum_line_amounts(contract_total: Decimal, weights: Sequence[Decimal], currency: str) -> list[Decimal]:
    """Split a contract price across work groups by weight, to the cent.

    Weights (pursantaj) rarely add up to exactly one hundred: seven groups of
    14.2857 make 99.9999, and a price times each weight then never adds up to
    the price. The shares are taken relative to the weights' own sum and
    rounded by largest remainder, the algorithm of ``aia._allocate_to_cents``,
    so they always add up to the rounded contract price.

    Raises:
        ValueError: The weights add up to zero.
    """
    if not weights:
        return []
    weight_sum = sum(weights, DEC_ZERO)
    if weight_sum == 0:
        raise ValueError("lump-sum weights add up to zero")
    if any(weight < 0 for weight in weights):
        raise ValueError("a lump-sum weight is negative")
    if _q(contract_total, currency) != contract_total:
        raise ValueError(f"contract total {contract_total} has more decimals than {currency} allows")
    quantum = money_quantum(currency)
    exact = [contract_total * weight / weight_sum for weight in weights]
    floors = [value.quantize(quantum, rounding=ROUND_FLOOR) for value in exact]
    short = int((_q(contract_total, currency) - sum(floors, DEC_ZERO)) / quantum)
    amounts = list(floors)
    for index in sorted(range(len(exact)), key=lambda i: (-(exact[i] - floors[i]), i))[:short]:
        amounts[index] += quantum
    return amounts


def _held_row(line: CertificateWorkLine, index: int, reason: str) -> WorkLineResult:
    return WorkLineResult(
        line=line,
        index=index,
        status="held",
        reason=reason,
        previous_quantity=line.previous_quantity,
        period_quantity=line.period_quantity,
        cumulative_quantity=None,
        previous_pct=line.previous_pct,
        period_pct=line.period_pct,
        cumulative_pct=None,
        contract_amount=line.contract_amount,
        previous_amount=None,
        period_amount=None,
        cumulative_amount=None,
    )


def _stated_row(line: CertificateWorkLine, index: int, currency: str, flavour: str) -> WorkLineResult | None:
    """The row whose money its source stated, or ``None`` when it stated none.

    One stated amount without the other is not a statement: the row is then
    computed like any other, and held if it cannot be.
    """
    if line.stated_previous_amount is None or line.stated_period_amount is None:
        return None
    previous_amount = _q(line.stated_previous_amount, currency)
    cumulative_amount = _q(line.stated_previous_amount + line.stated_period_amount, currency)
    contract_amount = line.contract_amount
    computed: Decimal | None = None
    cumulative_quantity: Decimal | None = None
    cumulative_pct: Decimal | None = None
    over = False
    over_by: Decimal | None = None
    if flavour == "unit_price":
        if line.previous_quantity is not None and line.period_quantity is not None:
            cumulative_quantity = line.previous_quantity + line.period_quantity
            if line.unit_price is not None:
                computed = _q(cumulative_quantity * line.unit_price, currency)
            if line.contract_quantity is not None and cumulative_quantity > line.contract_quantity:
                over, over_by = True, cumulative_quantity - line.contract_quantity
        if contract_amount is None and line.contract_quantity is not None and line.unit_price is not None:
            contract_amount = line.contract_quantity * line.unit_price
    else:
        if line.previous_pct is not None and line.period_pct is not None:
            cumulative_pct = line.previous_pct + line.period_pct
            if line.contract_amount is not None:
                computed = _share(line.contract_amount, cumulative_pct, currency)
            if cumulative_pct > DEC_HUNDRED:
                over, over_by = True, cumulative_pct - DEC_HUNDRED
    return WorkLineResult(
        line=line,
        index=index,
        status="value",
        reason="",
        previous_quantity=line.previous_quantity if flavour == "unit_price" else None,
        period_quantity=line.period_quantity if flavour == "unit_price" else None,
        cumulative_quantity=cumulative_quantity,
        previous_pct=line.previous_pct if flavour == "lump_sum" else None,
        period_pct=line.period_pct if flavour == "lump_sum" else None,
        cumulative_pct=cumulative_pct,
        contract_amount=_q(contract_amount, currency) if contract_amount is not None else None,
        previous_amount=previous_amount,
        period_amount=cumulative_amount - previous_amount,
        cumulative_amount=cumulative_amount,
        over_measured=over,
        over_by=over_by,
        computed_cumulative_amount=computed,
    )


def _unit_price_row(line: CertificateWorkLine, index: int, currency: str) -> WorkLineResult:
    stated = _stated_row(line, index, currency, "unit_price")
    if stated is not None:
        return stated
    missing = [
        name
        for name, value in (
            ("previous_quantity", line.previous_quantity),
            ("period_quantity", line.period_quantity),
            ("unit_price", line.unit_price),
        )
        if value is None
    ]
    if missing:
        return _held_row(line, index, ", ".join(missing))
    assert line.previous_quantity is not None and line.period_quantity is not None and line.unit_price is not None
    cumulative_quantity = line.previous_quantity + line.period_quantity
    previous_amount = _q(line.previous_quantity * line.unit_price, currency)
    cumulative_amount = _q(cumulative_quantity * line.unit_price, currency)
    contract_amount = line.contract_amount
    if contract_amount is None and line.contract_quantity is not None:
        contract_amount = line.contract_quantity * line.unit_price
    over = line.contract_quantity is not None and cumulative_quantity > line.contract_quantity
    return WorkLineResult(
        line=line,
        index=index,
        status="value",
        reason="",
        previous_quantity=line.previous_quantity,
        period_quantity=line.period_quantity,
        cumulative_quantity=cumulative_quantity,
        previous_pct=None,
        period_pct=None,
        cumulative_pct=None,
        contract_amount=_q(contract_amount, currency) if contract_amount is not None else None,
        previous_amount=previous_amount,
        period_amount=cumulative_amount - previous_amount,
        cumulative_amount=cumulative_amount,
        over_measured=over,
        over_by=cumulative_quantity - line.contract_quantity if over and line.contract_quantity is not None else None,
    )


def _share(contract_amount: Decimal, pct: Decimal, currency: str) -> Decimal:
    """A percent of a row's contract amount; the whole amount at one hundred."""
    if pct == DEC_HUNDRED:
        return _q(contract_amount, currency)
    return _q(contract_amount * pct / DEC_HUNDRED, currency)


def _lump_sum_row(line: CertificateWorkLine, index: int, currency: str) -> WorkLineResult:
    stated = _stated_row(line, index, currency, "lump_sum")
    if stated is not None:
        return stated
    missing = [
        name
        for name, value in (
            ("contract_amount", line.contract_amount),
            ("previous_pct", line.previous_pct),
            ("period_pct", line.period_pct),
        )
        if value is None
    ]
    if missing:
        return _held_row(line, index, ", ".join(missing))
    assert line.contract_amount is not None and line.previous_pct is not None and line.period_pct is not None
    cumulative_pct = line.previous_pct + line.period_pct
    previous_amount = _share(line.contract_amount, line.previous_pct, currency)
    cumulative_amount = _share(line.contract_amount, cumulative_pct, currency)
    over = cumulative_pct > DEC_HUNDRED
    return WorkLineResult(
        line=line,
        index=index,
        status="value",
        reason="",
        previous_quantity=None,
        period_quantity=None,
        cumulative_quantity=None,
        previous_pct=line.previous_pct,
        period_pct=line.period_pct,
        cumulative_pct=cumulative_pct,
        contract_amount=_q(line.contract_amount, currency),
        previous_amount=previous_amount,
        period_amount=cumulative_amount - previous_amount,
        cumulative_amount=cumulative_amount,
        over_measured=over,
        over_by=cumulative_pct - DEC_HUNDRED if over else None,
    )


def _totals(rows: Sequence[WorkLineResult]) -> WorkTotals:
    valued = [row for row in rows if row.status == "value"]
    contract = [row.contract_amount for row in valued]
    return WorkTotals(
        previous_amount=sum((row.previous_amount or DEC_ZERO for row in valued), DEC_ZERO),
        period_amount=sum((row.period_amount or DEC_ZERO for row in valued), DEC_ZERO),
        cumulative_amount=sum((row.cumulative_amount or DEC_ZERO for row in valued), DEC_ZERO),
        contract_amount=(
            sum((amount for amount in contract if amount is not None), DEC_ZERO)
            if contract and all(amount is not None for amount in contract)
            else None
        ),
    )


# ── Summary evaluation ────────────────────────────────────────────────────


def _plain(value: Decimal) -> str:
    """A Decimal as a plain string, never in scientific notation."""
    return format(value, "f")


def _held(defn: SummaryLineDef, reason: str, basis: Mapping[str, str] | None = None, **params: str) -> SummaryLine:
    merged = dict(basis or {})
    merged["reason"] = reason
    for name, value in params.items():
        merged[f"reason.{name}"] = value
    return SummaryLine(defn.key, defn.letter, "held", None, MappingProxyType(merged), defn.section)


def _value(defn: SummaryLineDef, amount: Decimal, basis: Mapping[str, str] | None = None) -> SummaryLine:
    return SummaryLine(defn.key, defn.letter, "value", amount, MappingProxyType(dict(basis or {})), defn.section)


def _not_applicable(defn: SummaryLineDef, basis: Mapping[str, str] | None = None) -> SummaryLine:
    return SummaryLine(defn.key, defn.letter, "not_applicable", None, MappingProxyType(dict(basis or {})), defn.section)


def _base(operands: Sequence[str], done: Mapping[str, SummaryLine]) -> tuple[Decimal | None, list[str]]:
    """The first operand less the others, and which of them are held.

    A line that does not apply contributes nothing. The amount is ``None``
    when any operand is held.
    """
    held = [key for key in operands if done[key].status == "held"]
    if held:
        return None, held
    amount = DEC_ZERO
    for position, key in enumerate(operands):
        value = done[key].amount if done[key].status == "value" else None
        if value is None:
            continue
        amount = amount + value if position == 0 else amount - value
    return amount, []


def _figure_basis(figure: Figure) -> dict[str, str]:
    basis: dict[str, str] = {
        "review_status": figure.review_status,
        "overridden": "true" if figure.overridden else "false",
    }
    if figure.base is not None:
        basis["base"] = _plain(figure.base)
    if figure.rate_pct is not None:
        basis["rate_pct"] = _plain(figure.rate_pct)
    if figure.numerator is not None and figure.denominator is not None:
        basis["numerator"] = str(figure.numerator)
        basis["denominator"] = str(figure.denominator)
    if figure.code:
        basis["code"] = figure.code
    if figure.legal_reference:
        basis["legal_reference"] = figure.legal_reference
    if figure.effective_from is not None:
        basis["effective_from"] = figure.effective_from.isoformat()
    if figure.status != "held" and figure.reason_key:
        # Why a figure does not apply, or a remark on a computed one (a cap
        # applied), with what the sentence needs to be printed.
        basis["remark"] = figure.reason_key
        for name, value in dict(figure.reason_params).items():
            basis[f"remark.{name}"] = str(value)
    return basis


def _tax_line(defn: SummaryLineDef, inp: CertificateInput, done: Mapping[str, SummaryLine]) -> SummaryLine:
    result = inp.taxes_by_line.get(defn.key, inp.taxes)
    if result is None:
        return _held(defn, "module_absent")
    figure = getattr(result, defn.tax_kind, None)
    if not isinstance(figure, Figure):
        return _held(defn, "missing_figure", kind=defn.tax_kind)
    basis = _figure_basis(figure)
    if inp.tax_conditions.get(defn.key):
        basis["conditions"] = inp.tax_conditions[defn.key]
    if figure.status == "not_applicable":
        if figure.reason_key:
            basis["reason"] = figure.reason_key
        return _not_applicable(defn, basis)
    expected: Decimal | None = None
    if defn.operands:
        expected, held = _base(defn.operands, done)
        if expected is None:
            return _held(defn, "base_held", basis, operands=", ".join(held))
        basis["expected_base"] = _plain(expected)
    if figure.status == "held":
        params = {str(name): str(value) for name, value in dict(figure.reason_params).items()}
        return _held(defn, figure.reason_key or "missing_figure", basis, **params)
    if figure.amount is None:
        return _held(defn, "missing_figure", basis, kind=defn.tax_kind)
    # The figure was computed somewhere else. It belongs on this certificate
    # only if it was computed on this certificate's base; a tax worked out on
    # another amount is a number nobody can check against the lines above it.
    if expected is not None and figure.base is not None and _q(figure.base, inp.currency) != expected:
        return _held(defn, "tax_base_mismatch", basis, base=_plain(figure.base), expected=_plain(expected))
    return _value(defn, figure.amount, basis)


def _percent_of_base(
    defn: SummaryLineDef,
    pct: Decimal,
    inp: CertificateInput,
    done: Mapping[str, SummaryLine],
    basis: dict[str, str],
) -> SummaryLine:
    if not defn.operands:
        return _held(defn, "base_held", basis, operands="")
    base, held = _base(defn.operands, done)
    if base is None:
        return _held(defn, "base_held", basis, operands=", ".join(held))
    basis["base"] = _plain(base)
    basis["rate_pct"] = _plain(pct)
    return _value(defn, _q(base * pct / DEC_HUNDRED, inp.currency), basis)


def _manual_line(defn: SummaryLineDef, inp: CertificateInput, done: Mapping[str, SummaryLine]) -> SummaryLine:
    entry = inp.manual_lines.get(defn.key)
    if entry is None:
        return _held(defn, "not_entered")
    basis: dict[str, str] = {"note": entry.note} if entry.note else {}
    if entry.status == "not_applicable":
        return _not_applicable(defn, basis)
    if entry.status == "held":
        return _held(defn, "manual_held", basis)
    if entry.amount is not None:
        return _value(defn, _q(entry.amount, inp.currency), basis)
    if entry.pct is not None:
        return _percent_of_base(defn, entry.pct, inp, done, basis)
    return _held(defn, "not_entered", basis)


def _evaluate(
    defn: SummaryLineDef,
    inp: CertificateInput,
    rows: Sequence[WorkLineResult],
    done: Mapping[str, SummaryLine],
) -> SummaryLine:
    if defn.op == "input":
        source = defn.operands[0]
        if source == "work_cumulative":
            held_rows = [row for row in rows if row.status == "held"]
            if held_rows:
                codes = ", ".join(row.code or str(row.index) for row in held_rows)
                return _held(defn, "work_line_incomplete", {"source": source}, lines=codes)
            return _value(defn, _totals(rows).cumulative_amount, {"source": source, "lines": str(len(rows))})
        if inp.previous_certified_total is None:
            why = {str(name): str(value) for name, value in dict(inp.previous_held_params).items()}
            return _held(defn, inp.previous_held_reason or "previous_unknown", {"source": source}, **why)
        return _value(defn, _q(inp.previous_certified_total, inp.currency), {"source": source})
    if defn.op == "tax":
        return _tax_line(defn, inp, done)
    if defn.op == "manual":
        return _manual_line(defn, inp, done)
    if defn.op == "retention":
        if inp.retention_pct is None:
            return _held(defn, "retention_unknown")
        return _percent_of_base(defn, inp.retention_pct, inp, done, {})
    # sum and difference
    held = [key for key in defn.operands if done[key].status == "held"]
    if held:
        return _held(defn, "operand_held", {"held_operands": ", ".join(held)}, operands=", ".join(held))
    amount = DEC_ZERO
    for position, key in enumerate(defn.operands):
        value = done[key].amount if done[key].status == "value" else None
        if value is None:
            continue
        amount = amount - value if defn.op == "difference" and position > 0 else amount + value
    return _value(defn, amount, {"operands": ", ".join(defn.operands)})


def compute_certificate(inp: CertificateInput) -> Certificate:
    """Compute one certificate: every work row and every summary line.

    The layout is evaluated in dependency order and returned in printed order.
    See the module docstring for the rounding rule and for what ``held`` means.

    Raises:
        ValueError: The layout cannot be evaluated (see
            :func:`app.modules.contracts.hakedis_layout.validate_layout`), or
            the flavour is unknown.
    """
    if inp.flavour not in ("unit_price", "lump_sum"):
        raise ValueError(f"unknown hakedis flavour {inp.flavour!r}")
    layout = tuple(inp.layout)
    validate_layout(layout)
    row_for = _unit_price_row if inp.flavour == "unit_price" else _lump_sum_row
    rows = tuple(row_for(line, index, inp.currency) for index, line in enumerate(inp.lines, start=1))

    by_key = {defn.key: defn for defn in layout}
    done: dict[str, SummaryLine] = {}
    for key in evaluation_order(layout):
        done[key] = _evaluate(by_key[key], inp, rows, done)
    summary = tuple(done[defn.key] for defn in layout)
    return Certificate(inp=inp, work_lines=rows, summary=summary, payable=done["payable"])


def expected_tax_bases(inp: CertificateInput) -> dict[str, Decimal | None]:
    """The base each tax line of the layout expects, keyed by the figure it prints.

    For whoever computes the taxes: line E for VAT and the income withholding,
    line E less the advance recovered for the stamp duty, the VAT for its
    withholding. ``None`` where the base is held or the line declares none.
    The taxes already on ``inp`` are ignored, since the bases come before them.
    """
    cert = compute_certificate(replace(inp, taxes=None, taxes_by_line={}))
    done = {line.key: line for line in cert.summary}
    bases: dict[str, Decimal | None] = {}
    for defn in inp.layout:
        if defn.op != "tax":
            continue
        # A tax line is held without its module, so a base built on one (the
        # VAT under its withholding) is not known yet either.
        bases[defn.tax_kind] = _base(defn.operands, done)[0] if defn.operands else None
    return bases


def manual_lines_for(settings: HakedisSettings, entered: Mapping[str, ManualLine]) -> dict[str, ManualLine]:
    """What was entered for a certificate, over what the contract already settles.

    A manual line the contract rules out is not applicable without anyone
    typing it each month, and an advance recovered at a contract percent is
    that percent of its base. An entry made on the certificate itself always
    wins over both.
    """
    lines: dict[str, ManualLine] = {
        key: ManualLine(key, "not_applicable", None, reason) for key, reason in settings.not_applicable.items()
    }
    if settings.advance_recovery_pct is not None:
        lines["advance_recovery"] = ManualLine("advance_recovery", "value", None, pct=settings.advance_recovery_pct)
    lines.update(entered)
    return lines


# ── Why a document is a draft ─────────────────────────────────────────────

#: Reasons that only pass on another line's hold and so get no note of their own.
_DERIVED_REASONS: frozenset[str] = frozenset({"operand_held", "base_held"})


def document_notes(cert: Certificate) -> tuple[DocumentNote, ...]:
    """Every reason this certificate is not final, numbered in printed order.

    A held line gets a note with its own reason; a total that is held only
    because an operand is gets none, since the operand's note already says
    why. A computed tax whose rate is unconfirmed, or whose amount a person
    replaced, gets a note too: the figure is there, but it is not yet settled.
    """
    notes: list[DocumentNote] = []
    tax_keys = {defn.key for defn in cert.inp.layout if defn.op == "tax"}
    signed = cert.inp.tax_status == "confirmed"
    unsigned_noted = False

    def add(line: SummaryLine, reason: str, params: Mapping[str, str]) -> None:
        notes.append(DocumentNote(len(notes) + 1, line.key, line.letter, reason, MappingProxyType(dict(params))))

    for line in cert.summary:
        basis = line.basis
        if line.key in tax_keys and line.status != "held" and cert.inp.tax_status == "draft" and not unsigned_noted:
            # Said once, on the first tax line it applies to: the figures are
            # there, and nobody has put a name under them yet.
            add(line, "taxes_not_confirmed", {})
            unsigned_noted = True
        if line.status == "held":
            reason = basis.get("reason", "")
            if reason in _DERIVED_REASONS:
                continue
            prefix = "reason."
            add(line, reason, {name[len(prefix) :]: value for name, value in basis.items() if name.startswith(prefix)})
            continue
        if line.status == "value" and not (signed and line.key in tax_keys):
            if basis.get("review_status") == "unconfirmed":
                add(line, "unconfirmed_rate", {})
            if basis.get("overridden") == "true":
                add(line, "overridden", {})
    return tuple(notes)


# ── Print model ───────────────────────────────────────────────────────────


def _style(inp: CertificateInput) -> NumberStyle:
    return number_style(inp.country_code, inp.currency)


def _decimals(value: Decimal, least: int, most: int) -> int:
    exponent = value.normalize().as_tuple().exponent
    places = -exponent if isinstance(exponent, int) and exponent < 0 else 0
    return min(max(places, least), most)


def format_money(amount: Decimal, inp: CertificateInput) -> str:
    """An amount in the currency's own decimals and the country's separators."""
    return format_number(amount, minor_units(inp.currency), _style(inp))


def format_quantity(quantity: Decimal, inp: CertificateInput) -> str:
    """A quantity with two to four decimals, as many as it carries."""
    return format_number(quantity, _decimals(quantity, 2, 4), _style(inp))


def format_percent(pct: Decimal, inp: CertificateInput) -> str:
    """A percent with two to six decimals, as many as it carries."""
    return format_number(pct, _decimals(pct, 2, 6), _style(inp))


def _format_unit_price(price: Decimal, inp: CertificateInput) -> str:
    return format_number(price, _decimals(price, minor_units(inp.currency), 4), _style(inp))


def _format_rate(inp: CertificateInput) -> Any:
    def render(raw: str) -> str:
        value = Decimal(raw)
        return format_number(value, _decimals(value, 0, 4), _style(inp))

    return render


@dataclass(frozen=True)
class PrintedSummaryLine:
    """One summary line as both documents print it.

    ``labels``, ``formulas``, ``details`` and ``held_words`` hold one entry
    per language of the locale, Turkish first on a bilingual document.
    """

    key: str
    letter: str
    section: str
    status: Status
    amount: Decimal | None
    labels: tuple[str, ...]
    formulas: tuple[str, ...]
    details: tuple[str, ...]
    text: str
    notes: tuple[int, ...]
    emphasis: bool


def note_text(note: DocumentNote, cert: Certificate, language: str, settings: HakedisSettings | None = None) -> str:
    """One footnote in one language, with its amounts in the document's format."""
    return reason_text(note.reason_key, note.params, cert, language, settings)


#: Reason parameters that are amounts, printed in the document's number format.
_MONEY_PARAMS = ("base", "expected", "work_value", "threshold", "measured", "cap", "computed", "stored", "stated")


def reason_text(
    reason_key: str,
    params: Mapping[str, str],
    cert: Certificate,
    language: str,
    settings: HakedisSettings | None = None,
) -> str:
    """The sentence for one reason key in one language, amounts in the document's format."""
    overrides = settings.labels if settings is not None else None
    shown = dict(params)
    for name in _MONEY_PARAMS:
        if name in shown:
            try:
                shown[name] = format_money(Decimal(shown[name]), cert.inp)
            except ArithmeticError:
                pass
    if "on" in shown:
        try:
            shown["on"] = format_date(date.fromisoformat(shown["on"]), cert.inp.country_code)
        except ValueError:
            pass
    key = f"reason.{reason_key}"
    if key not in HAKEDIS_LABELS[language] and key not in ((overrides or {}).get(language) or {}):
        return label("reason.other", language, overrides, reason=reason_key)
    return label_filled(key, language, overrides, shown)


def printed_summary(
    cert: Certificate, locale: str, settings: HakedisSettings | None = None
) -> tuple[PrintedSummaryLine, ...]:
    """The summary lines with their labels, formulas and amount text."""
    languages = locale_languages(locale)
    overrides = settings.labels if settings is not None else None
    layout = tuple(cert.inp.layout)
    by_key = {defn.key: defn for defn in layout}
    notes_by_line: dict[str, list[int]] = {}
    for note in cert.notes:
        notes_by_line.setdefault(note.line_key, []).append(note.number)
    rate = _format_rate(cert.inp)
    printed: list[PrintedSummaryLine] = []
    for line in cert.summary:
        defn = by_key[line.key]
        refs = tuple(notes_by_line.get(line.key, ()))
        if line.status == "value" and line.amount is not None:
            text = format_money(line.amount, cert.inp)
        elif line.status == "not_applicable":
            text = DASH
        else:
            text = " / ".join(label("status.held", language, overrides) for language in languages)
        details: list[str] = []
        for language in languages:
            parts: list[str] = []
            if line.basis.get("code"):
                parts.append(f"{label('basis.code', language, overrides)}: {line.basis['code']}")
            if line.basis.get("legal_reference"):
                parts.append(f"{label('basis.legal_reference', language, overrides)}: {line.basis['legal_reference']}")
            if line.basis.get("note") and language == languages[0]:
                # A person's own note is in one language; it is printed once.
                parts.append(f"{label('basis.note', language, overrides)}: {line.basis['note']}")
            if line.basis.get("conditions") and language == languages[0]:
                parts.append(f"{label('basis.conditions', language, overrides)}: {line.basis['conditions']}")
            if line.basis.get("remark"):
                prefix = "remark."
                remark = {name[len(prefix) :]: value for name, value in line.basis.items() if name.startswith(prefix)}
                parts.append(reason_text(line.basis["remark"], remark, cert, language, settings))
            details.append(", ".join(parts))
        printed.append(
            PrintedSummaryLine(
                key=line.key,
                letter=line.letter,
                section=line.section,
                status=line.status,
                amount=line.amount if line.status == "value" else None,
                labels=tuple(label(f"line.{line.key}", language, overrides) for language in languages),
                formulas=tuple(line_formula(defn, layout, line.basis, language, rate) for language in languages),
                details=tuple(details),
                text=text,
                notes=refs,
                emphasis=defn.section == "result" or (defn.op == "sum" and defn.section != "deductions"),
            )
        )
    return tuple(printed)


def header_rows(
    cert: Certificate,
    locale: str,
    settings: HakedisSettings | None = None,
    issue_date: date | None = None,
) -> list[tuple[tuple[str, ...], str]]:
    """The header block as ``(label per language, value)`` rows; empty values are left out."""
    general, parties = header_columns(cert, locale, settings, issue_date)
    return [*general, *parties]


def header_columns(
    cert: Certificate,
    locale: str,
    settings: HakedisSettings | None = None,
    issue_date: date | None = None,
) -> tuple[list[tuple[tuple[str, ...], str]], list[tuple[tuple[str, ...], str]]]:
    """The header block in its two halves: the job and the certificate, then the two parties."""
    inp = cert.inp
    languages = locale_languages(locale)
    overrides = settings.labels if settings is not None else None

    def parts(key: str) -> tuple[str, ...]:
        return tuple(label(key, language, overrides) for language in languages)

    def day(value: date) -> str:
        return format_date(value, inp.country_code)

    kind = "title.final" if inp.is_final else "title.interim"
    number = f"{inp.certificate_number} ({' / '.join(parts(kind))})"
    rows: list[tuple[tuple[str, ...], str]] = [
        (parts("header.project"), inp.project_name),
        (parts("header.contract"), inp.contract_title),
        (parts("header.contract_number"), inp.contract_number),
        (parts("header.certificate_number"), number),
        (parts("header.period"), f"{day(inp.period_start)} - {day(inp.period_end)}"),
        (parts("header.issue_date"), day(issue_date) if issue_date is not None else ""),
        (parts("header.currency"), inp.currency),
    ]
    parties: list[tuple[tuple[str, ...], str]] = []
    for role, party in (("header.employer", inp.employer), ("header.contractor", inp.contractor)):
        parties.append((parts(role), party.name))
        parties.append((_joined(parts(role), parts("header.tax_number")), party.tax_number))
        parties.append((_joined(parts(role), parts("header.tax_office")), party.tax_office))
        parties.append((_joined(parts(role), parts("header.address")), party.address))
    return (
        [(names, value) for names, value in rows if value],
        [(names, value) for names, value in parties if value],
    )


def _joined(first: tuple[str, ...], second: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(f"{a} - {b}" for a, b in zip(first, second, strict=True))


def works_columns(cert: Certificate, settings: HakedisSettings | None = None) -> tuple[ColumnDef, ...]:
    """The works list columns for this certificate's flavour, in printed order."""
    flavour = cert.inp.flavour
    chosen = (settings.columns if settings is not None else {}).get(flavour) or WORKS_DEFAULT_COLUMNS[flavour]
    known = {column.key: column for column in WORKS_COLUMNS[flavour]}
    return tuple(known[key] for key in chosen)


@dataclass(frozen=True)
class PrintedWorkRow:
    """One row of the works list as both documents print it.

    ``kind`` is ``section`` (a group title), ``line``, ``subtotal`` or
    ``total``. ``cells`` and ``values`` are aligned with the columns: the text
    as printed, and the number behind it where the cell is numeric.
    """

    kind: Literal["section", "line", "subtotal", "total"]
    cells: tuple[str, ...]
    values: tuple[Decimal | int | None, ...]
    title: str = ""
    flagged: bool = False
    held: bool = False


def _work_cell(row: WorkLineResult, column: ColumnDef, inp: CertificateInput) -> tuple[str, Decimal | int | None]:
    value = getattr(row, column.key)
    if column.kind == "seq":
        return str(value), int(value)
    if column.kind in ("text", "unit"):
        return str(value or ""), None
    if value is None:
        return "", None
    if column.kind == "money":
        return format_money(value, inp), value
    if column.kind == "percent":
        return format_percent(value, inp), value
    if column.kind == "unit_price":
        return _format_unit_price(value, inp), value
    return format_quantity(value, inp), value


def _total_row(
    kind: Literal["subtotal", "total"],
    title: str,
    rows: Sequence[WorkLineResult],
    columns: Sequence[ColumnDef],
    inp: CertificateInput,
) -> PrintedWorkRow:
    totals = _totals(rows)
    cells: list[str] = []
    values: list[Decimal | int | None] = []
    for column in columns:
        amount: Decimal | None = None
        if column.kind == "money":
            amount = getattr(totals, column.key, None)
        if amount is None:
            cells.append("")
            values.append(None)
        else:
            cells.append(format_money(amount, inp))
            values.append(amount)
    return PrintedWorkRow(kind, tuple(cells), tuple(values), title=title)


def printed_works(
    cert: Certificate, locale: str, settings: HakedisSettings | None = None
) -> tuple[tuple[ColumnDef, ...], tuple[PrintedWorkRow, ...]]:
    """The works list: its columns and its rows, with section subtotals and the total.

    Rows are grouped by section in order of first appearance. A list with no
    sections prints no group titles and no subtotals, only the total.
    """
    inp = cert.inp
    languages = locale_languages(locale)
    overrides = settings.labels if settings is not None else None
    columns = works_columns(cert, settings)
    sections: dict[str, list[WorkLineResult]] = {}
    for row in cert.work_lines:
        sections.setdefault(row.section, []).append(row)
    grouped = len(sections) > 1 or any(sections)
    printed: list[PrintedWorkRow] = []
    blank: tuple[str, ...] = tuple("" for _ in columns)
    nothing: tuple[Decimal | int | None, ...] = tuple(None for _ in columns)
    for section, rows in sections.items():
        if grouped:
            printed.append(PrintedWorkRow("section", blank, nothing, title=section))
        for row in rows:
            pairs = [_work_cell(row, column, inp) for column in columns]
            printed.append(
                PrintedWorkRow(
                    "line",
                    tuple(text for text, _ in pairs),
                    tuple(value for _, value in pairs),
                    flagged=row.over_measured,
                    held=row.status == "held",
                )
            )
        if grouped:
            subtotal = " / ".join(label("works.subtotal", language, overrides) for language in languages)
            title = f"{section} - {subtotal}" if section else subtotal
            printed.append(_total_row("subtotal", title, rows, columns, inp))
    total = " / ".join(label("works.total", language, overrides) for language in languages)
    printed.append(_total_row("total", total, cert.work_lines, columns, inp))
    return columns, tuple(printed)
