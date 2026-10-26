# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""International, framework-free payroll helpers.

This module holds small, side-effect-free helpers that make construction
labour payroll correct and clear for users anywhere in the world. It has no
database, no FastAPI, and no third-party dependency, so it imports and runs the
same in a unit test as it does in the request path. The service layer keeps its
own ``HTTPException``-raising logic and its DB-backed batch math; these helpers
are the pure arithmetic and plain-language layer a report, an export, a
background job, or a test can reuse without booting anything.

Design rules that keep the platform usable worldwide:

* No hardcoded currency, wage law, or locale. Every wage figure carries the
  currency the caller supplies; we never guess a default such as EUR or USD.
* No hardcoded overtime or deduction rule. The overtime threshold hours, the
  overtime multiplier, and any deduction rate are always explicit parameters.
  The defaults are neutral and documented (no overtime threshold unless one is
  given, an overtime multiplier of 1.5, no deduction unless a rate or amount is
  supplied), so any national convention plugs in without touching this code.
* Money is Decimal-exact. Amounts never touch ``float`` and never drift.
* Money is never summed across different currency codes. Mixing codes is a
  clean input error, not a silently-wrong total.
* Dates are ISO 8601 (``YYYY-MM-DD``).
* Bad input (garbage numbers, negative hours or rate, a zero-hours effective
  rate, an empty set) is turned into a clear ``ValueError`` or a well-defined
  zero. It never becomes a 500, a NaN, or an infinity.
* Pay-component and status words are localised (English, German, Russian) with
  an English fallback so a payroll clerk reads plain language, never a raw code.

Every money figure is derived by an explicit, documented formula and the
component parts (regular hours, overtime hours, the rates and multiplier used)
are exposed alongside the totals, so a worker or an auditor can see how each
number was reached.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from app.core.i18n import catalogue_table

# Default money rounding step. Two decimal places suit most currencies; a
# caller working in a zero-decimal or three-decimal currency passes its own
# ``quantum``. This is a default, never a hardcoded assumption.
DEFAULT_MONEY_QUANTUM = Decimal("0.01")

# Rounding step for an hourly rate. Rates commonly carry more precision than a
# final money amount, so four places is the default; callers may override.
DEFAULT_RATE_QUANTUM = Decimal("0.0001")

# ISO 8601 calendar date shape used across the module.
ISO_DATE_FORMAT = "YYYY-MM-DD"

# Neutral default overtime multiplier. Many jurisdictions pay overtime at 1.5x
# ("time and a half"), so it is a sensible default, but it is always overridable
# per the applicable agreement or law. It is never treated as a fixed rule.
DEFAULT_OVERTIME_MULTIPLIER = Decimal("1.5")


# ── Plain-language glossary ───────────────────────────────────────────────────

# One line per payroll concept, in plain words a site manager, a worker, or a
# payroll clerk understands in a few seconds, each stating the formula the
# figure is derived from. Kept here so the API and payslips can explain every
# number they show instead of assuming the reader knows the term.
CONCEPTS: dict[str, str] = {
    "regular_hours": (
        "The hours worked at the normal rate: the total hours up to the overtime "
        "threshold. With no threshold set, every hour is regular."
    ),
    "overtime_hours": (
        "The hours worked beyond the overtime threshold: total hours minus the "
        "threshold, never below zero. With no threshold set, this is zero."
    ),
    "overtime_threshold": (
        "The number of hours after which work counts as overtime, for example per "
        "day or per week. It is set per agreement or law, never assumed."
    ),
    "overtime_multiplier": (
        "How much more an overtime hour pays than a regular hour, for example 1.5 "
        "for time-and-a-half. It is set per agreement or law, never assumed."
    ),
    "rate": "The pay for one regular hour of work, in a stated currency (per hour).",
    "basic_rate": (
        "The part of the hourly rate that the overtime multiplier applies to. "
        "Where a rate is made up of a basic wage plus an hourly fringe benefit "
        "amount, only the basic wage is the overtime base. With no basic rate "
        "stated, the whole rate is the base."
    ),
    "fringe_rate": (
        "The part of the hourly rate paid as a fringe benefit, either into a "
        "benefit plan or in cash. It is paid on every hour at its face value and "
        "is never multiplied by the overtime multiplier."
    ),
    "overtime_base_rate": (
        "The rate the overtime multiplier was actually applied to: the basic "
        "rate when one is stated, otherwise the whole hourly rate."
    ),
    "regular_pay": "Pay for the regular hours: regular hours multiplied by the hourly rate.",
    "overtime_pay": (
        "Pay for the overtime hours. With no basic rate stated it is overtime "
        "hours multiplied by the hourly rate multiplied by the overtime "
        "multiplier. Where a basic rate is stated, the multiplier applies to the "
        "basic rate only and the remaining fringe part is paid at face value on "
        "each overtime hour."
    ),
    "gross_pay": (
        "Pay before deductions: regular pay plus overtime pay. This is the employer's labour cost for the work."
    ),
    "deduction": (
        "An amount withheld from gross pay, such as tax, a social contribution, or "
        "a pension. The amount or rate is entered by the user, never assumed."
    ),
    "net_pay": (
        "Take-home pay: gross pay minus the total of all deductions, floored at zero so a payslip is never negative."
    ),
    "effective_hourly_rate": (
        "The average pay per hour actually worked: gross pay divided by total "
        "hours. With zero hours it is a well-defined zero, never a division error."
    ),
}


def explain(concept: str) -> str:
    """Return a one-line plain-language explanation of a payroll concept.

    Args:
        concept: One of the keys in :data:`CONCEPTS` (for example ``"gross_pay"``
            or ``"effective_hourly_rate"``).

    Returns:
        A short sentence, including the formula, describing the concept.

    Raises:
        ValueError: If ``concept`` is not a known key, so a typo is caught
            rather than silently returning nothing.
    """
    try:
        return CONCEPTS[concept]
    except KeyError as exc:
        known = ", ".join(sorted(CONCEPTS))
        raise ValueError(f"Unknown payroll concept {concept!r}. Known: {known}.") from exc


# ── Plain-language, localised labels ──────────────────────────────────────────

# Each table maps a code to a plain-language label in English, German, and
# Russian. English is the fallback for any locale we do not carry, and an
# unknown code is humanised rather than shown raw, so a status a newer workflow
# adds still renders readably.

# Batch lifecycle status (mirrors the service FSM: draft/submitted/approved/posted).
_BATCH_STATUS_LABELS: dict[str, dict[str, str]] = catalogue_table(
    "payroll.intl.batch_status_labels", ("draft", "submitted", "approved", "posted")
)

# Deduction bucket (mirrors ``schemas.DeductionType``: tax/social/pension/other).
_DEDUCTION_TYPE_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "tax": "Tax",
        "social": "Social contribution",
        "pension": "Pension",
        "other": "Other deduction",
    },
    "de": {
        "tax": "Steuer",
        "social": "Sozialabgabe",
        "pension": "Rente",
        "other": "Sonstiger Abzug",
    },
    "ru": {
        "tax": "Налог",
        "social": "Социальный взнос",
        "pension": "Пенсия",
        "other": "Прочее удержание",
    },
}

# Pay component (the figures this module derives on a payslip).
_PAY_COMPONENT_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "regular_pay": "Regular pay",
        "overtime_pay": "Overtime pay",
        "gross_pay": "Gross pay",
        "deductions": "Deductions",
        "net_pay": "Net pay",
        "effective_hourly_rate": "Effective hourly rate",
    },
    "de": {
        "regular_pay": "Grundlohn",
        "overtime_pay": "Überstundenlohn",
        "gross_pay": "Bruttolohn",
        "deductions": "Abzüge",
        "net_pay": "Nettolohn",
        "effective_hourly_rate": "Effektiver Stundenlohn",
    },
    "ru": {
        "regular_pay": "Оплата по норме",
        "overtime_pay": "Оплата сверхурочных",
        "gross_pay": "Начислено (брутто)",
        "deductions": "Удержания",
        "net_pay": "К выплате (нетто)",
        "effective_hourly_rate": "Эффективная ставка за час",
    },
}

# The word for "not stated / unknown", localised so a missing value never shows
# a raw English word inside an otherwise-translated screen.
_UNKNOWN_LABELS: dict[str, str] = {"en": "Unknown", "de": "Unbekannt", "ru": "Неизвестно"}


def _normalize_locale(locale: str | None) -> str:
    """Return a short lower-case language code (``"de-CH"`` -> ``"de"``)."""
    if not locale:
        return "en"
    return str(locale).replace("_", "-").split("-")[0].strip().lower() or "en"


def _localized_label(code: str | None, locale: str | None, table: dict[str, dict[str, str]]) -> str:
    """Look ``code`` up in ``table`` for ``locale``, English then humanised fallback.

    Resolution order: the requested language, then English, then a readable form
    of the raw code (``"net_pay"`` -> ``"Net pay"``). A missing code yields the
    localised word for "Unknown". This never raises and never returns a blank,
    so the UI is safe against a code a newer module adds.
    """
    lang = _normalize_locale(locale)
    if not code:
        return _UNKNOWN_LABELS.get(lang, _UNKNOWN_LABELS["en"])
    per_lang = table.get(lang) or table["en"]
    label = per_lang.get(code)
    if label is None:
        label = table["en"].get(code)
    if label is None:
        return code.replace("_", " ").strip().capitalize()
    return label


def describe_batch_status(code: str | None, locale: str | None = None) -> str:
    """Return a plain-language, localised label for a payroll batch status."""
    return _localized_label(code, locale, _BATCH_STATUS_LABELS)


def describe_deduction_type(code: str | None, locale: str | None = None) -> str:
    """Return a plain-language, localised label for a deduction type."""
    return _localized_label(code, locale, _DEDUCTION_TYPE_LABELS)


def describe_pay_component(code: str | None, locale: str | None = None) -> str:
    """Return a plain-language, localised label for a pay component."""
    return _localized_label(code, locale, _PAY_COMPONENT_LABELS)


# ── Decimal parsing (strict, plain ValueError) ────────────────────────────────


def to_decimal(value: object, field: str = "value") -> Decimal:
    """Parse ``value`` into a finite ``Decimal`` or raise a clear ``ValueError``.

    Rejects ``None``, empty strings, non-numeric text, and non-finite values
    (``NaN`` / infinity) so a bad figure can never turn into a silent NaN in a
    total.

    Args:
        value: The raw value to parse (string, number, or Decimal).
        field: Names the offending input in the error message.

    Returns:
        A finite ``Decimal``.

    Raises:
        ValueError: If the value is missing, non-numeric, or non-finite.
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

    Half-up is the rounding people expect on a payslip. The default step is two
    decimal places; pass another ``quantum`` for a currency that uses a
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


# ── Dates ─────────────────────────────────────────────────────────────────────


def parse_iso_date(value: object, field: str = "date") -> date:
    """Parse an ISO 8601 date string or a ``date``/``datetime`` into a ``date``.

    Raises a clear ``ValueError`` for ``None`` or an unparseable value so a bad
    stored date is caught rather than silently mishandled.
    """
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value is None:
        raise ValueError(f"{field} is required (got None).")
    try:
        return date.fromisoformat(str(value).strip())
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{field} is not an ISO 8601 date ({ISO_DATE_FORMAT}): {value!r}.") from exc


# ── Hours: regular vs overtime split ──────────────────────────────────────────


def split_regular_overtime(
    total_hours: object,
    overtime_threshold: object | None = None,
) -> tuple[Decimal, Decimal]:
    """Split total hours into (regular, overtime) against an explicit threshold.

    Regular hours are the hours up to the threshold; overtime hours are anything
    beyond it. When ``overtime_threshold`` is ``None`` there is no overtime rule
    in force, so every hour is regular and overtime is zero. This keeps the
    default neutral: no country's working-time rule is baked in.

    Args:
        total_hours: The hours worked. Must be a non-negative finite number.
        overtime_threshold: The hours after which work is overtime, or ``None``
            for no overtime rule. Must be non-negative when given.

    Returns:
        A ``(regular_hours, overtime_hours)`` tuple of Decimals that always sums
        back to ``total_hours``.

    Raises:
        ValueError: If the hours are negative or non-finite, or the threshold is
            negative.
    """
    total = _non_negative(to_decimal(total_hours, "total_hours"), "total_hours")
    if overtime_threshold is None:
        return total, Decimal("0")
    threshold = _non_negative(to_decimal(overtime_threshold, "overtime_threshold"), "overtime_threshold")
    regular = min(total, threshold)
    overtime = max(total - threshold, Decimal("0"))
    return regular, overtime


# ── Pay math (Decimal-exact) ──────────────────────────────────────────────────


def regular_pay(
    regular_hours: object,
    rate: object,
    *,
    quantum: Decimal = DEFAULT_MONEY_QUANTUM,
) -> Decimal:
    """Return pay for the regular hours = regular hours times the hourly rate.

    Both inputs must be non-negative finite numbers. The result is rounded to
    ``quantum`` (default two decimals) with half-up rounding. The currency is
    the caller's concern; this returns the number only.
    """
    hours = _non_negative(to_decimal(regular_hours, "regular_hours"), "regular_hours")
    hourly = _non_negative(to_decimal(rate, "rate"), "rate")
    return quantize_money(hours * hourly, quantum)


def resolve_overtime_base(rate: object, basic_rate: object | None = None) -> tuple[Decimal, Decimal]:
    """Split an hourly rate into the overtime base and the part paid at face value.

    Returns ``(base, flat)`` where ``base`` is the rate the overtime multiplier
    applies to and ``flat`` is the remainder, which is paid at face value on
    every hour including overtime ones.

    With ``basic_rate`` omitted this is ``(rate, 0)``: the whole rate is the
    base, which is the behaviour every caller had before this parameter existed.

    Where a rate is made up of a basic wage plus an hourly fringe benefit
    amount, the fringe part is not part of the overtime base. Multiplying a
    combined rate by the overtime multiplier overpays the fringe and is the
    commonest error in construction wage compliance, so the split is available
    as its own function rather than left to each caller to remember.

    Args:
        rate: The whole hourly rate. Non-negative and finite.
        basic_rate: The part the multiplier applies to, or ``None`` for the
            whole rate. Non-negative and finite when given.

    Returns:
        A ``(base, flat)`` tuple of Decimals that sums back to ``rate``.

    Raises:
        ValueError: If either figure is negative or non-finite, or if
            ``basic_rate`` exceeds ``rate`` (which would make the fringe part
            negative and means the two figures do not describe one rate).
    """
    hourly = _non_negative(to_decimal(rate, "rate"), "rate")
    if basic_rate is None:
        return hourly, Decimal("0")
    base = _non_negative(to_decimal(basic_rate, "basic_rate"), "basic_rate")
    if base > hourly:
        raise ValueError(f"basic_rate {base} must not exceed the hourly rate {hourly}.")
    return base, hourly - base


def overtime_pay(
    overtime_hours: object,
    rate: object,
    overtime_multiplier: object = DEFAULT_OVERTIME_MULTIPLIER,
    *,
    basic_rate: object | None = None,
    quantum: Decimal = DEFAULT_MONEY_QUANTUM,
) -> Decimal:
    """Return pay for the overtime hours.

    With no ``basic_rate``, overtime pay = overtime hours times the hourly rate
    times the overtime multiplier. The multiplier is an explicit parameter
    (default 1.5 for time-and-a-half) so any agreement or law applies; it is
    never a fixed rule.

    Where ``basic_rate`` is given, the multiplier applies to the basic rate only
    and the remainder of the hourly rate is paid at face value on each overtime
    hour: ``hours x (basic x multiplier + (rate - basic))``. That is what a rate
    split into a basic wage and an hourly fringe benefit amount requires, and
    the two forms agree exactly when ``basic_rate == rate``.

    All inputs must be non-negative finite numbers. Zero overtime hours gives a
    well-defined ``0.00``.
    """
    hours = _non_negative(to_decimal(overtime_hours, "overtime_hours"), "overtime_hours")
    base, flat = resolve_overtime_base(rate, basic_rate)
    multiplier = _non_negative(to_decimal(overtime_multiplier, "overtime_multiplier"), "overtime_multiplier")
    return quantize_money(hours * ((base * multiplier) + flat), quantum)


def gross_pay(
    regular_hours: object,
    overtime_hours: object,
    rate: object,
    overtime_multiplier: object = DEFAULT_OVERTIME_MULTIPLIER,
    *,
    basic_rate: object | None = None,
    quantum: Decimal = DEFAULT_MONEY_QUANTUM,
) -> Decimal:
    """Return gross pay = regular pay plus overtime pay.

    Regular hours are always paid at the whole hourly rate. Overtime hours are
    paid per :func:`overtime_pay`: at the whole rate times the multiplier when
    no ``basic_rate`` is given, and otherwise with the multiplier applied to the
    basic rate only and the fringe remainder paid at face value.

    Gross pay is the pay before any deduction, and is the employer's labour cost
    for the work. All inputs must be non-negative finite numbers; the multiplier
    is explicit (default 1.5). Rounded once at the end to ``quantum``.
    """
    hours_reg = _non_negative(to_decimal(regular_hours, "regular_hours"), "regular_hours")
    hours_ot = _non_negative(to_decimal(overtime_hours, "overtime_hours"), "overtime_hours")
    hourly = _non_negative(to_decimal(rate, "rate"), "rate")
    base, flat = resolve_overtime_base(hourly, basic_rate)
    multiplier = _non_negative(to_decimal(overtime_multiplier, "overtime_multiplier"), "overtime_multiplier")
    total = (hours_reg * hourly) + (hours_ot * ((base * multiplier) + flat))
    return quantize_money(total, quantum)


def total_deductions(
    deductions: Iterable[object],
    *,
    quantum: Decimal = DEFAULT_MONEY_QUANTUM,
) -> Decimal:
    """Sum a set of deduction amounts, all in the same (caller-owned) currency.

    Each amount must be a non-negative finite number. An empty set sums to a
    well-defined ``0.00`` rather than raising. This does no currency conversion:
    the caller guarantees the amounts share one currency (see
    :func:`ensure_single_currency`).
    """
    running = Decimal("0")
    for index, amount in enumerate(deductions):
        running += _non_negative(to_decimal(amount, f"deductions[{index}]"), f"deductions[{index}]")
    return quantize_money(running, quantum)


def percentage_deduction(
    base: object,
    rate_percent: object,
    *,
    quantum: Decimal = DEFAULT_MONEY_QUANTUM,
) -> Decimal:
    """Return a percentage deduction = base times rate percent divided by 100.

    The rate is an explicit parameter the caller supplies (for example a tax or
    contribution percentage); the platform never injects one. The percent is
    clamped into ``[0, 100]`` so a deduction can never exceed its base or go
    negative. Both inputs must be non-negative finite numbers.
    """
    base_amount = _non_negative(to_decimal(base, "base"), "base")
    percent = _non_negative(to_decimal(rate_percent, "rate_percent"), "rate_percent")
    if percent > Decimal("100"):
        percent = Decimal("100")
    return quantize_money(base_amount * percent / Decimal("100"), quantum)


def net_pay(
    gross: object,
    deductions: Iterable[object] = (),
    *,
    quantum: Decimal = DEFAULT_MONEY_QUANTUM,
) -> Decimal:
    """Return take-home pay = gross pay minus the total of all deductions.

    The result is floored at zero: an over-deduction is clamped rather than
    producing a nonsensical negative payslip. ``gross`` and every deduction must
    be non-negative finite numbers; an empty ``deductions`` set leaves net equal
    to gross. No currency conversion happens here; the caller guarantees one
    currency across gross and deductions.
    """
    gross_amount = _non_negative(to_decimal(gross, "gross"), "gross")
    withheld = total_deductions(deductions, quantum=quantum)
    net = gross_amount - withheld
    if net < 0:
        net = Decimal("0")
    return quantize_money(net, quantum)


def effective_hourly_rate(
    gross: object,
    total_hours: object,
    *,
    quantum: Decimal = DEFAULT_RATE_QUANTUM,
) -> Decimal:
    """Return the average pay per hour worked = gross pay divided by total hours.

    Guards division by zero: when ``total_hours`` is zero there is nothing to
    average across, so the result is a well-defined ``0`` rather than a
    division-by-zero error or an infinity. Both inputs must be non-negative
    finite numbers. The result is rounded to ``quantum`` (default four decimals,
    the rate precision).
    """
    gross_amount = _non_negative(to_decimal(gross, "gross"), "gross")
    hours = _non_negative(to_decimal(total_hours, "total_hours"), "total_hours")
    if hours == 0:
        return quantize_money(Decimal("0"), quantum)
    return quantize_money(gross_amount / hours, quantum)


# ── Payslip breakdown (explainable components) ────────────────────────────────


def payslip_breakdown(
    total_hours: object,
    rate: object,
    currency: str | None = None,
    *,
    overtime_threshold: object | None = None,
    overtime_multiplier: object = DEFAULT_OVERTIME_MULTIPLIER,
    basic_rate: object | None = None,
    deductions: Iterable[object] = (),
    quantum: Decimal = DEFAULT_MONEY_QUANTUM,
    rate_quantum: Decimal = DEFAULT_RATE_QUANTUM,
) -> dict[str, str]:
    """Break a payslip line down into its components, each figure explained.

    Returns a small report a UI, a payslip, or an export can show directly. The
    component parts are exposed alongside the totals so every number is
    auditable:

        * ``total_hours``            - the hours worked, echoed.
        * ``regular_hours``          - hours up to the overtime threshold.
        * ``overtime_hours``         - hours beyond the threshold (0 if none set).
        * ``overtime_threshold``     - the threshold used, or ``""`` if none.
        * ``rate``                   - the hourly rate, echoed.
        * ``overtime_multiplier``    - the multiplier used (default 1.5).
        * ``basic_rate``             - the stated basic rate, or ``""`` if none.
        * ``fringe_rate``            - the remainder of the rate paid at face
                                       value on every hour, ``0`` if no basic
                                       rate was stated.
        * ``overtime_base_rate``     - the rate the multiplier was applied to.
        * ``currency``               - the stated currency code, or ``""``.
        * ``regular_pay``            - regular hours times rate.
        * ``overtime_pay``           - the multiplier applied to the overtime
                                       base, plus the fringe part at face value.
        * ``gross_pay``              - regular pay plus overtime pay.
        * ``total_deductions``       - sum of the supplied deductions.
        * ``net_pay``                - gross minus deductions, floored at zero.
        * ``effective_hourly_rate``  - gross divided by total hours (0 if none).

    Money is Decimal-exact and returned as strings, matching the money-as-string
    contract used across the API. The currency is carried through untouched and
    never guessed, and no overtime or deduction rule is assumed: the threshold,
    multiplier, and deductions are all the caller's explicit inputs.
    """
    hourly = _non_negative(to_decimal(rate, "rate"), "rate")
    multiplier = _non_negative(to_decimal(overtime_multiplier, "overtime_multiplier"), "overtime_multiplier")
    ot_base, fringe_part = resolve_overtime_base(hourly, basic_rate)
    regular_hours, overtime_hours = split_regular_overtime(total_hours, overtime_threshold)
    total = regular_hours + overtime_hours

    reg_pay = regular_pay(regular_hours, hourly, quantum=quantum)
    ot_pay = overtime_pay(overtime_hours, hourly, multiplier, basic_rate=basic_rate, quantum=quantum)
    gross = gross_pay(regular_hours, overtime_hours, hourly, multiplier, basic_rate=basic_rate, quantum=quantum)
    withheld = total_deductions(deductions, quantum=quantum)
    net = net_pay(gross, deductions, quantum=quantum)
    per_hour = effective_hourly_rate(gross, total, quantum=rate_quantum)

    threshold_out = ""
    if overtime_threshold is not None:
        threshold_out = format(to_decimal(overtime_threshold, "overtime_threshold").normalize(), "f")

    return {
        "total_hours": format(total.normalize(), "f"),
        "regular_hours": format(regular_hours.normalize(), "f"),
        "overtime_hours": format(overtime_hours.normalize(), "f"),
        "overtime_threshold": threshold_out,
        "rate": str(quantize_money(hourly, rate_quantum)),
        "overtime_multiplier": format(multiplier.normalize(), "f"),
        "basic_rate": "" if basic_rate is None else str(quantize_money(ot_base, rate_quantum)),
        "fringe_rate": str(quantize_money(fringe_part, rate_quantum)),
        "overtime_base_rate": str(quantize_money(ot_base, rate_quantum)),
        "currency": normalize_currency(currency),
        "regular_pay": str(reg_pay),
        "overtime_pay": str(ot_pay),
        "gross_pay": str(gross),
        "total_deductions": str(withheld),
        "net_pay": str(net),
        "effective_hourly_rate": str(per_hour),
    }
