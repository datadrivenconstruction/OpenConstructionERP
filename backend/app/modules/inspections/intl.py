# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""International, locale-safe helpers for the Inspections module.

This file is deliberately pure and dependency-free (standard library only).
It holds the maths and plain-language wording that quality and site inspections
need to be clear and correct for construction teams anywhere in the world:

* No hardcoded locale. Dates are formatted as ISO 8601. The overdue check for a
  re-inspection takes an explicit reference date and an explicit SLA window, so
  there is no hidden "server today" or "local timezone" assumption.
* Rates are ratios, never money. ``pass_rate`` returns a value in ``[0.0, 1.0]``
  (or ``[0.0, 100.0]`` as a percentage), never a currency amount and never
  ``NaN`` or ``inf``. ``defect_density`` returns a non-negative count per
  inspection, guarded against division by zero.
* Every derived number exposes its components (passed, evaluated, total, and so
  on) so the result can be explained in the UI rather than trusted blindly.
* Status and result words are translated for English, German and Russian with a
  safe fall-back to the raw code, so a missing translation never crashes and
  never shows a blank.

Nothing here touches the database or the network, which is why the whole file
is exercised by fast, DB-free unit tests. It only adds new helpers; it does not
change any existing service, schema or route signature.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta

from app.core.i18n import catalogue_table

# ── Vocabulary ───────────────────────────────────────────────────────────
#
# The canonical status and result codes are the single source of truth for the
# labels below. They mirror the finite-state machine in ``service.py``
# (_INSPECTION_STATUS_TRANSITIONS) and the ``result`` pattern in ``schemas.py``.

STATUS_CODES: tuple[str, ...] = (
    "scheduled",
    "in_progress",
    "completed",
    "failed",
    "cancelled",
)

RESULT_CODES: tuple[str, ...] = ("pass", "fail", "partial")

# Results that leave defects behind and therefore call for corrective work and a
# re-inspection. A clean ``pass`` never needs one. This mirrors the
# fail/partial branch that drives the punchlist/NCR flow in service.py/router.py.
REINSPECTION_RESULTS: frozenset[str] = frozenset({"fail", "partial"})

# Default UI language when the caller does not pass one. English is the
# guaranteed-complete fall-back for every label lookup.
DEFAULT_LOCALE: str = "en"

# ── Translations (en / de / ru, English fall-back) ───────────────────────

_STATUS_LABELS: dict[str, dict[str, str]] = catalogue_table(
    "inspections.intl.status_labels", ("scheduled", "in_progress", "completed", "failed", "cancelled")
)

_RESULT_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "pass": "Pass",
        "fail": "Fail",
        "partial": "Partial",
    },
    "de": {
        "pass": "Bestanden",
        "fail": "Durchgefallen",
        "partial": "Teilweise bestanden",
    },
    "ru": {
        "pass": "Пройдена",
        "fail": "Не пройдена",
        "partial": "Частично",
    },
}


def _clean_code(code: str | None) -> str:
    """Return a trimmed, lower-cased code, or an empty string for ``None``.

    Args:
        code: A raw status or result string in any letter case with surrounding
            whitespace, or ``None``.

    Returns:
        The normalised code, safe to use as a dictionary key.
    """
    return (code or "").strip().lower()


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


def _localize(code: str | None, locale: str | None, table: Mapping[str, Mapping[str, str]]) -> str:
    """Translate a code via ``table``, never blank and never raising.

    Args:
        code: The status or result code to translate.
        locale: Target locale; unsupported or missing locales fall back to
            English.
        table: The label table to read from.

    Returns:
        The localized label, the English label, or a tidy version of the raw
        code as a last resort.
    """
    clean = _clean_code(code)
    lang = _pick_locale(locale, table)
    localized = table[lang].get(clean)
    if localized:
        return localized
    english = table["en"].get(clean)
    return english if english else clean.replace("_", " ").strip() or clean


def localize_status(status: str, locale: str | None = None) -> str:
    """Translate an inspection status into a plain human word.

    Args:
        status: A status code such as ``"in_progress"`` or ``"completed"``.
        locale: Target locale (``"en"``, ``"de"``, ``"ru"``). Unsupported or
            missing locales fall back to English, and an unknown status falls
            back to a readable form of the raw code.

    Returns:
        The localized label, for example ``"In progress"`` or ``"In Bearbeitung"``.
    """
    return _localize(status, locale, _STATUS_LABELS)


def localize_result(result: str, locale: str | None = None) -> str:
    """Translate an inspection result into a plain human word.

    Args:
        result: A result code (``"pass"``, ``"fail"`` or ``"partial"``).
        locale: Target locale (``"en"``, ``"de"``, ``"ru"``). Unsupported or
            missing locales fall back to English, and an unknown result falls
            back to the raw code.

    Returns:
        The localized label, for example ``"Pass"`` or ``"Bestanden"``.
    """
    return _localize(result, locale, _RESULT_LABELS)


# ── Dates: ISO 8601 only ─────────────────────────────────────────────────


def _coerce_datetime(value: datetime | str) -> datetime:
    """Parse a value into a ``datetime`` without assuming any locale.

    Args:
        value: A ``datetime`` or an ISO 8601 string. A trailing ``Z`` is
            accepted as UTC, and a plain ``YYYY-MM-DD`` date is accepted.

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
        The ISO 8601 string, or ``None``.

    Raises:
        ValueError: If a non-empty string is not valid ISO 8601.
    """
    if value is None:
        return None
    return _coerce_datetime(value).isoformat()


def reinspection_due_date(failed_on: datetime | str, *, sla_days: float) -> str:
    """Return the ISO 8601 date by which a re-inspection is due.

    The due date is the failure date plus the re-inspection SLA window. The SLA
    is always an explicit parameter, so a project in any country can set its own
    turnaround (for example 7 days) without touching this code.

    Args:
        failed_on: When the inspection failed (a ``datetime`` or ISO 8601 string).
        sla_days: Days allowed to close out the re-inspection. Must be a finite,
            non-negative number.

    Returns:
        The ISO 8601 due date.

    Raises:
        ValueError: If ``sla_days`` is negative or not finite, or the date is not
            valid ISO 8601.
    """
    if not math.isfinite(sla_days):
        raise ValueError("sla_days must be a finite number")
    if sla_days < 0:
        raise ValueError("sla_days must be non-negative")
    due = _coerce_datetime(failed_on) + timedelta(days=sla_days)
    return due.isoformat()


def is_reinspection_overdue(
    due_date: datetime | str | None,
    reference_date: datetime | str,
    *,
    result: str | None = None,
    resolved: bool = False,
    sla_days: float = 0.0,
) -> bool:
    """Decide whether a re-inspection is overdue, with no hidden locale or clock.

    A re-inspection is overdue when the original inspection left defects behind
    (a ``fail`` or ``partial`` result), it has not been resolved yet, and its due
    date, extended by the SLA window, is strictly before the reference date. A
    missing due date is never overdue, a clean pass never needs a re-inspection,
    and an already resolved one is never overdue.

    Args:
        due_date: The date the re-inspection is due, or ``None`` when none is set.
        reference_date: The date to compare against ("today" is the caller's
            choice, passed in explicitly for testability and timezone safety).
        result: The original inspection result. When it is not ``fail`` or
            ``partial`` no re-inspection is owed, so the answer is ``False``.
        resolved: When ``True`` the re-inspection is done, so it is not overdue.
        sla_days: Extra SLA slack added to the due date before it counts as
            overdue. Must be finite (may be negative to be stricter).

    Returns:
        ``True`` if the re-inspection is overdue, otherwise ``False``.

    Raises:
        ValueError: If ``sla_days`` is not finite, or a date string is not valid
            ISO 8601.
    """
    if not math.isfinite(sla_days):
        raise ValueError("sla_days must be a finite number")
    if due_date is None or resolved:
        return False
    if result is not None and _clean_code(result) not in REINSPECTION_RESULTS:
        return False

    due = _coerce_datetime(due_date)
    ref = _coerce_datetime(reference_date)
    due, ref = _align_tzinfo(due, ref)
    deadline = due + timedelta(days=sla_days)
    return ref > deadline


# ── Rates and counts (ratios, never money; guarded against zero) ─────────


def pass_rate(passed: int, evaluated: int, *, as_percent: bool = False) -> float:
    """Pass rate as ``passed / evaluated``, guarded against division by zero.

    The result is a pure ratio, not a currency value. "Evaluated" means
    inspections that reached a result (pass, fail or partial); a project with no
    evaluated inspections is defined as ``0.0`` rather than an error, so a fresh
    project shows 0% instead of crashing.

    Args:
        passed: Number of inspections with a ``pass`` result. Must be
            non-negative.
        evaluated: Number of inspections that reached any result. Must be
            non-negative and not less than ``passed``.
        as_percent: When ``True`` return a value in ``[0.0, 100.0]``; otherwise a
            value in ``[0.0, 1.0]``.

    Returns:
        The pass rate, clamped to its valid range, never ``NaN``/``inf``.

    Raises:
        ValueError: If a count is negative or ``passed`` exceeds ``evaluated``.
    """
    if passed < 0 or evaluated < 0:
        raise ValueError("counts must be non-negative")
    if passed > evaluated:
        raise ValueError("passed cannot exceed evaluated")
    if evaluated == 0:
        return 0.0
    ratio = passed / evaluated
    # Guard the boundary against any float drift so the range invariant holds.
    ratio = min(1.0, max(0.0, ratio))
    return ratio * 100.0 if as_percent else ratio


def defect_density(defects: int, inspections: int) -> float:
    """Defects per inspection as ``defects / inspections``, zero-guarded.

    This is a non-negative count, not a ratio bounded at 1: a single inspection
    can raise several defects. With no inspections the density is defined as
    ``0.0`` rather than an error, so an empty project never divides by zero.

    Args:
        defects: Total number of defects raised. Must be non-negative.
        inspections: Number of inspections the defects came from. Must be
            non-negative.

    Returns:
        The defect density, always finite and ``>= 0.0``.

    Raises:
        ValueError: If a count is negative.
    """
    if defects < 0 or inspections < 0:
        raise ValueError("counts must be non-negative")
    if inspections == 0:
        return 0.0
    return defects / inspections


def counts_by_status(statuses: Iterable[str], *, include_all: bool = False) -> dict[str, int]:
    """Tally how many inspections sit in each status.

    Args:
        statuses: An iterable of status codes.
        include_all: When ``True`` every known status appears, with ``0`` for
            statuses that have no inspections. When ``False`` only present
            statuses appear.

    Returns:
        A mapping of status code to count.
    """
    tally = Counter(_clean_code(s) for s in statuses)
    if include_all:
        return {code: tally.get(code, 0) for code in STATUS_CODES}
    return dict(tally)


def counts_by_result(results: Iterable[str | None], *, include_all: bool = False) -> dict[str, int]:
    """Tally how many inspections reached each result.

    Inspections without a result yet (``None`` or blank) are skipped, so the
    tally only reflects evaluated inspections.

    Args:
        results: An iterable of result codes, possibly containing ``None`` for
            inspections not yet evaluated.
        include_all: When ``True`` every known result appears, with ``0`` for
            results that have no inspections. When ``False`` only present results
            appear.

    Returns:
        A mapping of result code to count.
    """
    tally = Counter(_clean_code(r) for r in results if _clean_code(r))
    if include_all:
        return {code: tally.get(code, 0) for code in RESULT_CODES}
    return dict(tally)


def pass_rate_breakdown(results: Iterable[str | None]) -> dict[str, float]:
    """Compute a pass-rate summary that exposes all of its components.

    This is the explainable form of :func:`pass_rate`: instead of a bare number
    it returns the counts the rate is derived from, so the UI can show "8 of 10
    evaluated passed (80%)" rather than an unexplained percentage. Inspections
    with no result yet are counted under ``pending`` and excluded from the rate.

    Args:
        results: An iterable of result codes, possibly containing ``None``.

    Returns:
        A mapping with integer ``total``, ``evaluated``, ``passed``, ``failed``,
        ``partial`` and ``pending`` counts plus the float ``rate`` in ``[0, 1]``
        and ``rate_percent`` in ``[0, 100]``.
    """
    total = 0
    passed = 0
    failed = 0
    partial = 0
    pending = 0
    for raw in results:
        total += 1
        code = _clean_code(raw)
        if code == "pass":
            passed += 1
        elif code == "fail":
            failed += 1
        elif code == "partial":
            partial += 1
        else:
            pending += 1
    evaluated = passed + failed + partial
    rate = pass_rate(passed, evaluated)
    return {
        "total": total,
        "evaluated": evaluated,
        "passed": passed,
        "failed": failed,
        "partial": partial,
        "pending": pending,
        "rate": rate,
        "rate_percent": rate * 100.0,
    }


# ── One-line, plain-language explainers ──────────────────────────────────


def explain_pass_rate(passed: int, evaluated: int) -> str:
    """One sentence explaining a pass rate and how it was derived.

    Args:
        passed: Number of inspections that passed.
        evaluated: Number of inspections that reached a result.

    Returns:
        A plain-language line, for example
        ``"8 of 10 evaluated inspections passed, a pass rate of 80.0%."`` A set
        with nothing evaluated yet is reported honestly.
    """
    if evaluated <= 0:
        return "No inspections have a result yet, so there is no pass rate (0.0%)."
    percent = pass_rate(passed, evaluated, as_percent=True)
    return f"{passed} of {evaluated} evaluated inspections passed, a pass rate of {percent:.1f}%."


def explain_defect_density(defects: int, inspections: int) -> str:
    """One sentence explaining defect density and how it was derived.

    Args:
        defects: Total number of defects raised.
        inspections: Number of inspections they came from.

    Returns:
        A plain-language line, for example
        ``"12 defects across 4 inspections, an average of 3.00 per inspection."``
        An empty set is reported honestly.
    """
    if inspections <= 0:
        return "No inspections yet, so defect density cannot be measured (0.00 per inspection)."
    density = defect_density(defects, inspections)
    return f"{defects} defects across {inspections} inspections, an average of {density:.2f} per inspection."


def explain_result(*, title: str, status: str, result: str | None = None, locale: str | None = None) -> str:
    """One sentence describing an inspection and where it stands.

    Args:
        title: The inspection's short title.
        status: Its status code.
        result: Its result code, or ``None`` when not evaluated yet.
        locale: Locale for the status and result words. The framing sentence
            stays in English so it reads the same everywhere.

    Returns:
        A single plain-language line such as
        ``"'Foundation pour' is Completed with a result of Pass."`` or, when
        there is no result yet, ``"'Foundation pour' is Scheduled, not yet
        evaluated."``
    """
    clean_title = (title or "").strip() or "Untitled inspection"
    sta = localize_status(status, locale)
    if _clean_code(result):
        res = localize_result(result or "", locale)
        return f"'{clean_title}' is {sta} with a result of {res}."
    return f"'{clean_title}' is {sta}, not yet evaluated."


def explain_reinspection_overdue(
    due_date: datetime | str | None,
    reference_date: datetime | str,
    *,
    result: str | None = None,
    resolved: bool = False,
    sla_days: float = 0.0,
) -> str:
    """One sentence explaining whether a re-inspection is overdue and against what date.

    Args:
        due_date: The date the re-inspection is due, or ``None``.
        reference_date: The date treated as "now" for the comparison.
        result: The original inspection result; a clean pass needs no
            re-inspection.
        resolved: When ``True`` the re-inspection is already done.
        sla_days: SLA slack added to the due date before it counts as overdue.

    Returns:
        A plain-language line naming the ISO date it was measured against.
    """
    if result is not None and _clean_code(result) not in REINSPECTION_RESULTS:
        return "This inspection passed, so no re-inspection is required."
    if resolved:
        return "The re-inspection is already done, so it is not overdue."
    if due_date is None:
        return "No re-inspection due date is set, so it cannot be overdue."
    overdue = is_reinspection_overdue(
        due_date,
        reference_date,
        result=result,
        resolved=resolved,
        sla_days=sla_days,
    )
    due_iso = to_iso_date(due_date)
    ref_iso = to_iso_date(reference_date)
    state = "overdue" if overdue else "on time"
    return f"Re-inspection due {due_iso}, measured against {ref_iso}: {state}."
