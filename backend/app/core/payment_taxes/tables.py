# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The shape of one statutory rate row and how a row is found for a date.

A payment tax is never a literal in arithmetic. It is a row: what is taxed, on
which base, at which rate or fraction, from which date, under which article,
read where and when, and whether a person has confirmed it against the primary
source. :mod:`app.core.payment_taxes.calc` computes only from rows it is handed,
so a figure on a certificate can always be traced back to the row behind it.

**A date either has a row or it does not.** :func:`lookup` never reaches for
the nearest row when the date falls in a gap, and never picks one of two rows
that both claim the date. The first would apply last year's fraction to this
year's invoice without anyone deciding to; the second would make the answer
depend on the order the table happens to be written in. A gap answers ``None``
and an overlap raises, and both reach the screen as a figure that is held.

Standard library only. Nothing here may import from ``app.modules``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal

__all__ = [
    "BASES",
    "BUYER_SCOPES",
    "KINDS",
    "OverlappingRowsError",
    "RateRow",
    "categories",
    "find_overlaps",
    "lookup",
    "rows_for",
    "validate_rows",
]

#: The taxes this package computes. Value added tax itself is deliberately not
#: one of them: its rate has a single source elsewhere in the platform, and a
#: second table of VAT rates is how two documents come to disagree.
KINDS: tuple[str, ...] = ("vat_withholding", "income_withholding", "stamp_duty")
BASES: tuple[str, ...] = ("vat", "net", "net_plus_vat")
BUYER_SCOPES: tuple[str, ...] = ("", "any", "designated_only", "designated_or_work_value")
_THRESHOLD_SCOPES: tuple[str, ...] = ("per_document", "per_payee_year")
_THRESHOLD_MEASURES: tuple[str, ...] = ("net", "net_plus_vat")
_REVIEW_STATUSES: tuple[str, ...] = ("confirmed", "unconfirmed")
_HUNDRED = Decimal("100")


@dataclass(frozen=True)
class RateRow:
    """One statutory rate, fraction or duty, valid for a range of dates.

    Attributes:
        country_code: ISO 3166-1 alpha-2 code of the jurisdiction.
        kind: Which tax the row belongs to.
        code: The official code where the authority publishes one, otherwise a
            house key. One row per ``(country_code, kind, code)`` on any date.
        labels: Printed label per locale, for example ``{"tr": ..., "en": ...}``.
        base: What the rate applies to: the VAT amount, the net amount, or the
            net amount plus VAT.
        rate_pct: The rate as a percent. A per-mille rate is written as a
            percent, so 9.48 per mille is ``Decimal("0.948")``. ``None`` for a
            row that carries a fraction instead.
        numerator: Fraction numerator, for ``kind == "vat_withholding"``.
        denominator: Fraction denominator, for ``kind == "vat_withholding"``.
        threshold_amount: Amount below which the tax does not apply, or ``None``.
        threshold_currency: Currency every amount on this row is stated in: the
            threshold, the cap and the work value threshold. Empty when the row
            states no amount.
        threshold_scope: Whether the threshold is tested on one document or on
            a payee's whole year.
        threshold_measure: Which amount of the document is compared against the
            threshold.
        cap_amount: Upper limit of the tax amount, or ``None``.
        effective_from: First day the row applies (inclusive). Where the source
            does not state a start, the earliest date the source evidences.
        effective_to: Last day the row applies (inclusive), ``None`` for open.
        legal_reference: Law, article and paragraph the value comes from.
        source_url: Where the value was read.
        read_date: ISO date the source was read.
        review_status: ``confirmed`` once read on the primary source, otherwise
            ``unconfirmed``. An unconfirmed row still computes; the status
            travels with the figure to the screen.
        buyer_scope: Who has to be the buyer for the tax to apply. ``any`` and
            the empty string place no condition. ``designated_only`` applies
            only to the buyers the law designates. ``designated_or_work_value``
            applies to designated buyers always and to everyone else only when
            the value of the whole work reaches ``work_value_threshold``.
        work_value_threshold: The value of the work, VAT included, from which
            an ordinary buyer falls under the tax. Compared against the
            contract, never against one document.
        conditions: A short statement of the condition per locale, shown beside
            the figure so the person confirming it sees what was assumed.
    """

    country_code: str
    kind: Literal["vat_withholding", "income_withholding", "stamp_duty"]
    code: str
    labels: Mapping[str, str]
    base: Literal["vat", "net", "net_plus_vat"]
    rate_pct: Decimal | None
    numerator: int | None
    denominator: int | None
    threshold_amount: Decimal | None
    threshold_currency: str
    threshold_scope: Literal["per_document", "per_payee_year", ""]
    threshold_measure: Literal["net", "net_plus_vat", ""]
    cap_amount: Decimal | None
    effective_from: date
    effective_to: date | None
    legal_reference: str
    source_url: str
    read_date: str
    review_status: Literal["confirmed", "unconfirmed"]
    buyer_scope: Literal["any", "designated_only", "designated_or_work_value", ""] = ""
    work_value_threshold: Decimal | None = None
    conditions: Mapping[str, str] = field(default_factory=dict)


class OverlappingRowsError(ValueError):
    """Two rows for one code are both in force on the same date.

    That is an error in the table, not something to resolve at lookup time:
    whichever row was returned, nobody would have chosen it.
    """


def _country(value: str) -> str:
    return (value or "").strip().upper()


def _in_force(row: RateRow, on: date) -> bool:
    """Whether ``on`` falls inside the row's range, both ends included."""
    if on < row.effective_from:
        return False
    return row.effective_to is None or on <= row.effective_to


def _identity(row: RateRow) -> str:
    return f"{_country(row.country_code)}/{row.kind}/{row.code}"


def lookup(rows: Sequence[RateRow], *, country: str, kind: str, code: str, on: date) -> RateRow | None:
    """Find the row for one code that is in force on a date.

    Args:
        rows: The table to search.
        country: Country code; case and surrounding space are ignored.
        kind: Row kind, matched exactly.
        code: Row code, matched exactly. A code is an identifier an authority
            published, so ``"Ab1"`` and ``"AB1"`` are different codes.
        on: The date the document is taxed on.

    Returns:
        The single row in force, or ``None`` when no row covers the date. A
        date in a gap between two rows is ``None``; the nearest row is never
        substituted.

    Raises:
        OverlappingRowsError: More than one row is in force on the date.
    """
    wanted = _country(country)
    found = [
        row
        for row in rows
        if row.kind == kind and row.code == code and _country(row.country_code) == wanted and _in_force(row, on)
    ]
    if not found:
        return None
    if len(found) > 1:
        raise OverlappingRowsError(f"{len(found)} rows for {wanted}/{kind}/{code} are in force on {on.isoformat()}")
    return found[0]


def rows_for(country: str) -> tuple[RateRow, ...]:
    """Return the shipped data set of one country.

    Args:
        country: Country code; case and surrounding space are ignored.

    Returns:
        The rows that ship for the country, empty when none do. An empty
        result means every selected tax will be held, which is the intended
        outcome for a country nobody has researched.
    """
    wanted = _country(country)
    if wanted == "TR":
        # Imported here because the data module imports the row shape from
        # this one.
        from app.core.payment_taxes.data_tr import ROWS

        return ROWS
    return ()


def categories(rows: Sequence[RateRow], *, country: str, kind: str, on: date) -> list[RateRow]:
    """List the rows of one kind in force on a date, for populating a picker.

    Args:
        rows: The table to search.
        country: Country code; case and surrounding space are ignored.
        kind: Row kind, matched exactly.
        on: The date the document is taxed on.

    Returns:
        One row per code, ordered by code.

    Raises:
        OverlappingRowsError: Two rows for one code are in force on the date.
            A picker offering both would let the choice decide the rate.
    """
    wanted = _country(country)
    found = sorted(
        (row for row in rows if row.kind == kind and _country(row.country_code) == wanted and _in_force(row, on)),
        key=lambda row: row.code,
    )
    for earlier, later in zip(found, found[1:], strict=False):
        if earlier.code == later.code:
            raise OverlappingRowsError(f"2 rows for {wanted}/{kind}/{later.code} are in force on {on.isoformat()}")
    return found


def find_overlaps(rows: Sequence[RateRow]) -> list[tuple[RateRow, RateRow]]:
    """Pairs of rows for the same code whose date ranges share at least one day.

    Args:
        rows: The table to check.

    Returns:
        Each overlapping pair once, in table order. Empty for a sound table.
        Ranges are inclusive, so a row ending on the day the next one starts
        overlaps it by that day.
    """
    pairs: list[tuple[RateRow, RateRow]] = []
    for index, first in enumerate(rows):
        for second in rows[index + 1 :]:
            if _identity(first) != _identity(second):
                continue
            first_ends_before = first.effective_to is not None and first.effective_to < second.effective_from
            second_ends_before = second.effective_to is not None and second.effective_to < first.effective_from
            if not (first_ends_before or second_ends_before):
                pairs.append((first, second))
    return pairs


def _iso_date(text: str) -> bool:
    try:
        date.fromisoformat(text)
    except (TypeError, ValueError):
        return False
    return len(text) == 10


def _row_problems(row: RateRow) -> list[str]:
    """Everything wrong with one row taken on its own."""
    problems: list[str] = []
    if not _country(row.country_code):
        problems.append("country_code is empty")
    if row.kind not in KINDS:
        problems.append(f"kind {row.kind!r} is not one of {KINDS}")
    if not (row.code or "").strip():
        problems.append("code is empty")
    if not row.labels or any(not (text or "").strip() for text in row.labels.values()):
        problems.append("labels are missing or blank")
    if row.base not in BASES:
        problems.append(f"base {row.base!r} is not one of {BASES}")

    has_fraction = row.numerator is not None or row.denominator is not None
    if row.kind == "vat_withholding":
        # A fraction of the VAT and nothing else: the share that changes hands
        # is defined by law as n/d of the computed VAT.
        if row.numerator is None or row.denominator is None or row.denominator <= 0:
            problems.append("fraction needs a numerator and a positive denominator")
        elif not 0 <= row.numerator <= row.denominator:
            problems.append("fraction numerator must lie between 0 and the denominator")
        if row.rate_pct is not None:
            problems.append("rate_pct must be empty on a fraction row")
        if row.base != "vat":
            problems.append("base of a vat_withholding row must be 'vat'")
    else:
        if has_fraction:
            problems.append("fraction is only meaningful on a vat_withholding row")
        if row.rate_pct is None:
            problems.append("rate_pct is required")
        elif not row.rate_pct.is_finite() or not 0 <= row.rate_pct <= _HUNDRED:
            problems.append("rate_pct must lie between 0 and 100")

    # The threshold is three statements that only mean something together.
    threshold_parts = (row.threshold_amount is not None, bool(row.threshold_scope), bool(row.threshold_measure))
    if any(threshold_parts) and not all(threshold_parts):
        problems.append("threshold amount, scope and measure must be given together or not at all")
    if row.threshold_amount is not None and not (row.threshold_amount.is_finite() and row.threshold_amount >= 0):
        problems.append("threshold amount must be a non-negative number")
    if row.threshold_scope and row.threshold_scope not in _THRESHOLD_SCOPES:
        problems.append(f"threshold scope {row.threshold_scope!r} is not one of {_THRESHOLD_SCOPES}")
    if row.threshold_measure and row.threshold_measure not in _THRESHOLD_MEASURES:
        problems.append(f"threshold measure {row.threshold_measure!r} is not one of {_THRESHOLD_MEASURES}")
    if row.cap_amount is not None and not (row.cap_amount.is_finite() and row.cap_amount >= 0):
        problems.append("cap must be a non-negative number")

    if row.buyer_scope not in BUYER_SCOPES:
        problems.append(f"buyer_scope {row.buyer_scope!r} is not one of {BUYER_SCOPES}")
    if row.buyer_scope == "designated_or_work_value":
        if row.work_value_threshold is None:
            problems.append("work_value_threshold is required by buyer_scope 'designated_or_work_value'")
    elif row.work_value_threshold is not None:
        problems.append("work_value_threshold is only meaningful with buyer_scope 'designated_or_work_value'")
    if row.work_value_threshold is not None and not (
        row.work_value_threshold.is_finite() and row.work_value_threshold > 0
    ):
        problems.append("work_value_threshold must be a positive number")
    if any(not (text or "").strip() for text in row.conditions.values()):
        problems.append("conditions contain a blank text")

    # An amount without a currency cannot be compared with anything, and a
    # currency without an amount is a leftover from an edit.
    has_amount = row.threshold_amount is not None or row.cap_amount is not None or row.work_value_threshold is not None
    has_currency = bool((row.threshold_currency or "").strip())
    if row.threshold_amount is not None and not has_currency:
        problems.append("threshold needs a threshold_currency")
    if row.cap_amount is not None and not has_currency:
        problems.append("cap needs a threshold_currency")
    if row.work_value_threshold is not None and not has_currency:
        problems.append("work_value_threshold needs a threshold_currency")
    if has_currency and not has_amount:
        problems.append("threshold_currency is set but the row states no amount")

    if row.effective_to is not None and row.effective_to < row.effective_from:
        problems.append("effective_to lies before effective_from")
    if not (row.legal_reference or "").strip():
        problems.append("legal_reference is empty")
    if not _iso_date(row.read_date):
        problems.append(f"read_date {row.read_date!r} is not an ISO date")
    if row.review_status not in _REVIEW_STATUSES:
        problems.append(f"review_status {row.review_status!r} is not one of {_REVIEW_STATUSES}")
    return problems


def validate_rows(rows: Sequence[RateRow]) -> list[str]:
    """Describe everything that makes a table unsafe to compute from.

    The calculator holds a figure whose row is malformed, so a bad table never
    produces a wrong amount. This function is how the table is found to be bad
    before a certificate is: the test over each shipped data set calls it.

    Args:
        rows: The table to check.

    Returns:
        One sentence per problem, each starting with ``country/kind/code``.
        Empty for a sound table.
    """
    problems = [f"{_identity(row)}: {problem}" for row in rows for problem in _row_problems(row)]
    for first, second in find_overlaps(rows):
        problems.append(
            f"{_identity(first)}: effective ranges overlap "
            f"({first.effective_from.isoformat()} and {second.effective_from.isoformat()})"
        )
    return problems
