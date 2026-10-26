# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""International, framework-free accommodation helpers.

This module holds small, side-effect-free helpers that make accommodation
money and occupancy math correct and clear for users anywhere in the world.
It has no database, no FastAPI, and no third-party dependency, so it imports
and runs the same in a unit test as it does in the request path.

Design rules that keep the platform usable worldwide:

* No hardcoded currency, unit, or locale. A rate is always "per person per
  night" and carries an explicit currency the caller supplies. We never guess
  a default currency such as EUR or USD.
* Money is Decimal-exact. Amounts never touch ``float`` and never drift.
* Money is never summed across different currency codes. Mixing codes is a
  clean input error, not a silently-wrong total.
* Dates are ISO 8601 (``YYYY-MM-DD``). A stay length is counted in nights, the
  unit the whole lodging industry bills in.
* Bad input (garbage numbers, negative counts, zero capacity, zero nights) is
  turned into a clear ``ValueError`` or a well-defined zero. It never becomes a
  500, a NaN, or an infinity.
* Status words are localised (English, German, Russian) with an English
  fallback so an operator reads plain language, never a raw code.

The service layer keeps its own ``HTTPException``-raising helpers. These
functions raise plain ``ValueError`` so they stay reusable outside a request
(reports, exports, background jobs, tests). A caller at the API edge can wrap a
``ValueError`` in a 400.
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

# ISO 8601 calendar date shape used across the module.
ISO_DATE_FORMAT = "YYYY-MM-DD"

# The unit every accommodation rate is quoted in. Spelled out so a report or an
# API response can state it and never leave "100" ambiguous.
RATE_UNIT = "per person per night"


# ── Plain-language glossary ───────────────────────────────────────────────────

# One line per accommodation concept, in plain words a site manager or
# estimator understands in a few seconds. Kept here so the API and reports can
# explain every figure they show instead of assuming the reader knows the term.
CONCEPTS: dict[str, str] = {
    "night": ("One night of stay: the gap between the check-in date and the check-out date, counted in whole nights."),
    "nights": (
        "The length of a stay in nights: check-out date minus check-in date. A same-day check-out is zero nights."
    ),
    "person_night": ("One person staying for one night. Two people for three nights is six person-nights."),
    "bed_nights": ("The total person-nights of a stay: the number of occupants multiplied by the number of nights."),
    "rate": ("The price of housing one person for one night, in a stated currency (per person per night)."),
    "accommodation_cost": (
        "The cost of a stay: the per-person-per-night rate multiplied by the total person-nights (bed-nights)."
    ),
    "cost_per_person_night": (
        "The average cost of housing one person for one night: total cost divided by total person-nights."
    ),
    "occupancy_rate": ("How full an accommodation is: occupied beds divided by total capacity, from 0 to 1."),
    "capacity": "The total number of people an accommodation or room can sleep.",
    "occupied": "The number of beds currently taken by occupants.",
    "vacant": "The number of beds still free: capacity minus occupied, never below zero.",
}


def explain(concept: str) -> str:
    """Return a one-line plain-language explanation of an accommodation concept.

    ``concept`` is one of the keys in :data:`CONCEPTS` (for example
    ``"occupancy_rate"`` or ``"bed_nights"``). Raises ``ValueError`` for an
    unknown key so a typo is caught rather than silently returning nothing.
    """
    try:
        return CONCEPTS[concept]
    except KeyError as exc:
        known = ", ".join(sorted(CONCEPTS))
        raise ValueError(f"Unknown accommodation concept {concept!r}. Known: {known}.") from exc


# ── Plain-language, localised status labels ───────────────────────────────────

# Every table mirrors the enum patterns in ``schemas.py`` so the codes stay in
# step. Each code maps to a plain-language label in English, German, and
# Russian. English is the fallback for any locale we do not carry.

# Accommodation kind (``schemas._KIND_PATTERN``).
_KIND_LABELS: dict[str, dict[str, str]] = catalogue_table(
    "accommodation.intl.kind_labels", ("worker_camp", "rental", "hotel")
)

# Room status (``schemas._ROOM_STATUS_PATTERN``).
_ROOM_STATUS_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "available": "Available",
        "occupied": "Occupied",
        "maintenance": "Under maintenance",
        "blocked": "Blocked",
    },
    "de": {
        "available": "Verfügbar",
        "occupied": "Belegt",
        "maintenance": "In Wartung",
        "blocked": "Gesperrt",
    },
    "ru": {
        "available": "Свободно",
        "occupied": "Занято",
        "maintenance": "На обслуживании",
        "blocked": "Заблокировано",
    },
}

# Booking status (``schemas._BOOKING_STATUS_PATTERN``).
_BOOKING_STATUS_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "reserved": "Reserved",
        "checked_in": "Checked in",
        "checked_out": "Checked out",
        "cancelled": "Cancelled",
    },
    "de": {
        "reserved": "Reserviert",
        "checked_in": "Eingecheckt",
        "checked_out": "Ausgecheckt",
        "cancelled": "Storniert",
    },
    "ru": {
        "reserved": "Забронировано",
        "checked_in": "Заселен",
        "checked_out": "Выселен",
        "cancelled": "Отменено",
    },
}

# Charge status (``schemas._CHARGE_STATUS_PATTERN``).
_CHARGE_STATUS_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "pending": "Pending",
        "invoiced": "Invoiced",
        "paid": "Paid",
        "waived": "Waived",
    },
    "de": {
        "pending": "Offen",
        "invoiced": "In Rechnung gestellt",
        "paid": "Bezahlt",
        "waived": "Erlassen",
    },
    "ru": {
        "pending": "Ожидает",
        "invoiced": "Выставлен счет",
        "paid": "Оплачено",
        "waived": "Списано",
    },
}

# The word for "not stated / unknown", localised so a missing status never
# shows a raw English word inside an otherwise-translated screen.
_UNKNOWN_LABELS: dict[str, str] = {"en": "Unknown", "de": "Unbekannt", "ru": "Неизвестно"}


def _normalize_locale(locale: str | None) -> str:
    """Return a short lower-case language code (``"de-CH"`` -> ``"de"``)."""
    if not locale:
        return "en"
    return str(locale).replace("_", "-").split("-")[0].strip().lower() or "en"


def _localized_label(code: str | None, locale: str | None, table: dict[str, dict[str, str]]) -> str:
    """Look ``code`` up in ``table`` for ``locale``, English then humanised fallback.

    Resolution order: the requested language, then English, then a readable
    form of the raw code (``"checked_in"`` -> ``"Checked in"``). A missing code
    yields the localised word for "Unknown". This never raises and never
    returns a blank, so the UI is safe against a status a newer module adds.
    """
    lang = _normalize_locale(locale)
    if not code:
        return _UNKNOWN_LABELS.get(lang, _UNKNOWN_LABELS["en"])
    per_lang = table.get(lang) or table["en"]
    label = per_lang.get(code)
    if label is None:
        label = table["en"].get(code)
    if label is None:
        # Unknown code from a newer workflow: show it readably, never blank.
        return code.replace("_", " ").strip().capitalize()
    return label


def describe_kind(code: str | None, locale: str | None = None) -> str:
    """Return a plain-language, localised label for an accommodation ``kind``."""
    return _localized_label(code, locale, _KIND_LABELS)


def describe_room_status(code: str | None, locale: str | None = None) -> str:
    """Return a plain-language, localised label for a room status code."""
    return _localized_label(code, locale, _ROOM_STATUS_LABELS)


def describe_booking_status(code: str | None, locale: str | None = None) -> str:
    """Return a plain-language, localised label for a booking status code."""
    return _localized_label(code, locale, _BOOKING_STATUS_LABELS)


def describe_charge_status(code: str | None, locale: str | None = None) -> str:
    """Return a plain-language, localised label for a charge status code."""
    return _localized_label(code, locale, _CHARGE_STATUS_LABELS)


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


def _non_negative_int(value: object, field: str) -> int:
    """Parse a non-negative whole number of people or nights, else ``ValueError``."""
    parsed = _non_negative(to_decimal(value, field), field)
    if parsed != parsed.to_integral_value():
        raise ValueError(f"{field} must be a whole number, got {value!r}.")
    return int(parsed)


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


# ── Dates and stay length ─────────────────────────────────────────────────────


def _to_date(value: object, field: str) -> date:
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


def nights_between(check_in: object, check_out: object) -> int:
    """Return the number of nights between two ISO 8601 dates.

    A stay is counted the way lodging is billed: the number of nights equals
    ``check_out - check_in`` in whole days. A same-day check-out is zero
    nights. ``check_out`` before ``check_in`` is a genuine input error and
    raises ``ValueError`` rather than returning a negative count.
    """
    start = _to_date(check_in, "check_in")
    end = _to_date(check_out, "check_out")
    if end < start:
        raise ValueError(f"check_out ({end.isoformat()}) must not precede check_in ({start.isoformat()}).")
    return (end - start).days


def bed_nights(occupants: object, check_in: object, check_out: object) -> int:
    """Return the person-nights (bed-nights) of a stay.

    Person-nights = occupants multiplied by nights. ``occupants`` must be a
    non-negative whole number; the dates follow :func:`nights_between`. Zero
    occupants or a zero-night stay yields ``0`` rather than an error, so an
    empty or same-day booking is a well-defined zero.
    """
    people = _non_negative_int(occupants, "occupants")
    nights = nights_between(check_in, check_out)
    return people * nights


# ── Cost math ─────────────────────────────────────────────────────────────────


def total_accommodation_cost(
    rate_per_person_night: object,
    person_nights: object,
    *,
    quantum: Decimal = DEFAULT_MONEY_QUANTUM,
) -> Decimal:
    """Return the accommodation cost = rate per person-night times person-nights.

    Both inputs must be non-negative finite numbers. ``person_nights`` is the
    bed-nights figure from :func:`bed_nights`. The result is rounded to
    ``quantum`` (default two decimals) with half-up rounding. Zero nights or a
    zero rate gives a well-defined ``Decimal("0.00")``. The currency is the
    caller's concern; this returns the number only, so an amount is never
    blended across currencies here.
    """
    rate = _non_negative(to_decimal(rate_per_person_night, "rate_per_person_night"), "rate_per_person_night")
    nights = _non_negative(to_decimal(person_nights, "person_nights"), "person_nights")
    return quantize_money(rate * nights, quantum)


def cost_per_person_night(
    total_cost: object,
    person_nights: object,
    *,
    quantum: Decimal = DEFAULT_MONEY_QUANTUM,
) -> Decimal:
    """Return the average cost of housing one person for one night.

    This is ``total_cost / person_nights``, with a zero guard: when
    ``person_nights`` is zero there is nothing to divide across, so the result
    is a well-defined ``Decimal("0.00")`` rather than a division-by-zero error
    or an infinity. Both inputs must be non-negative finite numbers.
    """
    total = _non_negative(to_decimal(total_cost, "total_cost"), "total_cost")
    nights = _non_negative(to_decimal(person_nights, "person_nights"), "person_nights")
    if nights == 0:
        return quantize_money(Decimal("0"), quantum)
    return quantize_money(total / nights, quantum)


def stay_cost_breakdown(
    rate_per_person_night: object,
    occupants: object,
    check_in: object,
    check_out: object,
    currency: str | None = None,
    *,
    quantum: Decimal = DEFAULT_MONEY_QUANTUM,
) -> dict[str, str]:
    """Break a stay down into its cost components, each figure explained.

    Returns a small report a UI or export can show directly:

        * ``occupants`` / ``nights``    - the two stay inputs, echoed.
        * ``bed_nights``                - occupants multiplied by nights.
        * ``rate_per_person_night``     - the per-person-per-night rate, echoed.
        * ``rate_unit``                 - the literal ``"per person per night"``.
        * ``currency``                  - the stated currency code, or ``""``.
        * ``total_cost``                - rate multiplied by bed-nights, rounded.
        * ``cost_per_person_night``     - the effective per-person-per-night cost.

    Money is Decimal-exact and returned as strings, matching the
    money-as-string contract used across the API. The currency is carried
    through untouched and never guessed, so the caller stays in control of it.
    """
    people = _non_negative_int(occupants, "occupants")
    nights = nights_between(check_in, check_out)
    person_nights = people * nights
    rate = _non_negative(to_decimal(rate_per_person_night, "rate_per_person_night"), "rate_per_person_night")

    total = total_accommodation_cost(rate, person_nights, quantum=quantum)
    per_pn = cost_per_person_night(total, person_nights, quantum=quantum)

    return {
        "occupants": str(people),
        "nights": str(nights),
        "bed_nights": str(person_nights),
        "rate_per_person_night": str(quantize_money(rate, quantum)),
        "rate_unit": RATE_UNIT,
        "currency": normalize_currency(currency),
        "total_cost": str(total),
        "cost_per_person_night": str(per_pn),
    }


# ── Occupancy ─────────────────────────────────────────────────────────────────


def occupancy_rate(occupied: object, capacity: object) -> dict[str, str]:
    """Compare occupied beds against capacity, with a zero-capacity guard.

    Returns a small report a UI can show directly:

        * ``occupied`` / ``capacity`` - the two input counts, echoed.
        * ``vacant``      - capacity minus occupied, never below zero.
        * ``rate``        - occupied divided by capacity, from 0 to 1.
        * ``rate_percent``- the same figure as a 0 to 100 percentage.
        * ``is_full``     - true once every bed is taken.
        * ``overbooked``  - true when more people are placed than beds exist.

    Both inputs must be non-negative finite numbers. Zero capacity is not an
    error: the rate is defined as ``0`` (an empty asset is not occupied),
    guarding against division by zero. The rate never exceeds 1 even when more
    people are placed than beds exist; that surplus shows up in ``overbooked``.
    """
    cap = _non_negative(to_decimal(capacity, "capacity"), "capacity")
    occ = _non_negative(to_decimal(occupied, "occupied"), "occupied")

    vacant = max(cap - occ, Decimal("0"))

    if cap == 0:
        # No beds exist, so occupancy is zero by definition; this is the
        # division-by-zero guard.
        rate = Decimal("0")
    else:
        rate = min(occ / cap, Decimal("1"))

    rate = rate.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    rate_percent = (rate * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    return {
        "occupied": format(occ.normalize(), "f"),
        "capacity": format(cap.normalize(), "f"),
        "vacant": format(vacant.normalize(), "f"),
        "rate": str(rate),
        "rate_percent": str(rate_percent),
        "is_full": "true" if (cap > 0 and occ >= cap) else "false",
        "overbooked": "true" if occ > cap else "false",
    }
