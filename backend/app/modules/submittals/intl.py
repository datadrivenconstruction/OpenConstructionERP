# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""International, explainable helpers for submittal review analytics.

This module is deliberately pure and dependency-free (standard library
only). It holds no database, no FastAPI, and no framework state, so it can
be imported and unit-tested in isolation. It is strictly additive: nothing
here changes the existing service, schema, or router contracts. It layers
plain-language, locale-aware reporting on top of the vocabulary those files
already define.

Design goals:

* International. Dates are ISO 8601 (``YYYY-MM-DD``). No locale is baked
  into any calculation. Review outcome and status words are translatable
  (en / de / ru today) with a safe English fallback. The review SLA is
  always a caller-supplied parameter, never a hidden constant.
* Clarity. Every figure has a one-line, plain-language explainer a site
  engineer or estimator can read in seconds.
* Robust edge cases. Division by zero, empty inputs, negative counts, and
  a review dated before its submission all return well-defined values or
  raise a clean ``ValueError``. No figure is ever NaN, infinity, or a
  misleading negative.
* Explainability. Every derived figure documents how it is computed and
  exposes its raw components so a reviewer can audit the number.

The status and outcome vocabularies mirror the ones pinned by
``schemas.py`` (``SubmittalReviewRequest``) and ``service.py``
(``_SUBMITTAL_STATUS_TRANSITIONS``). They are restated here as plain data
so this module stays import-light and independent; keep them in sync if the
canonical vocabulary ever grows.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from app.core.i18n import catalogue_table

# ── Vocabulary (mirrors schemas.py / service.py) ──────────────────────────

# Every submittal status the FSM can hold.
SUBMITTAL_STATUSES: tuple[str, ...] = (
    "draft",
    "submitted",
    "under_review",
    "approved",
    "approved_as_noted",
    "revise_and_resubmit",
    "rejected",
    "closed",
)

# The four decisions a reviewer can record on a submittal review.
REVIEW_OUTCOMES: tuple[str, ...] = (
    "approved",
    "approved_as_noted",
    "revise_and_resubmit",
    "rejected",
)

# Outcomes that count as a positive sign-off when computing approval rate.
# ``approved_as_noted`` is included because the submittal is cleared to
# proceed (with minor annotations), which is the industry-standard reading.
APPROVING_OUTCOMES: frozenset[str] = frozenset({"approved", "approved_as_noted"})

# Default review turnaround target in whole days. This is only a fallback so
# callers that do not track a per-project SLA still get a sensible number;
# every public function accepts an explicit ``sla_days`` override.
DEFAULT_REVIEW_SLA_DAYS: int = 14

# Default UI language when a caller passes nothing or an unknown code.
DEFAULT_LANGUAGE: str = "en"

# ── Localised labels (English fallback) ───────────────────────────────────

_STATUS_LABELS: dict[str, dict[str, str]] = catalogue_table(
    "submittals.intl.status_labels",
    (
        "draft",
        "submitted",
        "under_review",
        "approved",
        "approved_as_noted",
        "revise_and_resubmit",
        "rejected",
        "closed",
    ),
)

# Review outcome labels reuse the status wording for the four decisions.
_OUTCOME_LABELS: dict[str, dict[str, str]] = {
    lang: {outcome: labels[outcome] for outcome in REVIEW_OUTCOMES} for lang, labels in _STATUS_LABELS.items()
}


def normalize_language(language: str | None) -> str:
    """Return a supported base language code, defaulting to English.

    Accepts region-tagged codes such as ``de-DE`` or ``ru_RU`` and reduces
    them to the base language. Any unknown or empty value falls back to
    :data:`DEFAULT_LANGUAGE` so callers never have to guard the input.
    """
    if not language:
        return DEFAULT_LANGUAGE
    base = language.strip().lower().replace("_", "-").split("-", 1)[0]
    return base if base in _STATUS_LABELS else DEFAULT_LANGUAGE


def localize_status(status_value: str, language: str | None = None) -> str:
    """Translate a submittal status into a plain-language label.

    Falls back to English, and then to a humanised form of the raw code
    (underscores to spaces) if the status is unknown, so the caller always
    gets a readable string rather than a blank or a raised error.
    """
    lang = normalize_language(language)
    localized = _STATUS_LABELS[lang].get(status_value)
    if localized is not None:
        return localized
    english = _STATUS_LABELS[DEFAULT_LANGUAGE].get(status_value)
    if english is not None:
        return english
    return status_value.replace("_", " ").strip().capitalize()


def localize_outcome(outcome: str, language: str | None = None) -> str:
    """Translate a review outcome into a plain-language label.

    Same fallback chain as :func:`localize_status`.
    """
    lang = normalize_language(language)
    localized = _OUTCOME_LABELS[lang].get(outcome)
    if localized is not None:
        return localized
    english = _OUTCOME_LABELS[DEFAULT_LANGUAGE].get(outcome)
    if english is not None:
        return english
    return outcome.replace("_", " ").strip().capitalize()


# ── Date helpers (ISO 8601) ───────────────────────────────────────────────


def parse_iso_date(value: str | date) -> date:
    """Parse an ISO 8601 ``YYYY-MM-DD`` string into a :class:`date`.

    A :class:`date` is passed through unchanged. Any value that is not a
    valid ISO date raises a clean :class:`ValueError` naming the problem,
    never a bare parsing traceback.
    """
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        msg = "Date must be a non-empty ISO 8601 string (YYYY-MM-DD)."
        raise ValueError(msg)
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        msg = f"Invalid ISO 8601 date {value!r}; expected YYYY-MM-DD."
        raise ValueError(msg) from exc


def iso_days_between(start: str | date, end: str | date) -> int:
    """Signed whole days from ``start`` to ``end`` (end minus start).

    Positive when ``end`` is later than ``start``, negative when earlier.
    Both bounds are ISO 8601 dates. This is the low-level primitive; callers
    that need a non-negative duration use :func:`review_cycle_time_days`.
    """
    return (parse_iso_date(end) - parse_iso_date(start)).days


def review_cycle_time_days(date_submitted: str | date, date_returned: str | date) -> int:
    """Whole days a submittal spent in review, from submission to return.

    Derivation: ``date_returned`` minus ``date_submitted`` in calendar days.
    A same-day return is ``0``. If the return date precedes the submission
    date the inputs are inconsistent, so this raises :class:`ValueError`
    rather than reporting a misleading negative cycle time.
    """
    days = iso_days_between(date_submitted, date_returned)
    if days < 0:
        msg = "date_returned precedes date_submitted; a review cannot be returned before it was submitted."
        raise ValueError(msg)
    return days


def review_due_date(date_submitted: str | date, sla_days: int = DEFAULT_REVIEW_SLA_DAYS) -> str:
    """ISO 8601 date by which a review is due, given the submission and SLA.

    Derivation: ``date_submitted`` plus ``sla_days`` calendar days. The SLA
    must be zero or positive; a negative SLA raises :class:`ValueError`.
    """
    if sla_days < 0:
        msg = "sla_days must be zero or positive."
        raise ValueError(msg)
    from datetime import timedelta

    due = parse_iso_date(date_submitted) + timedelta(days=sla_days)
    return due.isoformat()


def is_review_overdue(
    due_date: str | date,
    reference_date: str | date,
    *,
    sla_days: int = 0,
    returned: bool = False,
) -> bool:
    """Flag whether a review is overdue as of a reference date.

    A review is overdue when it is still open (``returned`` is ``False``)
    and the reference date is more than ``sla_days`` grace days past the due
    date. Formally: ``iso_days_between(due_date, reference_date) > sla_days``.

    Parameters mirror how a scheduler would call this: ``due_date`` is when
    the review was expected back, ``reference_date`` is "today" (or any
    as-of date), and ``sla_days`` is a parameterised grace window (default
    zero, meaning overdue the day after the due date). A review that has
    already been returned is never overdue. ``sla_days`` must be zero or
    positive.
    """
    if returned:
        return False
    if sla_days < 0:
        msg = "sla_days must be zero or positive."
        raise ValueError(msg)
    return iso_days_between(due_date, reference_date) > sla_days


# ── Rates and counts (guarded) ────────────────────────────────────────────


def approval_rate(approved_count: int, reviewed_count: int) -> float:
    """Share of reviewed submittals that were approved, in ``[0.0, 1.0]``.

    Derivation: ``approved_count / reviewed_count``. When nothing has been
    reviewed the rate is defined as ``0.0`` (a guarded division, never a
    NaN or a 500). Negative counts, or more approvals than reviews, are
    inconsistent inputs and raise :class:`ValueError` rather than producing
    a rate outside ``[0, 1]``.
    """
    if approved_count < 0 or reviewed_count < 0:
        msg = "Counts must be zero or positive."
        raise ValueError(msg)
    if approved_count > reviewed_count:
        msg = "approved_count cannot exceed reviewed_count."
        raise ValueError(msg)
    if reviewed_count == 0:
        return 0.0
    return approved_count / reviewed_count


def approval_rate_percent(approved_count: int, reviewed_count: int) -> float:
    """Approval rate as a percentage in ``[0.0, 100.0]``.

    Same derivation and guards as :func:`approval_rate`, scaled by 100 and
    rounded to one decimal place for display.
    """
    return round(approval_rate(approved_count, reviewed_count) * 100.0, 1)


def _counts(values: Iterable[str], vocabulary: tuple[str, ...], kind: str) -> dict[str, int]:
    """Tally ``values`` against a fixed ``vocabulary``.

    Returns a dict keyed by every vocabulary term (zero-filled) so the shape
    is stable regardless of the input, which keeps dashboards and tests
    deterministic. An unrecognised value raises :class:`ValueError` naming
    the offending term rather than silently miscounting.
    """
    tally: dict[str, int] = dict.fromkeys(vocabulary, 0)
    for value in values:
        if value not in tally:
            msg = f"Unknown {kind} {value!r}; expected one of {', '.join(vocabulary)}."
            raise ValueError(msg)
        tally[value] += 1
    return tally


def counts_by_status(statuses: Iterable[str]) -> dict[str, int]:
    """Count submittals by status, zero-filled across all known statuses.

    An empty input yields every status at zero. An unknown status raises
    :class:`ValueError`.
    """
    return _counts(statuses, SUBMITTAL_STATUSES, "status")


def counts_by_outcome(outcomes: Iterable[str]) -> dict[str, int]:
    """Count reviews by outcome, zero-filled across all known outcomes.

    An empty input yields every outcome at zero. An unknown outcome raises
    :class:`ValueError`.
    """
    return _counts(outcomes, REVIEW_OUTCOMES, "outcome")


# ── One-line plain-language explainers ────────────────────────────────────


def explain_submittal() -> str:
    """One line: what a submittal is."""
    return (
        "A submittal is a document (shop drawing, product data, sample, or "
        "certificate) sent for review to confirm it meets the specification "
        "before the work or material is used."
    )


def explain_review_cycle_time() -> str:
    """One line: how review cycle time is derived."""
    return (
        "Review cycle time is the whole number of calendar days from the "
        "date a submittal was submitted to the date it was returned."
    )


def explain_approval_rate() -> str:
    """One line: how approval rate is derived."""
    return (
        "Approval rate is the number of submittals approved (including "
        "approved as noted) divided by the number reviewed, from 0 to 100 "
        "percent; it is zero when nothing has been reviewed."
    )


def explain_overdue_review() -> str:
    """One line: what makes a review overdue."""
    return (
        "A review is overdue when it is still open and the current date is "
        "past its due date by more than the agreed SLA grace days."
    )


# ── Composite, explainable summary ────────────────────────────────────────


def summarize_review_performance(
    outcomes: Iterable[str],
    *,
    cycle_times_days: Iterable[int] | None = None,
    language: str | None = None,
) -> dict[str, object]:
    """Build one explainable review-performance summary.

    Ties the individual helpers together and exposes every raw component so
    the result can be audited: the outcome tally, the reviewed and approved
    counts feeding the rate, the rate itself in both scales, and the average
    cycle time when cycle-time samples are supplied. Outcome labels are
    localised for the requested language with an English fallback.

    All inputs are guarded: an empty ``outcomes`` yields a zero-filled tally,
    a zero reviewed count yields a ``0.0`` rate, and an empty
    ``cycle_times_days`` yields ``None`` for the average (never a division by
    zero). Negative cycle-time samples are rejected with :class:`ValueError`.
    """
    lang = normalize_language(language)
    tally = counts_by_outcome(outcomes)
    reviewed = sum(tally.values())
    approved = sum(count for outcome, count in tally.items() if outcome in APPROVING_OUTCOMES)

    average_cycle_time: float | None = None
    cycle_samples: list[int] = []
    if cycle_times_days is not None:
        cycle_samples = list(cycle_times_days)
        for sample in cycle_samples:
            if sample < 0:
                msg = "Cycle time samples must be zero or positive."
                raise ValueError(msg)
        if cycle_samples:
            average_cycle_time = round(sum(cycle_samples) / len(cycle_samples), 1)

    localized_tally = {localize_outcome(outcome, lang): count for outcome, count in tally.items()}

    return {
        "language": lang,
        "reviewed_count": reviewed,
        "approved_count": approved,
        "approval_rate": approval_rate(approved, reviewed),
        "approval_rate_percent": approval_rate_percent(approved, reviewed),
        "counts_by_outcome": tally,
        "counts_by_outcome_localized": localized_tally,
        "cycle_time_sample_count": len(cycle_samples),
        "average_cycle_time_days": average_cycle_time,
        "explainers": {
            "submittal": explain_submittal(),
            "review_cycle_time": explain_review_cycle_time(),
            "approval_rate": explain_approval_rate(),
            "overdue_review": explain_overdue_review(),
        },
    }
