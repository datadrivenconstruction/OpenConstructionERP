# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""International, locale-safe helpers for the Punch List module.

This file is deliberately pure and dependency-free (standard library only).
It holds the maths and plain-language wording that a punch list needs to be
clear and correct for construction teams anywhere in the world:

* No hardcoded locale. Dates are formatted as ISO 8601. The overdue check
  takes an explicit reference date and an explicit grace threshold, so there
  is no hidden "server today" or "local timezone" assumption.
* Rates are ratios, never money. ``completion_rate`` returns a value in
  ``[0.0, 1.0]`` (or ``[0.0, 100.0]`` as a percentage), never a currency
  amount and never ``NaN`` or ``inf``.
* Every derived number exposes its components (closed, open, total) so the
  result can be explained in the UI rather than trusted blindly.
* Status and severity words are translated for English, German and Russian
  with a safe fall-back to the raw code, so a missing translation never
  crashes and never shows a blank.

Nothing here touches the database or the network, which is why the whole
file is exercised by fast, DB-free unit tests.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import datetime

from app.core.i18n import catalogue_table

# ── Vocabulary ───────────────────────────────────────────────────────────
#
# The canonical status and severity codes are the single source of truth for
# labels below. They mirror the finite-state machine in ``service.py`` and the
# priority pattern in ``schemas.py``. ``reopened`` is only ever a client-facing
# alias for ``open`` and is normalised away before counting or labelling.

STATUS_CODES: tuple[str, ...] = (
    "open",
    "assigned",
    "in_progress",
    "resolved",
    "verified",
    "closed",
)

SEVERITY_CODES: tuple[str, ...] = ("low", "medium", "high", "critical")

# Statuses that count as "done" for completion and overdue maths. A verified
# or closed item no longer needs work, so it is complete and cannot be overdue.
# This mirrors the open/closed split used by the PDF cover page in service.py.
DONE_STATUSES: frozenset[str] = frozenset({"verified", "closed"})

# Severity ranking, low to high, so a mixed set can report its worst item.
SEVERITY_RANK: dict[str, int] = {code: rank for rank, code in enumerate(SEVERITY_CODES)}

# Default UI language when the caller does not pass one. English is the
# guaranteed-complete fall-back for every label lookup.
DEFAULT_LOCALE: str = "en"

# ── Translations (en / de / ru, English fall-back) ───────────────────────

_STATUS_LABELS: dict[str, dict[str, str]] = catalogue_table(
    "punchlist.intl.status_labels", ("open", "assigned", "in_progress", "resolved", "verified", "closed")
)

_SEVERITY_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "low": "Low",
        "medium": "Medium",
        "high": "High",
        "critical": "Critical",
    },
    "de": {
        "low": "Niedrig",
        "medium": "Mittel",
        "high": "Hoch",
        "critical": "Kritisch",
    },
    "ru": {
        "low": "Низкий",
        "medium": "Средний",
        "high": "Высокий",
        "critical": "Критический",
    },
}


def _normalise_status(status: str) -> str:
    """Return the canonical status code, folding the ``reopened`` alias to ``open``.

    Args:
        status: A raw status string, possibly the ``reopened`` UI alias, in any
            letter case with surrounding whitespace.

    Returns:
        The trimmed, lower-cased status code with ``reopened`` mapped to ``open``.
    """
    code = (status or "").strip().lower()
    return "open" if code == "reopened" else code


def _pick_locale(locale: str | None, table: Mapping[str, Mapping[str, str]]) -> str:
    """Choose a supported locale, falling back to English.

    Args:
        locale: Requested locale, for example ``"de"`` or ``"de-DE"``. May be
            ``None``.
        table: Translation table keyed by locale.

    Returns:
        A locale key that exists in ``table``; ``DEFAULT_LOCALE`` when the
        request is missing or unsupported.
    """
    if not locale:
        return DEFAULT_LOCALE
    key = locale.strip().lower()
    if key in table:
        return key
    # Accept region-tagged locales such as "de-DE" or "ru_RU".
    base = key.replace("_", "-").split("-", 1)[0]
    return base if base in table else DEFAULT_LOCALE


def localize_status(status: str, locale: str | None = None) -> str:
    """Translate a punch item status into a plain human word.

    Args:
        status: A status code (or the ``reopened`` alias).
        locale: Target locale (``"en"``, ``"de"``, ``"ru"``). Unsupported or
            missing locales fall back to English, and an unknown status falls
            back to a readable form of the raw code.

    Returns:
        The localized label, for example ``"In progress"`` or ``"In Bearbeitung"``.
    """
    code = _normalise_status(status)
    lang = _pick_locale(locale, _STATUS_LABELS)
    table = _STATUS_LABELS[lang]
    if code in table:
        return table[code]
    # Unknown status: never blank, never a crash. Show a tidy version of the code.
    english = _STATUS_LABELS["en"].get(code)
    return english if english else code.replace("_", " ").strip() or code


def localize_severity(severity: str, locale: str | None = None) -> str:
    """Translate a punch item severity (priority) into a plain human word.

    Args:
        severity: A severity code such as ``"high"`` or ``"critical"``.
        locale: Target locale (``"en"``, ``"de"``, ``"ru"``). Unsupported or
            missing locales fall back to English, and an unknown severity falls
            back to the raw code.

    Returns:
        The localized label, for example ``"Critical"`` or ``"Kritisch"``.
    """
    code = (severity or "").strip().lower()
    lang = _pick_locale(locale, _SEVERITY_LABELS)
    table = _SEVERITY_LABELS[lang]
    if code in table:
        return table[code]
    english = _SEVERITY_LABELS["en"].get(code)
    return english if english else code.replace("_", " ").strip() or code


# ── Dates: ISO 8601 only ─────────────────────────────────────────────────


def _coerce_datetime(value: datetime | str) -> datetime:
    """Parse a value into a ``datetime`` without assuming any locale.

    Args:
        value: A ``datetime`` or an ISO 8601 string. A trailing ``Z`` is
            accepted as UTC.

    Returns:
        The parsed ``datetime``.

    Raises:
        ValueError: If a string cannot be parsed as ISO 8601, or the type is
            unsupported.
    """
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(f"date must be ISO 8601, got {value!r}") from exc
    raise ValueError(f"date must be a datetime or ISO 8601 string, got {type(value).__name__}")


def _align_tzinfo(a: datetime, b: datetime) -> tuple[datetime, datetime]:
    """Make two datetimes comparable when one is naive and the other aware.

    A naive value is treated as sharing the aware value's timezone. When both
    are naive or both aware they are returned unchanged.

    Args:
        a: First datetime.
        b: Second datetime.

    Returns:
        The pair, adjusted so a direct comparison never raises.
    """
    if a.tzinfo is None and b.tzinfo is not None:
        return a.replace(tzinfo=b.tzinfo), b
    if b.tzinfo is None and a.tzinfo is not None:
        return a, b.replace(tzinfo=a.tzinfo)
    return a, b


def to_iso_date(value: datetime | str | None) -> str | None:
    """Return the ISO 8601 rendering of a date, or ``None`` when absent.

    Args:
        value: A ``datetime``, an ISO 8601 string, or ``None``.

    Returns:
        The ISO 8601 string (unchanged for valid string input), or ``None``.

    Raises:
        ValueError: If a non-empty string is not valid ISO 8601.
    """
    if value is None:
        return None
    return _coerce_datetime(value).isoformat()


def is_overdue(
    due_date: datetime | str | None,
    reference_date: datetime | str,
    *,
    status: str | None = None,
    done_statuses: Iterable[str] = DONE_STATUSES,
    grace_days: float = 0.0,
) -> bool:
    """Decide whether an item is overdue, with no hidden locale or clock.

    An item is overdue when it still needs work and its due date, extended by
    an explicit grace period, is strictly before the given reference date.
    A missing due date is never overdue, and a done item is never overdue.

    Args:
        due_date: The item's due date, or ``None`` when it has none.
        reference_date: The date to compare against ("today" is the caller's
            choice, passed in explicitly for testability and timezone safety).
        status: The item's status. When it is a done status the item is not
            overdue regardless of the dates.
        done_statuses: Statuses that count as done. Defaults to verified/closed.
        grace_days: Days of slack added to the due date before it counts as
            overdue. Must be a finite number (may be negative to be stricter).

    Returns:
        ``True`` if overdue, otherwise ``False``.

    Raises:
        ValueError: If ``grace_days`` is not finite, or a date string is not
            valid ISO 8601.
    """
    if not math.isfinite(grace_days):
        raise ValueError("grace_days must be a finite number")
    if due_date is None:
        return False
    if status is not None:
        done = {_normalise_status(s) for s in done_statuses}
        if _normalise_status(status) in done:
            return False

    due = _coerce_datetime(due_date)
    ref = _coerce_datetime(reference_date)
    due, ref = _align_tzinfo(due, ref)
    # timedelta from a finite float of days is always representable here.
    from datetime import timedelta

    deadline = due + timedelta(days=grace_days)
    return ref > deadline


# ── Rates and counts (ratios, never money; guarded against zero) ─────────


def completion_rate(closed: int, total: int, *, as_percent: bool = False) -> float:
    """Completion rate as ``closed / total``, guarded against division by zero.

    The result is a pure ratio, not a currency value. An empty punch list
    (``total == 0``) is defined as ``0.0`` rather than an error, so a fresh
    project shows 0% complete instead of crashing.

    Args:
        closed: Number of completed (done) items. Must be non-negative.
        total: Total number of items. Must be non-negative and not less than
            ``closed``.
        as_percent: When ``True`` return a value in ``[0.0, 100.0]``; otherwise
            a value in ``[0.0, 1.0]``.

    Returns:
        The completion rate, clamped to its valid range, never ``NaN``/``inf``.

    Raises:
        ValueError: If a count is negative or ``closed`` exceeds ``total``.
    """
    if closed < 0 or total < 0:
        raise ValueError("counts must be non-negative")
    if closed > total:
        raise ValueError("closed cannot exceed total")
    if total == 0:
        return 0.0
    ratio = closed / total
    # Guard the boundary against any float drift so the range invariant holds.
    ratio = min(1.0, max(0.0, ratio))
    return ratio * 100.0 if as_percent else ratio


def counts_by_status(statuses: Iterable[str], *, include_all: bool = False) -> dict[str, int]:
    """Tally how many items sit in each status.

    Args:
        statuses: An iterable of status codes (the ``reopened`` alias is folded
            into ``open``).
        include_all: When ``True`` every known status appears, with ``0`` for
            statuses that have no items. When ``False`` only present statuses
            appear.

    Returns:
        A mapping of status code to count.
    """
    tally = Counter(_normalise_status(s) for s in statuses)
    if include_all:
        return {code: tally.get(code, 0) for code in STATUS_CODES}
    return dict(tally)


def counts_by_severity(severities: Iterable[str], *, include_all: bool = False) -> dict[str, int]:
    """Tally how many items sit at each severity (priority).

    Args:
        severities: An iterable of severity codes.
        include_all: When ``True`` every known severity appears, with ``0`` for
            severities that have no items. When ``False`` only present
            severities appear.

    Returns:
        A mapping of severity code to count.
    """
    tally = Counter((s or "").strip().lower() for s in severities)
    if include_all:
        return {code: tally.get(code, 0) for code in SEVERITY_CODES}
    return dict(tally)


def open_vs_closed(statuses: Iterable[str], *, done_statuses: Iterable[str] = DONE_STATUSES) -> dict[str, int]:
    """Split a set of statuses into open and closed (done) counts.

    Args:
        statuses: An iterable of status codes.
        done_statuses: Statuses that count as closed/done. Defaults to
            verified/closed.

    Returns:
        A mapping with ``open``, ``closed`` and ``total`` counts. ``open`` plus
        ``closed`` always equals ``total``.
    """
    done = {_normalise_status(s) for s in done_statuses}
    total = 0
    closed = 0
    for raw in statuses:
        total += 1
        if _normalise_status(raw) in done:
            closed += 1
    return {"open": total - closed, "closed": closed, "total": total}


def highest_severity(severities: Iterable[str]) -> str | None:
    """Return the worst severity present, or ``None`` when the set is empty.

    Unknown severity codes are ignored rather than ranked, so a typo never
    masquerades as the most critical item.

    Args:
        severities: An iterable of severity codes.

    Returns:
        The highest-ranked known severity code, or ``None`` if none are known.
    """
    worst: str | None = None
    worst_rank = -1
    for raw in severities:
        code = (raw or "").strip().lower()
        rank = SEVERITY_RANK.get(code, -1)
        if rank > worst_rank:
            worst_rank = rank
            worst = code
    return worst


def completion_breakdown(statuses: Iterable[str], *, done_statuses: Iterable[str] = DONE_STATUSES) -> dict[str, float]:
    """Compute a completion summary that exposes all of its components.

    This is the explainable form of :func:`completion_rate`: instead of a bare
    number it returns the counts the rate is derived from, so the UI can show
    "12 of 20 done (60%)" rather than an unexplained percentage.

    Args:
        statuses: An iterable of status codes.
        done_statuses: Statuses that count as done. Defaults to verified/closed.

    Returns:
        A mapping with integer ``total``, ``closed`` and ``open`` counts plus
        the float ``rate`` in ``[0, 1]`` and ``rate_percent`` in ``[0, 100]``.
    """
    split = open_vs_closed(statuses, done_statuses=done_statuses)
    rate = completion_rate(split["closed"], split["total"])
    return {
        "total": split["total"],
        "closed": split["closed"],
        "open": split["open"],
        "rate": rate,
        "rate_percent": rate * 100.0,
    }


# ── One-line, plain-language explainers ──────────────────────────────────


def explain_item(*, title: str, status: str, severity: str, locale: str | None = None) -> str:
    """One sentence describing what a punch item is and where it stands.

    Args:
        title: The item's short title.
        status: Its status code.
        severity: Its severity (priority) code.
        locale: Locale for the status and severity words. The framing sentence
            stays in English so it reads the same everywhere.

    Returns:
        A single plain-language line such as
        ``"'Cracked wall' is a High-severity item, currently Open."``
    """
    clean_title = (title or "").strip() or "Untitled item"
    sev = localize_severity(severity, locale)
    sta = localize_status(status, locale)
    return f"'{clean_title}' is a {sev}-severity item, currently {sta}."


def explain_completion_rate(closed: int, total: int) -> str:
    """One sentence explaining a completion rate and how it was derived.

    Args:
        closed: Number of done items.
        total: Total number of items.

    Returns:
        A plain-language line, for example
        ``"12 of 20 items are done, a completion rate of 60.0%."`` An empty
        list is reported honestly as having nothing to complete.
    """
    if total <= 0:
        return "No items yet, so there is nothing to complete (0.0%)."
    percent = completion_rate(closed, total, as_percent=True)
    return f"{closed} of {total} items are done, a completion rate of {percent:.1f}%."


def explain_open_vs_closed(statuses: Iterable[str], *, done_statuses: Iterable[str] = DONE_STATUSES) -> str:
    """One sentence contrasting how many items are still open versus done.

    Args:
        statuses: An iterable of status codes.
        done_statuses: Statuses that count as done. Defaults to verified/closed.

    Returns:
        A plain-language line such as ``"8 open, 12 done, out of 20 total."``
    """
    split = open_vs_closed(statuses, done_statuses=done_statuses)
    return f"{split['open']} open, {split['closed']} done, out of {split['total']} total."


def explain_overdue(
    due_date: datetime | str | None,
    reference_date: datetime | str,
    *,
    status: str | None = None,
    grace_days: float = 0.0,
) -> str:
    """One sentence explaining whether an item is overdue and against what date.

    Args:
        due_date: The item's due date, or ``None``.
        reference_date: The date treated as "now" for the comparison.
        status: The item's status; a done item is reported as not overdue.
        grace_days: Slack added to the due date before it counts as overdue.

    Returns:
        A plain-language line naming the ISO date it was measured against.
    """
    if due_date is None:
        return "No due date is set, so this item cannot be overdue."
    overdue = is_overdue(due_date, reference_date, status=status, grace_days=grace_days)
    due_iso = to_iso_date(due_date)
    ref_iso = to_iso_date(reference_date)
    state = "overdue" if overdue else "on time"
    return f"Due {due_iso}, measured against {ref_iso}: {state}."
