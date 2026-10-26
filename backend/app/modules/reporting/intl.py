# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""International, Decimal-exact reporting math and plain-language explainers.

This module is a small, dependency-free toolkit of PURE
functions that the reporting layer can use to turn line amounts into a
report total, a grouped cost breakdown, and a top-N selection - and to
describe every one of those figures in plain language, localized into every
interface language with an English fallback.

Design goals (why this file exists)
------------------------------------
- **International, not hardcoded.** No currency, unit or locale is baked
  in. The caller passes the ISO 4217 currency code and the locale; money
  reads in exactly one currency and is never blended across codes.
- **Decimal-exact money.** Every amount is parsed to :class:`decimal.Decimal`.
  Money never touches ``float`` here, so no rounding drift and no ``NaN`` /
  ``inf`` can leak into a report total.
- **Percentages are ratios.** A "percent of total" is returned as a ratio
  in the ``0.0 .. 1.0`` range (``Decimal("0.25")`` means 25 percent). The
  caller decides how to render it; :func:`format_ratio_as_percent` is the
  convenience formatter.
- **Edge cases are defined, never a 500.** Zero total is guarded (share is
  ``0``, never a division-by-zero). Empty inputs give a well-defined empty
  result. Invalid values (blended currencies, a negative count, a
  non-finite amount) raise a clean :class:`ValueError`, never a crash.
- **Explainable.** Each figure has a one-line explainer that states how it
  was derived, so a site engineer or estimator understands the number in a
  minute.

Nothing here does I/O, touches the database, reads the clock, or mutates
its inputs. That keeps it trivially testable and safe to call from any
layer (service, router, exporter, renderer).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from app.core.i18n import SUPPORTED_LOCALES as _ALL_LOCALES
from app.core.i18n import t

__all__ = [
    "Breakdown",
    "GroupShare",
    "classification_label",
    "ensure_single_currency",
    "explain_breakdown",
    "explain_percent_of_total",
    "explain_report_total",
    "explain_top_n",
    "format_money",
    "format_ratio_as_percent",
    "group_breakdown",
    "normalize_currency",
    "ratio_of_total",
    "report_total",
    "to_decimal",
    "top_n_by_value",
]

# ── Currency shape guard (soft ISO 4217 check, mirrors schemas.py) ─────────
#
# A soft 3-uppercase-letter check, not a closed enum: the platform is global
# and must accept a valid but obscure code. This mirrors the check the
# reporting schema layer already applies to ``override_currency``.
_CURRENCY_CODE_RE = re.compile(r"^[A-Z]{3}$")

DEFAULT_LOCALE = "en"

#: Locales this module can localize an explainer into: every interface
#: language. Sentences live in ``reporting.explain.*`` in ``backend/locales``.
SUPPORTED_LOCALES: tuple[str, ...] = tuple(_ALL_LOCALES)

# ── Classification standards (may be named; they are open standards) ───────
#
# Display names for the classification code systems the platform supports.
# These are open standards, not commercial brands, so naming them is fine.
_CLASSIFICATION_STANDARDS: dict[str, str] = {
    "din276": "DIN 276",
    "nrm": "NRM",
    "masterformat": "MasterFormat",
    "uniformat": "UniFormat",
    "gaeb": "GAEB",
}


def _norm_locale(locale: str | None) -> str:
    """Normalize a locale to one this module localizes, else English."""
    if not locale:
        return DEFAULT_LOCALE
    code = locale.strip().lower()
    # Accept region-tagged locales like ``de-DE`` / ``ru_RU`` by taking the
    # language subtag.
    code = re.split(r"[-_]", code, maxsplit=1)[0]
    return code if code in SUPPORTED_LOCALES else DEFAULT_LOCALE


# ── Currency helpers ───────────────────────────────────────────────────────


def normalize_currency(code: str | None) -> str:
    """Validate and normalize a single ISO 4217 currency code.

    Args:
        code: A currency code such as ``"eur"`` or ``"USD"``.

    Returns:
        The upper-cased, stripped 3-letter code.

    Raises:
        ValueError: If *code* is empty or not a 3-letter code. A precise
            message is raised rather than silently defaulting, so a caller
            never stamps a malformed currency onto a report.
    """
    if code is None:
        raise ValueError("currency code is required (got None)")
    normalized = code.strip().upper()
    if not normalized:
        raise ValueError("currency code is required (got an empty string)")
    if not _CURRENCY_CODE_RE.match(normalized):
        raise ValueError(f"'{code}' is not a 3-letter ISO 4217 currency code (e.g. EUR, USD, GBP, JPY).")
    return normalized


def ensure_single_currency(codes: Iterable[str | None]) -> str:
    """Return the one currency shared by *codes*, or raise if they blend.

    Money must never be blended across currency codes. This guard collapses
    an iterable of codes to the single code they all share.

    Args:
        codes: Currency codes to check. ``None`` / empty entries are
            ignored so a partially-tagged data set still resolves as long
            as every tagged entry agrees.

    Returns:
        The single normalized ISO 4217 code shared by every non-empty entry.

    Raises:
        ValueError: If no non-empty code is present, or if two different
            codes are found (a blend the platform forbids).
    """
    seen: list[str] = []
    for raw in codes:
        if raw is None:
            continue
        candidate = raw.strip().upper()
        if not candidate:
            continue
        normalized = normalize_currency(candidate)
        if normalized not in seen:
            seen.append(normalized)
    if not seen:
        raise ValueError("no currency code present; cannot resolve a single currency")
    if len(seen) > 1:
        raise ValueError(
            f"cannot blend currencies in one report total: found {', '.join(seen)}. Convert to one currency first."
        )
    return seen[0]


def to_decimal(value: object) -> Decimal:
    """Parse a money-ish value to an exact, finite :class:`~decimal.Decimal`.

    Accepts a :class:`~decimal.Decimal`, an ``int``, or a numeric string
    (with surrounding whitespace and thousands separators as spaces
    tolerated). A ``float`` is accepted but routed through its string form
    so the caller's literal is preserved without binary-float drift.

    Args:
        value: The value to parse.

    Returns:
        A finite ``Decimal``.

    Raises:
        ValueError: If *value* is ``None``, cannot be parsed, or parses to a
            non-finite ``Decimal`` (``NaN`` / ``Infinity``). Never returns a
            non-finite number, so a report total can never become ``NaN`` /
            ``inf``.
    """
    if value is None:
        raise ValueError("amount is required (got None)")
    if isinstance(value, Decimal):
        parsed = value
    elif isinstance(value, bool):
        # bool is an int subclass; treating True as 1 in money is a bug.
        raise ValueError(f"boolean {value!r} is not a valid money amount")
    elif isinstance(value, int):
        parsed = Decimal(value)
    elif isinstance(value, float):
        parsed = Decimal(str(value))
    elif isinstance(value, str):
        text = value.strip().replace(" ", "")
        if not text:
            raise ValueError("amount is required (got an empty string)")
        try:
            parsed = Decimal(text)
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"'{value}' is not a valid numeric amount") from exc
    else:
        raise ValueError(f"unsupported amount type: {type(value).__name__}")
    if not parsed.is_finite():
        raise ValueError(f"amount must be finite, got {parsed}")
    return parsed


# ── Core math (report total, ratio, breakdown, top-N) ──────────────────────


def report_total(amounts: Iterable[object]) -> Decimal:
    """Sum line amounts into a Decimal-exact report total.

    Derivation: the total is the exact sum of every line amount, with no
    float intermediate. An empty set totals ``Decimal("0")`` (a report with
    no lines has a zero total, which is a defined value, not an error).
    Negative amounts are allowed - a credit, an adjustment, or a retention
    release is a legitimate negative line.

    Args:
        amounts: Line amounts, each parseable by :func:`to_decimal`.

    Returns:
        The exact ``Decimal`` sum.

    Raises:
        ValueError: If any amount is not a valid finite number.
    """
    total = Decimal("0")
    for amount in amounts:
        total += to_decimal(amount)
    return total


def ratio_of_total(part: object, total: object) -> Decimal:
    """Return ``part / total`` as a ratio, with a zero-total guard.

    A "percent of total" is a ratio: ``ratio_of_total(25, 100)`` is
    ``Decimal("0.25")`` (25 percent). When *total* is zero the ratio is
    defined here as ``Decimal("0")`` rather than raising or returning
    ``inf`` / ``NaN`` - a share of a zero total is reported as 0 percent.

    Args:
        part: The portion amount (parseable by :func:`to_decimal`).
        total: The overall total (parseable by :func:`to_decimal`).

    Returns:
        The ratio as a ``Decimal``. Can exceed 1 (a part larger than the
        total) or be negative (a negative part or total); both are real
        situations the caller may legitimately want to see.

    Raises:
        ValueError: If either argument is not a valid finite number.
    """
    total_dec = to_decimal(total)
    part_dec = to_decimal(part)
    if total_dec == 0:
        return Decimal("0")
    return part_dec / total_dec


@dataclass(frozen=True)
class GroupShare:
    """One group in a cost breakdown.

    Attributes:
        key: The group key (e.g. a trade, a DIN 276 cost group code).
        total: The Decimal-exact sum of the group's line amounts.
        share: The group total as a ratio of the overall total
            (``0.0 .. 1.0`` typically; ``0`` when the overall total is 0).
        count: How many lines fell into the group.
    """

    key: str
    total: Decimal
    share: Decimal
    count: int


@dataclass(frozen=True)
class Breakdown:
    """A grouped cost breakdown plus its overall total.

    Attributes:
        total: The overall Decimal-exact total across every group.
        groups: The groups, sorted by ``total`` descending (ties broken by
            key ascending for a stable, deterministic order).
        currency: The single ISO 4217 code every amount reads in, or
            ``None`` when the caller did not declare one.
    """

    total: Decimal
    groups: tuple[GroupShare, ...]
    currency: str | None = None


def group_breakdown(
    items: Iterable[object],
    key_getter: Callable[[object], object],
    amount_getter: Callable[[object], object],
    *,
    currency: str | None = None,
) -> Breakdown:
    """Group *items* by a key and total each group with its share of the whole.

    Derivation: each item's amount (via *amount_getter*) is summed per group
    key (via *key_getter*); every group's share is its total divided by the
    overall total, with the zero-total guard from :func:`ratio_of_total` (so
    a zero overall total yields a 0 share for every group rather than a
    division error). Groups are returned sorted by total descending.

    Args:
        items: The line items to group.
        key_getter: Maps an item to its group key. The key is stringified so
            heterogeneous key types still group and sort deterministically.
        amount_getter: Maps an item to its amount (parseable by
            :func:`to_decimal`).
        currency: Optional single ISO 4217 code to validate and stamp onto
            the result. When given it is normalized; pass it so the caller
            can prove the breakdown reads in exactly one currency.

    Returns:
        A :class:`Breakdown` with the overall total and per-group shares.

    Raises:
        ValueError: If an amount is invalid, or if *currency* is malformed.
    """
    resolved_currency = normalize_currency(currency) if currency is not None else None

    totals: dict[str, Decimal] = {}
    counts: dict[str, int] = {}
    for item in items:
        key = str(key_getter(item))
        amount = to_decimal(amount_getter(item))
        totals[key] = totals.get(key, Decimal("0")) + amount
        counts[key] = counts.get(key, 0) + 1

    overall = sum(totals.values(), Decimal("0"))

    groups = tuple(
        GroupShare(
            key=key,
            total=group_total,
            share=ratio_of_total(group_total, overall),
            count=counts[key],
        )
        # Sort by total descending, then key ascending for a stable order.
        for key, group_total in sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))
    )
    return Breakdown(total=overall, groups=groups, currency=resolved_currency)


def top_n_by_value(
    items: Iterable[object],
    value_getter: Callable[[object], object],
    n: int,
) -> list[object]:
    """Return the *n* items with the highest value, largest first.

    Args:
        items: The items to rank.
        value_getter: Maps an item to a value parseable by
            :func:`to_decimal`.
        n: How many items to return. ``0`` yields an empty list.

    Returns:
        Up to *n* items sorted by value descending. Ties keep their original
        relative order (the sort is stable), so the result is deterministic.
        Fewer than *n* items in means fewer than *n* out.

    Raises:
        ValueError: If *n* is negative, or if a value is not a valid finite
            number.
    """
    if n < 0:
        raise ValueError(f"n must be zero or positive, got {n}")
    if n == 0:
        return []
    materialized = list(items)
    # Decorate with the parsed value and original index so ties stay stable
    # and the sort never compares two heterogeneous items directly.
    decorated = [(to_decimal(value_getter(item)), idx, item) for idx, item in enumerate(materialized)]
    decorated.sort(key=lambda triple: (-triple[0], triple[1]))
    return [item for _, _, item in decorated[:n]]


# ── Formatting helpers ─────────────────────────────────────────────────────


def format_money(amount: object, currency: str | None = None) -> str:
    """Format an amount as ``"<amount> <CUR>"`` with no float coercion.

    The amount is parsed by :func:`to_decimal` and stringified exactly (its
    own precision is preserved). The currency, when supplied, is validated
    and appended so the figure reads in one explicit currency. When no
    currency is supplied only the amount is returned - the caller then owns
    labelling it.

    Args:
        amount: The amount (parseable by :func:`to_decimal`).
        currency: Optional ISO 4217 code to append.

    Returns:
        e.g. ``"1234.56 EUR"`` or ``"1234.56"``.

    Raises:
        ValueError: If the amount is invalid or the currency is malformed.
    """
    amount_str = str(to_decimal(amount))
    if currency is None:
        return amount_str
    return f"{amount_str} {normalize_currency(currency)}"


def format_ratio_as_percent(
    ratio: object,
    *,
    places: int = 1,
    locale: str | None = None,
) -> str:
    """Format a ratio (``0.25``) as a percent string (``"25.0%"``).

    Args:
        ratio: A ratio parseable by :func:`to_decimal` (``0.25`` means 25
            percent). Values outside ``0 .. 1`` are formatted as-is (a share
            above the total or a negative share is a real thing to show).
        places: Decimal places in the percentage (default 1). Must be zero
            or positive.
        locale: Reserved for future locale-specific decimal separators;
            currently the output uses a period separator in every locale so
            it round-trips cleanly. Accepted for API symmetry.

    Returns:
        The percentage string, e.g. ``"25.0%"``.

    Raises:
        ValueError: If *ratio* is invalid or *places* is negative.
    """
    if places < 0:
        raise ValueError(f"places must be zero or positive, got {places}")
    _norm_locale(locale)  # validate / normalize even though output is neutral
    ratio_dec = to_decimal(ratio)
    percent = ratio_dec * Decimal(100)
    quantum = Decimal(1) if places == 0 else Decimal(1).scaleb(-places)
    return f"{percent.quantize(quantum)}%"


def classification_label(standard: str, code: str | None = None) -> str:
    """Return a display label for a classification standard and optional code.

    These are open standards (DIN 276, NRM, MasterFormat, UniFormat, GAEB),
    not commercial brands, so naming them is intended.

    Args:
        standard: A standard key (case-insensitive), e.g. ``"din276"``.
        code: Optional classification code within that standard, e.g.
            ``"330"``.

    Returns:
        e.g. ``"DIN 276 330"`` or, when the standard is unknown, the raw
        standard token upper-cased so the label still conveys something.
    """
    name = _CLASSIFICATION_STANDARDS.get(standard.strip().lower(), standard.strip().upper())
    code_clean = (code or "").strip()
    return f"{name} {code_clean}".strip()


# ── Plain-language explainers (localized, English fallback) ─────────────────


def explain_report_total(
    total: object,
    *,
    line_count: int,
    currency: str | None = None,
    locale: str | None = None,
) -> str:
    """One line stating how a report total was derived.

    Example (en): ``"Report total: 1500.00 EUR (sum of 3 lines)."``

    Args:
        total: The total (parseable by :func:`to_decimal`).
        line_count: How many lines were summed.
        currency: Optional ISO 4217 code to show alongside the amount.
        locale: Target locale (any interface language; English fallback).

    Returns:
        A single explanatory sentence.

    Raises:
        ValueError: If the total is invalid, the currency is malformed, or
            *line_count* is negative.
    """
    if line_count < 0:
        raise ValueError(f"line_count must be zero or positive, got {line_count}")
    loc = _norm_locale(locale)
    money = format_money(total, currency)
    plural = "one" if line_count == 1 else "other"
    return t(f"reporting.explain.report_total_{plural}", loc, money=money, count=line_count)


def explain_percent_of_total(
    part: object,
    total: object,
    *,
    currency: str | None = None,
    locale: str | None = None,
) -> str:
    """One line stating a part as a percent of the total, with the guard noted.

    Example (en):
    ``"250.00 EUR is 25.0% of 1000.00 EUR (percent of total)."``
    When the total is zero the sentence explains the zero-total guard rather
    than dividing.

    Args:
        part: The portion amount (parseable by :func:`to_decimal`).
        total: The overall total (parseable by :func:`to_decimal`).
        currency: Optional ISO 4217 code shown alongside both amounts.
        locale: Target locale (any interface language; English fallback).

    Returns:
        A single explanatory sentence.

    Raises:
        ValueError: If either amount is invalid or the currency is malformed.
    """
    loc = _norm_locale(locale)
    part_money = format_money(part, currency)
    total_money = format_money(total, currency)
    if to_decimal(total) == 0:
        return t("reporting.explain.percent_zero_total", loc, part=part_money, total=total_money)
    ratio = ratio_of_total(part, total)
    percent = format_ratio_as_percent(ratio, locale=loc)
    return t("reporting.explain.percent_of_total", loc, part=part_money, percent=percent, total=total_money)


def explain_breakdown(breakdown: Breakdown, *, locale: str | None = None) -> str:
    """One line summarizing a cost breakdown (group count, total, currency).

    Example (en):
    ``"Cost breakdown: 4 groups, total 1000.00 EUR."``

    Args:
        breakdown: A :class:`Breakdown` from :func:`group_breakdown`.
        locale: Target locale (any interface language; English fallback).

    Returns:
        A single explanatory sentence. An empty breakdown says "no data".
    """
    loc = _norm_locale(locale)
    n = len(breakdown.groups)
    if n == 0:
        return t("reporting.explain.breakdown_empty", loc)
    money = format_money(breakdown.total, breakdown.currency)
    return t(f"reporting.explain.breakdown_{'one' if n == 1 else 'other'}", loc, count=n, money=money)


def explain_top_n(
    items: Sequence[object],
    requested_n: int,
    *,
    locale: str | None = None,
) -> str:
    """One line stating how many items a top-N selection returned.

    Example (en): ``"Top 5 by value: showing 3 of 3 lines."``

    Args:
        items: The selected items (the output of :func:`top_n_by_value`).
        requested_n: The N originally requested.
        locale: Target locale (any interface language; English fallback).

    Returns:
        A single explanatory sentence.

    Raises:
        ValueError: If *requested_n* is negative.
    """
    if requested_n < 0:
        raise ValueError(f"requested_n must be zero or positive, got {requested_n}")
    loc = _norm_locale(locale)
    shown = len(items)
    return t(f"reporting.explain.top_n_{'one' if shown == 1 else 'other'}", loc, requested=requested_n, shown=shown)
