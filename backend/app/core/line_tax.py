# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Per-line tax arithmetic that holds in every market.

Five questions a single bill-wide VAT rate cannot answer, each a pure function
over plain values so a country pack composes them and a test can pin them to a
worked example:

* ``category_rate``: which rate a tax category (goods, works, services,
  simplified, exempt) carries on a date. A category is effective-dated, so a
  rate that ends on a known day (a temporary reduction, a sunset of an
  election) is data with an ``effective_to`` and not a code change.
* ``compute_tax_base``: the tax base and tax of a set of lines at their own
  rates. A line entered gross of tax (a prime-cost sum priced VAT-inclusive)
  is never taxed again: it is added to the total beside the tax, not under it.
* ``method_change_locked``: whether a project may leave its tax method yet,
  given the election date and a lock period in months.
* ``check_item_codes``: item codes against a pack-supplied pattern list, and
  duplicates inside a uniqueness scope (bill, section or sub-project).
* ``default_edition``: which edition of a standard a project takes when it
  states none, decided by the day the project was created and never by today.

No rate, pattern or date lives here. Every one of them is an argument, and the
country values sit in the pack that passes them. Standard library only.
"""

from __future__ import annotations

import calendar
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

__all__ = [
    "TAX_CATEGORY_KINDS",
    "TAX_METHODS",
    "CodeFinding",
    "TaxBase",
    "TaxCategory",
    "TaxLine",
    "add_months",
    "category_rate",
    "check_item_codes",
    "compute_tax_base",
    "default_edition",
    "lock_ends_on",
    "method_change_locked",
    "parse_date",
    "to_decimal",
]

#: The kinds a tax category can be. A pack names its own codes; the kind is
#: what lets a rule written once ask "is this a goods line" in any market.
TAX_CATEGORY_KINDS: tuple[str, ...] = ("goods", "works", "services", "simplified", "exempt")

#: How a project accounts for output tax. ``simplified`` is a flat collection
#: rate on gross receipts without input credit; ``exempt`` charges nothing.
TAX_METHODS: tuple[str, ...] = ("general", "simplified", "exempt")

_CENT = Decimal("0.01")
_HUNDRED = Decimal(100)
_ZERO = Decimal(0)


def to_decimal(value: Any) -> Decimal:
    """Read a money or percentage value; blanks and garbage read as zero."""
    if isinstance(value, Decimal):
        return value
    if value is None or value == "":
        return _ZERO
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return _ZERO


def parse_date(value: Any) -> date | None:
    """Read a ``date`` or an ISO ``YYYY-MM-DD`` string, else ``None``."""
    if isinstance(value, date):
        return value
    text = str(value or "").strip()[:10]
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


@dataclass(frozen=True)
class TaxCategory:
    """One effective-dated tax category of a market.

    ``effective_to`` is inclusive: the last day the rate applies. ``None`` on
    either end means open.
    """

    code: str
    kind: str
    rate_pct: Decimal
    effective_from: date | None = None
    effective_to: date | None = None

    def in_force(self, on: date) -> bool:
        """Whether this category applies on ``on``."""
        if self.effective_from is not None and on < self.effective_from:
            return False
        return not (self.effective_to is not None and on > self.effective_to)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> TaxCategory:
        """Build from a pack row (``rate_pct`` as a string, dates as ISO)."""
        return cls(
            code=str(raw.get("code") or ""),
            kind=str(raw.get("kind") or ""),
            rate_pct=to_decimal(raw.get("rate_pct")),
            effective_from=parse_date(raw.get("effective_from")),
            effective_to=parse_date(raw.get("effective_to")),
        )


def category_rate(categories: Iterable[TaxCategory], code: str, on: date) -> Decimal | None:
    """The rate of category ``code`` on ``on``, or ``None`` when none is in force.

    Several rows may share a code with disjoint windows; the one whose window
    holds ``on`` answers. ``None`` is the honest answer for a day the data does
    not reach, never a fallback rate.
    """
    for category in categories:
        if category.code == code and category.in_force(on):
            return category.rate_pct
    return None


@dataclass(frozen=True)
class TaxLine:
    """One priced line for the tax base.

    ``amount`` is net of tax unless ``tax_inclusive`` is set, in which case it
    already carries its tax and is kept out of the base.
    """

    ref: str
    amount: Decimal
    rate_pct: Decimal | None = None
    tax_inclusive: bool = False


@dataclass
class TaxBase:
    """The result of :func:`compute_tax_base`."""

    taxable_base: Decimal = _ZERO
    tax: Decimal = _ZERO
    tax_inclusive_total: Decimal = _ZERO
    #: ``{rate_pct as str: {"base": Decimal, "tax": Decimal}}``.
    by_rate: dict[str, dict[str, Decimal]] = field(default_factory=dict)

    @property
    def total(self) -> Decimal:
        """Base plus tax plus the sums that already carry their tax."""
        return self.taxable_base + self.tax + self.tax_inclusive_total


def compute_tax_base(lines: Iterable[TaxLine], default_rate_pct: Decimal | None = None) -> TaxBase:
    """Sum the tax base and the tax of ``lines``, each at its own rate.

    A line with no rate takes ``default_rate_pct``; with neither it is taxed at
    zero and still counted in the base. Tax is rounded per rate group to the
    cent, half up, which is how an invoice states it.
    """
    result = TaxBase()
    raw_tax: dict[str, Decimal] = {}
    for line in lines:
        if line.tax_inclusive:
            result.tax_inclusive_total += line.amount
            continue
        rate = line.rate_pct if line.rate_pct is not None else (default_rate_pct or _ZERO)
        key = str(rate.normalize()) if rate else "0"
        group = result.by_rate.setdefault(key, {"base": _ZERO, "tax": _ZERO})
        group["base"] += line.amount
        raw_tax[key] = raw_tax.get(key, _ZERO) + line.amount * rate / _HUNDRED
        result.taxable_base += line.amount
    for key, amount in raw_tax.items():
        rounded = amount.quantize(_CENT, rounding=ROUND_HALF_UP)
        result.by_rate[key]["tax"] = rounded
        result.tax += rounded
    return result


def add_months(start: date, months: int) -> date:
    """``start`` moved by whole months, clamped to the last day of the month."""
    month_index = start.month - 1 + months
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def lock_ends_on(election: date | None, lock_months: int | None) -> date | None:
    """The first day a method elected on ``election`` may be changed."""
    if election is None or not lock_months:
        return None
    return add_months(election, int(lock_months))


def method_change_locked(election: date | None, lock_months: int | None, change_on: date) -> bool:
    """Whether a change of tax method on ``change_on`` falls inside the lock."""
    ends = lock_ends_on(election, lock_months)
    return ends is not None and change_on < ends


@dataclass(frozen=True)
class CodeFinding:
    """One item-code problem: ``kind`` is ``format`` or ``duplicate``."""

    kind: str
    ref: str
    code: str
    scope: str = ""
    other_refs: tuple[str, ...] = ()


def check_item_codes(
    entries: Sequence[tuple[str, str, str]],
    patterns: Sequence[str],
    shared: Sequence[str] = (),
) -> list[CodeFinding]:
    """Check ``(ref, code, scope)`` entries against patterns and for duplicates.

    A code passes the format check when any pattern matches it in full. Blank
    codes are skipped: whether a code is required is a different rule. A code
    used twice inside one ``scope`` yields one ``duplicate`` finding per extra
    occurrence, naming the first occurrence. Codes matching a ``shared``
    pattern name an item rather than a line and are never duplicates.
    """
    compiled = [re.compile(p) for p in patterns]
    repeatable = [re.compile(p) for p in shared]
    findings: list[CodeFinding] = []
    seen: dict[tuple[str, str], str] = {}
    for ref, code, scope in entries:
        text = (code or "").strip()
        if not text:
            continue
        if compiled and not any(p.fullmatch(text) for p in compiled):
            findings.append(CodeFinding("format", ref, text, scope))
        key = (scope, text)
        if any(p.fullmatch(text) for p in repeatable):
            continue
        if key in seen:
            findings.append(CodeFinding("duplicate", ref, text, scope, (seen[key],)))
        else:
            seen[key] = ref
    return findings


def default_edition(editions: Sequence[dict[str, Any]], created_on: date | None) -> str | None:
    """The edition a project created on ``created_on`` takes when it states none.

    ``editions`` are pack rows ``{"key", "in_force_from"}``. The newest edition
    already in force on the creation day wins. A project with no creation day
    gets the oldest edition, because a record that cannot say when it began is
    an old record.
    """
    dated = sorted(
        ((parse_date(row.get("in_force_from")) or date.min, str(row.get("key") or "")) for row in editions),
        key=lambda pair: pair[0],
    )
    if not dated:
        return None
    if created_on is None:
        return dated[0][1]
    chosen = None
    for start, key in dated:
        if start <= created_on:
            chosen = key
    return chosen or dated[0][1]
