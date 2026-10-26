# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""International, dependency-free helpers for resource-planning readouts.

This module is deliberately pure (no database, no I/O, stdlib only) and
side-effect free so it can be reused by services, exporters, reports and
tests without any wiring. It answers the plain question a planner asks about
labor and plant allocation anywhere in the world:

    "How loaded is this resource, is it overbooked, and how much headroom
     is left?"

Design rules that keep it usable worldwide:

- No hardcoded locale or units. Load and capacity are plain numbers in the
  SAME caller-chosen unit (allocation percent, hours, crew members, machine
  count, ...). The helpers never assume percent.
- No fixed working day or working week. When you need to turn a period into
  an hours capacity, you pass the working hours explicitly
  (``available_hours``); nothing here bakes in 8 hours or a 5-day week.
- Dates are ISO 8601 (``parse_iso8601`` / ``days_between``). No locale-specific
  date parsing.
- Every figure is explainable: ``load_report`` returns the derived numbers
  together with the components they came from and a one-line plain-language
  explainer, and the label helpers localize resource type / status words into
  English, German and Russian with an English (then raw-value) fallback.

Edge-case contract (never 500, never NaN, never inf):

- Negative load or capacity raises a clean ``ValueError``.
- Non-finite (NaN / inf) or non-numeric input raises a clean ``ValueError``.
- Zero capacity is guarded: the utilization rate is undefined without a
  capacity, so it is reported as ``0.0`` and ``capacity_defined`` is ``False``;
  the overallocation flag still correctly treats any positive load against
  zero capacity as an overallocation.
- Utilization may exceed 100 percent - that IS an overallocation - so the
  upper bound is never clamped. It is only ever guarded against NaN / inf.
- Empty inputs return empty results, never errors.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.core.i18n import catalogue_table

# ── Localized vocabulary ─────────────────────────────────────────────────
# Keys mirror the real module vocabulary (see schemas.py / models.py):
#   resource_type   : person | crew | equipment | subcontractor
#   resource status : active | inactive | on_leave
#   assignment status: proposed | confirmed | in_progress | completed | cancelled
# Only en / de / ru are provided; any other locale falls back to English,
# and any unknown value falls back to the raw value so nothing is ever lost.

SUPPORTED_LOCALES: tuple[str, ...] = ("en", "de", "ru")
FALLBACK_LOCALE = "en"

RESOURCE_TYPE_LABELS: dict[str, dict[str, str]] = catalogue_table(
    "resources.intl.resource_type_labels", ("person", "crew", "equipment", "subcontractor")
)

RESOURCE_STATUS_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "active": "Active",
        "inactive": "Inactive",
        "on_leave": "On leave",
    },
    "de": {
        "active": "Aktiv",
        "inactive": "Inaktiv",
        "on_leave": "Abwesend",
    },
    "ru": {
        "active": "Активен",
        "inactive": "Неактивен",
        "on_leave": "В отпуске",
    },
}

ASSIGNMENT_STATUS_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "proposed": "Proposed",
        "confirmed": "Confirmed",
        "in_progress": "In progress",
        "completed": "Completed",
        "cancelled": "Cancelled",
    },
    "de": {
        "proposed": "Vorgeschlagen",
        "confirmed": "Bestatigt",
        "in_progress": "In Arbeit",
        "completed": "Abgeschlossen",
        "cancelled": "Storniert",
    },
    "ru": {
        "proposed": "Предложено",
        "confirmed": "Подтверждено",
        "in_progress": "В работе",
        "completed": "Завершено",
        "cancelled": "Отменено",
    },
}

# One-line, plain-language explainers for each derived figure. English text is
# the source of truth; de / ru mirror it. ``explain`` falls back to English.
EXPLAINERS: dict[str, dict[str, str]] = {
    "en": {
        "utilization_rate": (
            "Utilization rate is allocated load divided by capacity, shown as a "
            "percent; above 100 percent means the resource is overbooked."
        ),
        "allocation_vs_capacity": (
            "Allocation is the load booked onto the resource; capacity is the most "
            "it can take. Both are in the same unit you supplied."
        ),
        "overallocation": (
            "Overallocation is how much the booked load exceeds capacity; a positive "
            "amount means work must be moved, dropped or reinforced."
        ),
        "remaining_capacity": (
            "Remaining capacity is capacity minus allocated load; a negative value "
            "means the resource is overbooked by that amount."
        ),
    },
    "de": {
        "utilization_rate": (
            "Die Auslastung ist die gebuchte Last geteilt durch die Kapazitat, als "
            "Prozentwert; uber 100 Prozent bedeutet Uberbuchung."
        ),
        "allocation_vs_capacity": (
            "Die Zuteilung ist die auf die Ressource gebuchte Last; die Kapazitat ist "
            "das Maximum. Beide in der von Ihnen gewahlten Einheit."
        ),
        "overallocation": (
            "Die Uberbuchung ist der Betrag, um den die Last die Kapazitat "
            "ubersteigt; ein positiver Wert erfordert Umplanung oder Verstarkung."
        ),
        "remaining_capacity": (
            "Die Restkapazitat ist Kapazitat minus gebuchte Last; ein negativer Wert "
            "bedeutet Uberbuchung um diesen Betrag."
        ),
    },
    "ru": {
        "utilization_rate": (
            "Загрузка - это назначенная нагрузка, деленная на мощность, в процентах; "
            "выше 100 процентов означает перегрузку ресурса."
        ),
        "allocation_vs_capacity": (
            "Назначение - это нагрузка на ресурс; мощность - это максимум, который он "
            "выдерживает. Обе величины в выбранной вами единице."
        ),
        "overallocation": (
            "Перегрузка - это величина превышения нагрузкой мощности; положительное "
            "значение означает, что работу надо перенести, снять или усилить."
        ),
        "remaining_capacity": (
            "Остаток мощности - это мощность минус назначенная нагрузка; "
            "отрицательное значение означает перегрузку на эту величину."
        ),
    },
}


def _normalize_locale(locale: str | None) -> str:
    """Reduce a BCP-47-ish tag (e.g. ``de-CH``) to a supported base language.

    Unknown or empty locales fall back to English so callers never crash on an
    unexpected tag.
    """
    if not locale:
        return FALLBACK_LOCALE
    base = locale.replace("_", "-").split("-", 1)[0].strip().lower()
    return base if base in SUPPORTED_LOCALES else FALLBACK_LOCALE


def _localized_label(table: dict[str, dict[str, str]], value: str | None, locale: str | None) -> str:
    """Look up ``value`` in ``table`` for ``locale`` with English then raw fallback."""
    if value is None:
        return ""
    lang = _normalize_locale(locale)
    catalog = table.get(lang, {})
    if value in catalog:
        return catalog[value]
    english = table.get(FALLBACK_LOCALE, {})
    return english.get(value, value)


def resource_type_label(value: str | None, locale: str | None = FALLBACK_LOCALE) -> str:
    """Localized label for a resource type (person / crew / equipment / subcontractor)."""
    return _localized_label(RESOURCE_TYPE_LABELS, value, locale)


def resource_status_label(value: str | None, locale: str | None = FALLBACK_LOCALE) -> str:
    """Localized label for a resource status (active / inactive / on_leave)."""
    return _localized_label(RESOURCE_STATUS_LABELS, value, locale)


def assignment_status_label(value: str | None, locale: str | None = FALLBACK_LOCALE) -> str:
    """Localized label for an assignment status (proposed / confirmed / ...)."""
    return _localized_label(ASSIGNMENT_STATUS_LABELS, value, locale)


def explain(topic: str, locale: str | None = FALLBACK_LOCALE) -> str:
    """Return the one-line explainer for a figure, localized with English fallback.

    Args:
        topic: one of ``utilization_rate``, ``allocation_vs_capacity``,
            ``overallocation``, ``remaining_capacity``.
        locale: target locale; unknown locales fall back to English.

    Returns:
        The explainer string, or an empty string if the topic is unknown.
    """
    lang = _normalize_locale(locale)
    catalog = EXPLAINERS.get(lang, {})
    if topic in catalog:
        return catalog[topic]
    return EXPLAINERS[FALLBACK_LOCALE].get(topic, "")


# ── Numeric guards ────────────────────────────────────────────────────────


def _as_finite_nonneg(value: Any, name: str) -> float:  # noqa: ANN401 - accepts any numeric-like
    """Coerce ``value`` to a finite, non-negative float or raise ``ValueError``.

    Accepts int / float / Decimal / numeric strings. Rejects NaN, inf, negative
    values and anything non-numeric so downstream math can never produce NaN or
    inf and can never divide against a nonsense figure.
    """
    if isinstance(value, bool):
        # bool is an int subclass; treat it as a programming error, not a load.
        raise ValueError(f"{name} must be a number, not a boolean")
    try:
        if isinstance(value, Decimal):
            result = float(value)
        else:
            result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number, got {value!r}") from exc
    if math.isnan(result) or math.isinf(result):
        raise ValueError(f"{name} must be a finite number, got {value!r}")
    if result < 0:
        raise ValueError(f"{name} must not be negative, got {result}")
    return result


# ── Core pure figures ─────────────────────────────────────────────────────


def utilization_rate(allocated: Any, capacity: Any, *, ndigits: int = 2) -> float:  # noqa: ANN401
    """Utilization rate as a percent: ``allocated / capacity * 100``.

    Zero-capacity guard: a rate is undefined without a capacity, so a zero
    capacity returns ``0.0`` (see ``load_report`` for the ``capacity_defined``
    flag and the overallocation figure, which still flags any positive load
    against zero capacity). The upper bound is never clamped: a result above
    100 is a real overallocation and is returned as-is. The result is always a
    finite float.

    Args:
        allocated: booked load, same unit as ``capacity``. Non-negative.
        capacity: maximum load the resource can take. Non-negative.
        ndigits: rounding precision for the returned percent.

    Raises:
        ValueError: if either input is negative, non-finite or non-numeric.
    """
    a = _as_finite_nonneg(allocated, "allocated")
    c = _as_finite_nonneg(capacity, "capacity")
    if c == 0:
        return 0.0
    return round(a / c * 100.0, ndigits)


def overallocation(allocated: Any, capacity: Any, *, ndigits: int = 4) -> dict[str, Any]:  # noqa: ANN401
    """Overallocation flag and amount for a resource.

    The amount is ``allocated - capacity`` when positive, else ``0.0``. Any
    positive load against a zero capacity is an overallocation.

    Returns a dict with ``overallocated`` (bool), ``overallocation_amount``
    (float, in the input unit), and the ``allocated`` / ``capacity`` components
    it was derived from.

    Raises:
        ValueError: if either input is negative, non-finite or non-numeric.
    """
    a = _as_finite_nonneg(allocated, "allocated")
    c = _as_finite_nonneg(capacity, "capacity")
    over = a - c
    is_over = over > 0
    return {
        "overallocated": is_over,
        "overallocation_amount": round(over, ndigits) if is_over else 0.0,
        "allocated": a,
        "capacity": c,
    }


def remaining_capacity(allocated: Any, capacity: Any, *, ndigits: int = 4) -> float:  # noqa: ANN401
    """Remaining headroom: ``capacity - allocated`` in the input unit.

    A negative result means the resource is overbooked by that amount. The
    result is always a finite float.

    Raises:
        ValueError: if either input is negative, non-finite or non-numeric.
    """
    a = _as_finite_nonneg(allocated, "allocated")
    c = _as_finite_nonneg(capacity, "capacity")
    return round(c - a, ndigits)


def counts_by_resource_type(resources: Iterable[Any]) -> dict[str, int]:
    """Count resources per resource type.

    Accepts an iterable of plain type strings, mappings with a ``resource_type``
    key, or objects with a ``resource_type`` attribute (e.g. ORM rows). Items
    whose type cannot be determined are counted under ``"unknown"``. An empty
    iterable returns an empty dict.
    """
    counts: dict[str, int] = {}
    for item in resources:
        if isinstance(item, str):
            rtype = item
        elif isinstance(item, dict):
            rtype = item.get("resource_type") or "unknown"
        else:
            rtype = getattr(item, "resource_type", None) or "unknown"
        rtype = str(rtype)
        counts[rtype] = counts.get(rtype, 0) + 1
    return counts


# ── Working-hours capacity (no fixed working day assumed) ─────────────────


def available_hours(days: Any, working_hours_per_day: Any, *, ndigits: int = 2) -> float:  # noqa: ANN401
    """Nominal available hours over ``days`` at ``working_hours_per_day``.

    Working hours per day is an explicit parameter - nothing here assumes 8
    hours or a 5-day week, so it fits any country, shift pattern or calendar.
    Both inputs must be non-negative and finite.

    Raises:
        ValueError: if either input is negative, non-finite or non-numeric.
    """
    d = _as_finite_nonneg(days, "days")
    h = _as_finite_nonneg(working_hours_per_day, "working_hours_per_day")
    return round(d * h, ndigits)


# ── Combined, fully explainable report ─────────────────────────────────────


def load_report(
    allocated: Any,  # noqa: ANN401
    capacity: Any,  # noqa: ANN401
    *,
    locale: str | None = FALLBACK_LOCALE,
    resource_type: str | None = None,
    status: str | None = None,
    ndigits: int = 2,
) -> dict[str, Any]:
    """One explainable readout combining every figure for a resource.

    This is the explainability entry point: it exposes each derived number
    together with the components it came from and a localized one-line
    explainer, so a UI or report can show not just the value but how it was
    reached. It never raises for a zero or empty capacity; it only raises the
    documented ``ValueError`` for negative / non-finite / non-numeric inputs.

    Args:
        allocated: booked load, same unit as ``capacity``.
        capacity: maximum load the resource can take.
        locale: locale for labels and explainers (English fallback).
        resource_type: optional resource type to localize into ``type_label``.
        status: optional resource status to localize into ``status_label``.
        ndigits: rounding precision for the utilization percent.

    Returns:
        A JSON-serializable dict with the figures, their components, boolean
        flags, localized labels and explainers.
    """
    a = _as_finite_nonneg(allocated, "allocated")
    c = _as_finite_nonneg(capacity, "capacity")
    capacity_defined = c > 0

    over = overallocation(a, c)
    util = utilization_rate(a, c, ndigits=ndigits)
    remaining = remaining_capacity(a, c)

    report: dict[str, Any] = {
        "allocated": a,
        "capacity": c,
        "capacity_defined": capacity_defined,
        "utilization_percent": util,
        "overallocated": over["overallocated"],
        "overallocation_amount": over["overallocation_amount"],
        "remaining_capacity": remaining,
        "components": {
            "utilization_percent": {
                "formula": "allocated / capacity * 100",
                "allocated": a,
                "capacity": c,
                "capacity_defined": capacity_defined,
            },
            "overallocation_amount": {
                "formula": "max(allocated - capacity, 0)",
                "allocated": a,
                "capacity": c,
            },
            "remaining_capacity": {
                "formula": "capacity - allocated",
                "allocated": a,
                "capacity": c,
            },
        },
        "explainers": {
            "utilization_rate": explain("utilization_rate", locale),
            "allocation_vs_capacity": explain("allocation_vs_capacity", locale),
            "overallocation": explain("overallocation", locale),
            "remaining_capacity": explain("remaining_capacity", locale),
        },
    }
    if resource_type is not None:
        report["resource_type"] = resource_type
        report["type_label"] = resource_type_label(resource_type, locale)
    if status is not None:
        report["status"] = status
        report["status_label"] = resource_status_label(status, locale)
    return report


# ── ISO 8601 date helpers ─────────────────────────────────────────────────


def parse_iso8601(value: str | date | datetime) -> datetime:
    """Parse an ISO 8601 date or datetime string into a ``datetime``.

    Accepts a plain ``date`` (promoted to midnight) or ``datetime`` unchanged,
    or an ISO 8601 string (``2026-07-05`` or ``2026-07-05T14:30:00+02:00``).
    A trailing ``Z`` (UTC) is accepted. Raises a clean ``ValueError`` on any
    unparseable input.
    """
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if not isinstance(value, str):
        raise ValueError(f"expected an ISO 8601 string or date, got {value!r}")
    text = value.strip()
    if not text:
        raise ValueError("expected a non-empty ISO 8601 string")
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"not a valid ISO 8601 date/datetime: {value!r}") from exc


def days_between(start: str | date | datetime, end: str | date | datetime, *, ndigits: int = 4) -> float:
    """Number of calendar days between two ISO 8601 instants (``end - start``).

    Both bounds are parsed via ``parse_iso8601``. A non-positive span (end at or
    before start) returns ``0.0`` rather than a negative number, so downstream
    capacity math is never fed a negative period. When one bound is timezone
    aware and the other naive, both are compared as-is only if compatible; a
    mismatch raises a clean ``ValueError`` instead of a ``TypeError``.
    """
    a = parse_iso8601(start)
    b = parse_iso8601(end)
    aware_a = a.tzinfo is not None
    aware_b = b.tzinfo is not None
    if aware_a != aware_b:
        raise ValueError("cannot compare a timezone-aware date with a naive date; make both consistent")
    seconds = (b - a).total_seconds()
    if seconds <= 0:
        return 0.0
    return round(seconds / 86400.0, ndigits)
