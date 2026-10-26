# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""International, framework-free approval-routing helpers.

Small, side-effect-free helpers that make multi-step approval reporting correct
and clear for users anywhere in the world. There is no database, no FastAPI and
no third-party dependency here, so this module imports and runs the same in a
unit test as it does in the request path. It sits beside the other pure engines
in this module (:mod:`sla_engine`, :mod:`escalation`, :mod:`delegation_engine`)
and follows the same rules.

Design rules that keep the platform usable worldwide:

* No hardcoded locale. Decision and status words are localised (English,
  German, Russian) with an English fallback, so an operator reads plain
  language, never a raw code, whatever their language.
* Dates are ISO 8601 (``YYYY-MM-DD``). A "days" threshold such as an SLA grace
  period is always an explicit parameter, never a buried constant, so a team in
  any jurisdiction sets its own service level.
* Every rate stays in a defined range. A completion rate is a ``Decimal`` in
  ``[0, 1]`` (and ``[0, 100]`` as a percentage), guarded against division by
  zero, so it can never become a ``NaN`` or an infinity.
* Bad input (negative counts, more completed steps than exist, a garbage date)
  is turned into a clear ``ValueError`` or a well-defined value. It never
  becomes a 500, a ``NaN``, or an infinity.
* Every figure is explainable: a plain-language glossary states in one line
  what an approval step, a completion rate, or an overdue step means, and the
  breakdown helpers expose the components a rate was derived from.

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

# ISO 8601 calendar date shape used across the module.
ISO_DATE_FORMAT = "YYYY-MM-DD"

# Canonical code sets, mirrored from ``models.py`` / ``schemas.py`` so the two
# stay in step without importing the ORM (which would pull in SQLAlchemy and
# break the pure-engine, no-database guarantee this module shares with
# ``sla_engine`` and ``delegation_engine``).
DECISION_CODES: tuple[str, ...] = ("pending", "approved", "rejected")
STATUS_CODES: tuple[str, ...] = ("pending", "approved", "rejected", "cancelled")

# Rounding steps. A rate carries four decimals of resolution; its percentage
# form carries two. Half-up is the rounding people expect on a report.
_RATE_QUANTUM = Decimal("0.0001")
_PERCENT_QUANTUM = Decimal("0.01")


# -- Plain-language glossary ---------------------------------------------------

# One line per approval concept, in plain words a site manager or an estimator
# understands in a few seconds. Kept here so the API and reports can explain
# every figure they show instead of assuming the reader knows the term.
CONCEPTS: dict[str, str] = {
    "approval_step": (
        "One required sign-off in a route: a named approver or a role must approve before the item moves on."
    ),
    "route": ("An ordered list of approval steps an item must clear, from the first step to the last."),
    "instance": ("One item working its way through a route, for example a single change order awaiting approval."),
    "pending": ("Waiting for a decision: the step or item has neither been approved nor rejected yet."),
    "approved": ("Signed off: the approver accepted the step, so the item may move to the next step or finish."),
    "rejected": ("Turned down: the approver declined the step, which stops the whole item."),
    "cancelled": ("Withdrawn before a final decision: the item was stopped by a person, not by an approval outcome."),
    "step_completion_rate": (
        "Share of a route's steps that have been decided (approved or rejected), from 0 to 1: "
        "decided steps divided by total steps."
    ),
    "pending_vs_approved_vs_rejected": (
        "A count of steps in each state so a reader sees at a glance how many still wait, how many passed, "
        "and how many were turned down."
    ),
    "overdue_step": (
        "A step is overdue when the reference date is past its due date plus any allowed SLA grace days. "
        "With zero grace days, any date after the due date is overdue."
    ),
    "sla_days": (
        "The grace period, in whole days, allowed past a step's due date before it counts as overdue. "
        "It is always an explicit parameter so each team sets its own service level."
    ),
}


def explain(concept: str) -> str:
    """Return a one-line plain-language explanation of an approval concept.

    ``concept`` is one of the keys in :data:`CONCEPTS` (for example
    ``"step_completion_rate"`` or ``"overdue_step"``). Raises ``ValueError`` for
    an unknown key so a typo is caught rather than silently returning nothing.
    """
    try:
        return CONCEPTS[concept]
    except KeyError as exc:
        known = ", ".join(sorted(CONCEPTS))
        raise ValueError(f"Unknown approval concept {concept!r}. Known: {known}.") from exc


# -- Plain-language, localised labels ------------------------------------------

# Each code maps to a plain-language label in English, German and Russian.
# English is the fallback for any locale we do not carry. The decision table
# mirrors ``STEP_DECISIONS`` and the status table mirrors ``INSTANCE_STATUSES``
# from ``models.py``.

_DECISION_LABELS: dict[str, dict[str, str]] = catalogue_table(
    "approval_routes.intl.decision_labels", ("pending", "approved", "rejected")
)

_STATUS_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "pending": "Pending",
        "approved": "Approved",
        "rejected": "Rejected",
        "cancelled": "Cancelled",
    },
    "de": {
        "pending": "Ausstehend",
        "approved": "Genehmigt",
        "rejected": "Abgelehnt",
        "cancelled": "Abgebrochen",
    },
    "ru": {
        "pending": "Ожидает",
        "approved": "Одобрено",
        "rejected": "Отклонено",
        "cancelled": "Отменено",
    },
}

# The word for "not stated / unknown", localised so a missing code never shows a
# raw English word inside an otherwise-translated screen.
_UNKNOWN_LABELS: dict[str, str] = {"en": "Unknown", "de": "Unbekannt", "ru": "Неизвестно"}


def _normalize_locale(locale: str | None) -> str:
    """Return a short lower-case language code (``"de-CH"`` -> ``"de"``)."""
    if not locale:
        return "en"
    return str(locale).replace("_", "-").split("-")[0].strip().lower() or "en"


def _localized_label(code: str | None, locale: str | None, table: dict[str, dict[str, str]]) -> str:
    """Look ``code`` up in ``table`` for ``locale``, English then humanised fallback.

    Resolution order: the requested language, then English, then a readable form
    of the raw code (``"purchase_order"`` -> ``"Purchase order"``). A missing
    code yields the localised word for "Unknown". This never raises and never
    returns a blank, so the UI is safe against a code a newer workflow adds.
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


def describe_decision(code: str | None, locale: str | None = None) -> str:
    """Return a plain-language, localised label for a step decision code.

    ``code`` is one of :data:`DECISION_CODES` (``pending`` / ``approved`` /
    ``rejected``). Unknown or missing codes fall back safely, never blank.
    """
    return _localized_label(code, locale, _DECISION_LABELS)


def describe_status(code: str | None, locale: str | None = None) -> str:
    """Return a plain-language, localised label for an instance status code.

    ``code`` is one of :data:`STATUS_CODES` (``pending`` / ``approved`` /
    ``rejected`` / ``cancelled``). Unknown or missing codes fall back safely.
    """
    return _localized_label(code, locale, _STATUS_LABELS)


# -- Counting helpers ----------------------------------------------------------


def _count_over(values: Iterable[str | None], codes: tuple[str, ...]) -> dict[str, int]:
    """Tally ``values`` into a stable dict over ``codes`` plus an ``other`` bucket.

    The returned dict always has every canonical code present (``0`` when
    absent) plus ``"other"`` for anything unrecognised, so the shape never
    depends on the data. An empty input yields all zeros. Whitespace and case
    are normalised (``" Approved "`` counts as ``approved``). ``None`` and blank
    entries fall into ``"other"`` because a missing code is not a valid state.
    """
    tally: dict[str, int] = dict.fromkeys(codes, 0)
    tally["other"] = 0
    known = set(codes)
    for raw in values:
        key = str(raw).strip().lower() if raw is not None else ""
        if key in known:
            tally[key] += 1
        else:
            tally["other"] += 1
    return tally


def counts_by_decision(decisions: Iterable[str | None]) -> dict[str, int]:
    """Count step decisions into ``pending`` / ``approved`` / ``rejected`` / ``other``.

    Guards the empty set (all zeros) and never raises on an unexpected value; a
    code outside :data:`DECISION_CODES` is tallied under ``"other"`` so the
    total always equals the number of inputs.
    """
    return _count_over(decisions, DECISION_CODES)


def counts_by_status(statuses: Iterable[str | None]) -> dict[str, int]:
    """Count instance statuses into the four canonical states plus ``other``.

    Guards the empty set (all zeros) and never raises on an unexpected value; a
    code outside :data:`STATUS_CODES` is tallied under ``"other"`` so the total
    always equals the number of inputs.
    """
    return _count_over(statuses, STATUS_CODES)


# -- Completion rate -----------------------------------------------------------


def _non_negative_int(value: object, field: str) -> int:
    """Parse a non-negative whole number, else raise a clear ``ValueError``.

    Rejects ``None``, non-numeric text, non-finite values, negatives and
    fractions so a bad count can never turn into a silent ``NaN`` in a rate.
    """
    if value is None:
        raise ValueError(f"{field} is required (got None).")
    if isinstance(value, bool):
        # bool is an int subclass; a boolean count is almost always a caller bug.
        raise ValueError(f"{field} must be a whole number, got {value!r}.")
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{field} is not a valid number: {value!r}.") from exc
    if not parsed.is_finite():
        raise ValueError(f"{field} must be a finite number, got {value!r}.")
    if parsed < 0:
        raise ValueError(f"{field} must not be negative, got {value!r}.")
    if parsed != parsed.to_integral_value():
        raise ValueError(f"{field} must be a whole number, got {value!r}.")
    return int(parsed)


def step_completion_rate(total_steps: object, completed_steps: object) -> dict[str, str]:
    """Report how far a route has been worked through, with a zero guard.

    A step is "completed" once it has been decided (approved or rejected); a
    step still waiting is pending. The rate is ``completed_steps / total_steps``,
    a figure from 0 to 1. Returns a small, self-explaining report a UI or export
    can show directly:

        * ``total_steps``   - the number of steps in the route, echoed.
        * ``completed_steps``- the number already decided, echoed.
        * ``pending_steps`` - ``total_steps - completed_steps``.
        * ``rate``          - completed divided by total, from 0 to 1.
        * ``rate_percent``  - the same figure as a 0 to 100 percentage.
        * ``is_complete``   - true once every step is decided.

    Both inputs must be non-negative whole numbers. A route with zero steps is
    not an error: the rate is defined as ``0`` (nothing has been completed),
    which is the division-by-zero guard. ``completed_steps`` greater than
    ``total_steps`` is a genuine inconsistency and raises ``ValueError`` rather
    than returning a rate above 1.
    """
    total = _non_negative_int(total_steps, "total_steps")
    completed = _non_negative_int(completed_steps, "completed_steps")
    if completed > total:
        raise ValueError(
            f"completed_steps ({completed}) must not exceed total_steps ({total}).",
        )

    pending = total - completed
    if total == 0:
        # No steps exist, so completion is zero by definition; this is the
        # division-by-zero guard.
        rate = Decimal("0")
    else:
        rate = Decimal(completed) / Decimal(total)

    rate = rate.quantize(_RATE_QUANTUM, rounding=ROUND_HALF_UP)
    rate_percent = (rate * Decimal("100")).quantize(_PERCENT_QUANTUM, rounding=ROUND_HALF_UP)

    return {
        "total_steps": str(total),
        "completed_steps": str(completed),
        "pending_steps": str(pending),
        "rate": str(rate),
        "rate_percent": str(rate_percent),
        "is_complete": "true" if (total > 0 and completed >= total) else "false",
    }


def completion_from_decisions(
    decisions: Iterable[str | None],
    total_steps: object | None = None,
) -> dict[str, str]:
    """Derive a completion report from a list of per-step decisions.

    Counts ``approved`` and ``rejected`` decisions as completed and everything
    else (``pending`` / unknown) as not yet done, then defers to
    :func:`step_completion_rate` for the guarded arithmetic. The result carries
    the decision counts alongside the rate so the figure is fully explainable:
    a reader can see exactly which decisions produced it.

    ``total_steps`` defaults to the number of decisions supplied (one decision
    row per step). Pass an explicit ``total_steps`` when a route has steps that
    have not produced a decision row yet, so pending steps are counted honestly
    rather than ignored.
    """
    counts = counts_by_decision(decisions)
    completed = counts["approved"] + counts["rejected"]
    if total_steps is None:
        total = counts["pending"] + counts["approved"] + counts["rejected"] + counts["other"]
    else:
        total = _non_negative_int(total_steps, "total_steps")

    report = step_completion_rate(total, completed)
    report["approved"] = str(counts["approved"])
    report["rejected"] = str(counts["rejected"])
    report["pending"] = str(counts["pending"])
    return report


# -- Overdue steps -------------------------------------------------------------


def _to_date(value: object, field: str) -> date:
    """Parse an ISO 8601 date string or a ``date`` / ``datetime`` into a ``date``.

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


def format_iso_date(value: object) -> str:
    """Return ``value`` as an ISO 8601 ``YYYY-MM-DD`` string.

    Accepts an ISO date string, a ``date`` or a ``datetime`` (the date part is
    used). This is the single place a stored date is rendered for display or
    export, so every surface shows the same locale-neutral shape.
    """
    return _to_date(value, "value").isoformat()


def days_overdue(due_date: object, reference_date: object, *, sla_days: object = 0) -> int:
    """Return whole days a step is past its due date plus SLA grace, clamped at zero.

    The effective deadline is ``due_date + sla_days``. When ``reference_date`` is
    at or before that deadline the step is on time and the result is ``0`` (never
    negative). ``sla_days`` is the grace period in whole days and is always an
    explicit parameter, defaulting to ``0`` (no grace). All three dates follow
    ISO 8601; a ``date`` or ``datetime`` is also accepted.
    """
    grace = _non_negative_int(sla_days, "sla_days")
    due = _to_date(due_date, "due_date")
    reference = _to_date(reference_date, "reference_date")
    elapsed = (reference - due).days - grace
    return max(0, elapsed)


def is_step_overdue(due_date: object, reference_date: object, *, sla_days: object = 0) -> bool:
    """Whether a step has passed its due date plus the allowed SLA grace days.

    Returns ``True`` once ``reference_date`` is more than ``sla_days`` days past
    ``due_date``. A ``due_date`` of ``None`` means the step has no deadline, so
    it can never be overdue and the result is ``False`` (no error). With
    ``sla_days`` at its default of ``0``, any reference date after the due date
    is overdue. This is the boolean companion to :func:`days_overdue`.
    """
    if due_date is None:
        return False
    return days_overdue(due_date, reference_date, sla_days=sla_days) > 0


__all__ = [
    "CONCEPTS",
    "DECISION_CODES",
    "ISO_DATE_FORMAT",
    "STATUS_CODES",
    "completion_from_decisions",
    "counts_by_decision",
    "counts_by_status",
    "days_overdue",
    "describe_decision",
    "describe_status",
    "explain",
    "format_iso_date",
    "is_step_overdue",
    "step_completion_rate",
]
