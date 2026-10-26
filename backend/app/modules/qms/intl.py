# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""International, locale-safe quality helpers for the QMS module.

This module is deliberately pure and dependency-free (standard library
only). It carries no database access, no ORM imports and no I/O, so it is
safe to import from anywhere and trivial to unit-test offline.

Design rules that make the QMS usable worldwide:

* No hardcoded locale. Every user-facing word goes through
  :func:`localize_severity` / :func:`localize_status`, which translate to
  English, German or Russian and fall back to English (then to the raw
  key) so a missing translation never blocks a response.
* ISO 8601 everywhere. Dates are parsed and compared with
  :meth:`datetime.date.fromisoformat`; no locale-specific date parsing.
* Thresholds are parameters with documented defaults. The only threshold
  here, ``grace_days`` on the overdue check, defaults to ``0`` (a due date
  is overdue the day after it passes).
* Rates are dimensionless ratios, never currency. A rate is a plain float
  in ``[0.0, 1.0]``; :func:`as_percent` presents the same value in
  ``[0.0, 100.0]``.
* Every rate helper returns its components alongside the rate so the
  number is explainable ("2 of 3 inspections passed => 0.667").

Edge cases are guarded, not left to blow up: empty sets yield a defined
zero rate, and negative or impossible counts raise :class:`ValueError`
(a clean client error) rather than producing NaN, inf or a 500.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from app.core.i18n import catalogue_table

# ── Vocabulary ────────────────────────────────────────────────────────────
# Ordered from least to most serious so callers can sort or threshold on it.
SEVERITY_ORDER: tuple[str, ...] = ("observation", "minor", "major", "critical")

# Nonconformance / NCR statuses that mean "still needs work". Everything not
# listed here (closed, cancelled) is treated as resolved. Kept explicit so the
# open-rate helper has one obvious source of truth.
OPEN_NCR_STATUSES: frozenset[str] = frozenset(
    {"open", "action_pending", "verifying"},
)
CLOSED_NCR_STATUSES: frozenset[str] = frozenset({"closed", "cancelled"})

# Supported UI languages. English is always the fallback.
SUPPORTED_LANGS: tuple[str, ...] = ("en", "de", "ru")
_FALLBACK_LANG = "en"

# Localized severity words (en / de / ru). English fallback on any gap.
_SEVERITY_WORDS: dict[str, dict[str, str]] = catalogue_table(
    "qms.intl.severity_words", ("observation", "minor", "major", "critical")
)

# Localized status words spanning every QMS entity (ITP plan, inspection,
# NCR, punch item, audit, finding). English fallback on any gap.
_STATUS_WORDS: dict[str, dict[str, str]] = {
    "en": {
        "draft": "draft",
        "active": "active",
        "superseded": "superseded",
        "scheduled": "scheduled",
        "in_progress": "in progress",
        "passed": "passed",
        "failed": "failed",
        "conditional": "conditional",
        "open": "open",
        "action_pending": "action pending",
        "verifying": "verifying",
        "closed": "closed",
        "cancelled": "cancelled",
        "assigned": "assigned",
        "ready_for_inspection": "ready for inspection",
        "rejected": "rejected",
        "planned": "planned",
        "completed": "completed",
    },
    "de": {
        "draft": "Entwurf",
        "active": "aktiv",
        "superseded": "abgeloest",
        "scheduled": "geplant",
        "in_progress": "in Bearbeitung",
        "passed": "bestanden",
        "failed": "durchgefallen",
        "conditional": "bedingt",
        "open": "offen",
        "action_pending": "Massnahme ausstehend",
        "verifying": "in Pruefung",
        "closed": "geschlossen",
        "cancelled": "storniert",
        "assigned": "zugewiesen",
        "ready_for_inspection": "pruefbereit",
        "rejected": "abgelehnt",
        "planned": "geplant",
        "completed": "abgeschlossen",
    },
    "ru": {
        "draft": "chernovik",
        "active": "aktivnyy",
        "superseded": "zameneno",
        "scheduled": "zaplanirovano",
        "in_progress": "v rabote",
        "passed": "proydeno",
        "failed": "ne proydeno",
        "conditional": "uslovno",
        "open": "otkryto",
        "action_pending": "ozhidaet deystviya",
        "verifying": "proverka",
        "closed": "zakryto",
        "cancelled": "otmeneno",
        "assigned": "naznacheno",
        "ready_for_inspection": "gotovo k proverke",
        "rejected": "otkloneno",
        "planned": "zaplanirovano",
        "completed": "zaversheno",
    },
}

# One-line, plain-language explanations of the quality concepts the module
# surfaces. Keyed by concept; localized en / de / ru with English fallback.
_GLOSSARY: dict[str, dict[str, str]] = {
    "nonconformance": {
        "en": "A nonconformance is work or a product that does not meet the specification and must be fixed or accepted by concession.",
        "de": "Eine Nichtkonformitaet ist eine Leistung oder ein Produkt, das die Vorgabe nicht erfuellt und behoben oder freigegeben werden muss.",
        "ru": "Nesootvetstvie - eto rabota ili produkt, kotoryy ne otvechaet trebovaniyam i dolzhen byt ispravlen ili prinyat po ustupke.",
    },
    "inspection_pass_rate": {
        "en": "Inspection pass rate is how many inspections passed divided by all inspections done, from 0 to 1.",
        "de": "Die Pruefquote ist die Anzahl bestandener Pruefungen geteilt durch alle durchgefuehrten Pruefungen, von 0 bis 1.",
        "ru": "Dolya proydennykh proverok - eto chislo proydennykh proverok, delennoe na vse vypolnennye proverki, ot 0 do 1.",
    },
    "first_pass_yield": {
        "en": "First-pass yield is the share of inspections that passed on the first attempt, with no rework, from 0 to 1.",
        "de": "Die Erstpruefquote ist der Anteil der Pruefungen, die beim ersten Versuch ohne Nacharbeit bestanden wurden, von 0 bis 1.",
        "ru": "Vykhod s pervogo raza - eto dolya proverok, proydennykh s pervoy popytki bez dorabotki, ot 0 do 1.",
    },
    "open_vs_closed": {
        "en": "Open items still need work; closed items are resolved. The open rate is open items divided by all items.",
        "de": "Offene Punkte brauchen noch Arbeit; geschlossene sind erledigt. Die Offenrate ist offene Punkte geteilt durch alle Punkte.",
        "ru": "Otkrytye punkty trebuyut raboty; zakrytye - resheny. Dolya otkrytykh - eto otkrytye punkty, delennye na vse punkty.",
    },
    "overdue": {
        "en": "An item is overdue when its due date has passed and it is not yet closed.",
        "de": "Ein Punkt ist ueberfaellig, wenn sein Faelligkeitsdatum ueberschritten ist und er noch nicht geschlossen wurde.",
        "ru": "Punkt prosrochen, kogda ego srok proshel, a on eshche ne zakryt.",
    },
    "severity": {
        "en": "Severity ranks how serious a nonconformance is, from observation to minor, major and critical.",
        "de": "Der Schweregrad bewertet, wie ernst eine Nichtkonformitaet ist, von Beobachtung ueber geringfuegig und erheblich bis kritisch.",
        "ru": "Uroven ser'eznosti pokazyvaet, naskolko ser'ezno nesootvetstvie: ot nablyudeniya do neznachitelnogo, sushchestvennogo i kriticheskogo.",
    },
}


# ── Localization ──────────────────────────────────────────────────────────


def _normalize_lang(lang: str | None) -> str:
    """Return a supported language code, defaulting to English.

    Accepts a full locale such as ``"de-DE"`` and keeps only the primary
    subtag. Anything unknown resolves to English.

    Args:
        lang: Requested language or locale code, or ``None``.

    Returns:
        One of :data:`SUPPORTED_LANGS`.
    """
    if not lang:
        return _FALLBACK_LANG
    primary = lang.replace("_", "-").split("-", 1)[0].strip().lower()
    return primary if primary in SUPPORTED_LANGS else _FALLBACK_LANG


def _localize(table: dict[str, dict[str, str]], key: str, lang: str | None) -> str:
    """Translate ``key`` via ``table`` with English then raw-key fallback.

    Args:
        table: Nested ``{lang: {key: word}}`` lookup.
        key: The canonical (English) key to translate.
        lang: Requested language or locale code.

    Returns:
        The localized word, or the English word, or ``key`` itself if the
        key is unknown in every language.
    """
    resolved = _normalize_lang(lang)
    localized = table.get(resolved, {}).get(key)
    if localized is not None:
        return localized
    return table.get(_FALLBACK_LANG, {}).get(key, key)


def localize_severity(severity: str, lang: str | None = "en") -> str:
    """Localize a severity word (en / de / ru), English fallback.

    Args:
        severity: Canonical severity such as ``"major"``.
        lang: Requested language or locale code; defaults to English.

    Returns:
        The severity word in the requested language, or the raw value if it
        is not a known severity.
    """
    return _localize(_SEVERITY_WORDS, severity, lang)


def localize_status(status: str, lang: str | None = "en") -> str:
    """Localize a status word (en / de / ru), English fallback.

    Args:
        status: Canonical status such as ``"action_pending"``.
        lang: Requested language or locale code; defaults to English.

    Returns:
        The status word in the requested language, or the raw value if it is
        not a known status.
    """
    return _localize(_STATUS_WORDS, status, lang)


def explain(concept: str, lang: str | None = "en") -> str:
    """Return a one-line, plain-language explanation of a quality concept.

    Known concepts: ``nonconformance``, ``inspection_pass_rate``,
    ``first_pass_yield``, ``open_vs_closed``, ``overdue``, ``severity``.

    Args:
        concept: Concept key to explain.
        lang: Requested language or locale code; defaults to English.

    Returns:
        A single sentence. Unknown concepts return an empty string rather
        than raising, so a UI tooltip never breaks the page.
    """
    entry = _GLOSSARY.get(concept)
    if entry is None:
        return ""
    resolved = _normalize_lang(lang)
    return entry.get(resolved) or entry.get(_FALLBACK_LANG, "")


# ── Rate math (all guarded, all explainable) ──────────────────────────────


def _require_non_negative(**values: int) -> None:
    """Raise :class:`ValueError` if any named count is negative.

    Args:
        **values: Named integer counts to check.

    Raises:
        ValueError: If any value is negative.
    """
    for name, value in values.items():
        if value < 0:
            raise ValueError(f"{name} must not be negative (got {value})")


def safe_ratio(numerator: int, denominator: int) -> float:
    """Divide two counts safely into a rate in ``[0.0, 1.0]``.

    Guards the two failure modes that would otherwise produce a 500 or a
    meaningless number: a zero denominator (returns ``0.0``, the defined
    empty-set value) and a numerator larger than the denominator (rejected,
    because a rate above 1 is never valid for these ratios).

    Args:
        numerator: Count of the subset (for example, passed inspections).
        denominator: Count of the whole set (for example, all inspections).

    Returns:
        ``numerator / denominator`` rounded to 6 places, or ``0.0`` when the
        denominator is zero.

    Raises:
        ValueError: If either count is negative, or the numerator exceeds
            the denominator.
    """
    _require_non_negative(numerator=numerator, denominator=denominator)
    if numerator > denominator:
        raise ValueError(
            f"numerator {numerator} cannot exceed denominator {denominator}",
        )
    if denominator == 0:
        return 0.0
    return round(numerator / denominator, 6)


def as_percent(rate: float) -> float:
    """Present a ``[0.0, 1.0]`` rate as a ``[0.0, 100.0]`` percentage.

    Args:
        rate: A dimensionless ratio in ``[0.0, 1.0]``.

    Returns:
        The same value scaled to a percentage, rounded to 4 places.

    Raises:
        ValueError: If ``rate`` is outside ``[0.0, 1.0]``.
    """
    if not (0.0 <= rate <= 1.0):
        raise ValueError(f"rate must be within [0.0, 1.0] (got {rate})")
    return round(rate * 100.0, 4)


def inspection_pass_rate(passed: int, total: int) -> dict[str, float | int]:
    """Compute the inspection pass rate with its components.

    Pass rate = inspections passed / inspections done. An empty set (no
    inspections) yields a defined ``0.0`` rather than an error.

    Args:
        passed: Number of inspections that passed.
        total: Number of inspections carried out.

    Returns:
        A dict with ``passed``, ``total``, ``rate`` (``[0,1]``) and
        ``percent`` (``[0,100]``) so the number is fully explainable.

    Raises:
        ValueError: If counts are negative or ``passed`` exceeds ``total``.
    """
    rate = safe_ratio(passed, total)
    return {
        "passed": passed,
        "total": total,
        "rate": rate,
        "percent": as_percent(rate),
    }


def first_pass_yield(passed_first_time: int, total: int) -> dict[str, float | int]:
    """Compute first-pass yield with its components.

    First-pass yield = inspections that passed on the first attempt / all
    inspections. An empty set yields a defined ``0.0``.

    Args:
        passed_first_time: Inspections that passed without any rework.
        total: All inspections carried out.

    Returns:
        A dict with ``passed_first_time``, ``total``, ``rate`` (``[0,1]``)
        and ``percent`` (``[0,100]``).

    Raises:
        ValueError: If counts are negative or the numerator exceeds
            ``total``.
    """
    rate = safe_ratio(passed_first_time, total)
    return {
        "passed_first_time": passed_first_time,
        "total": total,
        "rate": rate,
        "percent": as_percent(rate),
    }


def open_nonconformance_rate(
    open_count: int,
    total_count: int,
) -> dict[str, float | int]:
    """Compute the open-nonconformance rate with its components.

    Open rate = open nonconformances / all nonconformances. A project with
    no nonconformances yields a defined ``0.0`` (nothing is open).

    Args:
        open_count: Number of nonconformances still open.
        total_count: Number of nonconformances raised in scope.

    Returns:
        A dict with ``open``, ``total``, ``closed`` (derived), ``rate``
        (``[0,1]``) and ``percent`` (``[0,100]``).

    Raises:
        ValueError: If counts are negative or ``open_count`` exceeds
            ``total_count``.
    """
    rate = safe_ratio(open_count, total_count)
    return {
        "open": open_count,
        "closed": total_count - open_count,
        "total": total_count,
        "rate": rate,
        "percent": as_percent(rate),
    }


def counts_by_status(statuses: Iterable[str]) -> dict[str, int]:
    """Tally how many items sit in each status.

    Args:
        statuses: An iterable of status strings (any vocabulary).

    Returns:
        A dict mapping each seen status to its count. An empty input yields
        an empty dict, never an error.
    """
    tally: dict[str, int] = {}
    for status in statuses:
        tally[status] = tally.get(status, 0) + 1
    return tally


def counts_by_severity(severities: Iterable[str]) -> dict[str, int]:
    """Tally how many items sit at each severity, in severity order.

    Known severities (:data:`SEVERITY_ORDER`) always appear as keys, even
    with a count of zero, so a dashboard has a stable set of bars. Unknown
    severities are appended after the known ones.

    Args:
        severities: An iterable of severity strings.

    Returns:
        A dict mapping each severity to its count, known severities first.
    """
    tally: dict[str, int] = dict.fromkeys(SEVERITY_ORDER, 0)
    for severity in severities:
        tally[severity] = tally.get(severity, 0) + 1
    return tally


# ── Overdue check (ISO 8601 in, boolean out) ──────────────────────────────


def _coerce_date(value: str | date) -> date:
    """Parse an ISO 8601 date, or pass a ``date`` through unchanged.

    Accepts a bare ``YYYY-MM-DD`` string or the date part of an ISO 8601
    datetime (for example ``2026-07-05T10:00:00+00:00``).

    Args:
        value: A ``date`` or an ISO 8601 date/datetime string.

    Returns:
        The corresponding :class:`datetime.date`.

    Raises:
        ValueError: If a string is not valid ISO 8601.
    """
    if isinstance(value, date):
        return value
    text = value.strip()
    # Keep only the date part so an ISO datetime string is accepted too.
    date_part = text.split("T", 1)[0]
    try:
        return date.fromisoformat(date_part)
    except ValueError as exc:
        raise ValueError(
            f"due date must be ISO 8601 (YYYY-MM-DD); got {value!r}",
        ) from exc


def is_overdue(
    due_date: str | date | None,
    *,
    as_of: str | date | None = None,
    is_closed: bool = False,
    grace_days: int = 0,
) -> bool:
    """Return whether an item is overdue against its due date.

    An item is overdue when it is still open and ``as_of`` is later than the
    due date plus a grace window. Dates are ISO 8601. A closed item is never
    overdue, and a missing due date is never overdue (nothing to breach).

    Args:
        due_date: The due date as ISO 8601 or a ``date``; ``None`` means no
            deadline, so the item is never overdue.
        as_of: The reference "today" as ISO 8601 or a ``date``; defaults to
            the current UTC date.
        is_closed: Whether the item is already resolved. Closed items are
            never overdue.
        grace_days: Documented threshold. Days of grace allowed after the
            due date before the item counts as overdue. Defaults to ``0``
            (overdue the first day past due). Must not be negative.

    Returns:
        ``True`` if the item is overdue, else ``False``.

    Raises:
        ValueError: If ``grace_days`` is negative or a date string is not
            valid ISO 8601.
    """
    if grace_days < 0:
        raise ValueError(f"grace_days must not be negative (got {grace_days})")
    if is_closed or due_date is None:
        return False
    due = _coerce_date(due_date)
    reference = _coerce_date(as_of) if as_of is not None else _utc_today()
    return (reference - due).days > grace_days


def overdue_days(
    due_date: str | date,
    *,
    as_of: str | date | None = None,
) -> int:
    """Return how many days past due an item is (never negative).

    Args:
        due_date: The due date as ISO 8601 or a ``date``.
        as_of: The reference "today"; defaults to the current UTC date.

    Returns:
        Whole days elapsed since the due date, clamped to ``0`` for items
        that are not yet due.

    Raises:
        ValueError: If a date string is not valid ISO 8601.
    """
    due = _coerce_date(due_date)
    reference = _coerce_date(as_of) if as_of is not None else _utc_today()
    return max(0, (reference - due).days)


def _utc_today() -> date:
    """Return the current date in UTC.

    Isolated so the module stays locale- and timezone-independent: "today"
    is always the UTC calendar date, not the server's local date.

    Returns:
        Today's UTC :class:`datetime.date`.
    """
    from datetime import UTC, datetime

    return datetime.now(UTC).date()
