# DDC-CWICR-OE: DataDrivenConstruction / OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""International, database-free reporting helpers for the transmittals module.

Everything here is a plain function or small dataclass with no database, clock
or network access, so it can be unit tested in isolation and reused by the
service, router and reporting layers. The goal is a set of transmittal figures
that read the same for a document controller anywhere in the world:

    - No hardcoded locale. Words are localized on request (en / de / ru) and
      fall back to English for any other language, so nothing is ever shown as
      a raw code.
    - All dates are ISO 8601 (YYYY-MM-DD). A stored value may also be a full
      ISO timestamp (the service records the issue moment as
      ``datetime.now(UTC).isoformat()``); only the calendar-date part is used.
    - The acknowledgement SLA is always a parameter, never assumed, because
      "how many days to acknowledge" is a project and contract decision.

Every figure guards its edge cases: nothing issued, empty sets, negative
counts or a reply dated before the issue date all resolve to a well-defined
value or a clean :class:`ValueError`, never a 500, a NaN, an infinity or a
misleading negative. Any rate stays inside [0, 1] (and its percent twin inside
[0, 100]). Each result also exposes the components it was derived from, so a
reader can see exactly how the number was reached.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta

from app.core.i18n import catalogue_table
from app.modules.transmittals.logic import (
    PURPOSE_CODES,
    VALID_STATUSES,
    parse_iso_date,
)

# ── Localization (en / de / ru, English fallback) ─────────────────────────

DEFAULT_LOCALE = "en"
SUPPORTED_LOCALES: tuple[str, ...] = ("en", "de", "ru")

# Short, plain-language label for each status, per language. English is the
# fallback for any language not listed and for any status that has no entry.
_STATUS_WORDS: dict[str, dict[str, str]] = catalogue_table(
    "transmittals.intl.status_words", ("draft", "issued", "responded")
)

# Short label for each purpose code, per language.
_PURPOSE_WORDS: dict[str, dict[str, str]] = {
    "en": {
        "for_approval": "for approval",
        "for_review": "for review",
        "for_information": "for information",
        "for_construction": "for construction",
        "for_tender": "for tender",
        "for_record": "for record",
    },
    "de": {
        "for_approval": "zur Genehmigung",
        "for_review": "zur Pruefung",
        "for_information": "zur Information",
        "for_construction": "zur Ausfuehrung",
        "for_tender": "zur Ausschreibung",
        "for_record": "zur Ablage",
    },
    "ru": {
        "for_approval": "на утверждение",
        "for_review": "на рассмотрение",
        "for_information": "для сведения",
        "for_construction": "в производство работ",
        "for_tender": "для тендера",
        "for_record": "в архив",
    },
}


def _normalize_locale(locale: str | None) -> str:
    """Return a supported base language code, defaulting to English.

    Accepts full tags such as ``de-DE`` or ``ru_RU`` and keeps only the base
    language. Any language we do not carry falls back to English so a caller
    never has to handle a missing translation.
    """
    if not locale:
        return DEFAULT_LOCALE
    base = locale.strip().lower().replace("_", "-").split("-", 1)[0]
    return base if base in SUPPORTED_LOCALES else DEFAULT_LOCALE


def localize_status(status_code: str, locale: str | None = DEFAULT_LOCALE) -> str:
    """Return the plain-language status word in the requested language.

    Falls back to the English word, then to the raw code, so the result is
    always human-readable and never blank.
    """
    lang = _normalize_locale(locale)
    words = _STATUS_WORDS.get(lang, {})
    if status_code in words:
        return words[status_code]
    return _STATUS_WORDS[DEFAULT_LOCALE].get(status_code, status_code)


def localize_purpose(purpose_code: str, locale: str | None = DEFAULT_LOCALE) -> str:
    """Return the plain-language purpose label in the requested language.

    Falls back to the English label, then to the raw code, so the result is
    always human-readable and never blank.
    """
    lang = _normalize_locale(locale)
    words = _PURPOSE_WORDS.get(lang, {})
    if purpose_code in words:
        return words[purpose_code]
    return _PURPOSE_WORDS[DEFAULT_LOCALE].get(purpose_code, purpose_code)


# ── One-line explainers ───────────────────────────────────────────────────

# Plain-language, one-sentence definitions a first-time user can read in the
# UI next to each figure. English source text; localize the surrounding UI as
# usual. Kept ASCII-clean (no dashes or smart quotes) on purpose.
EXPLAINERS: dict[str, str] = {
    "transmittal": (
        "A transmittal is a formal, numbered record that a set of documents was "
        "sent to named recipients for a stated purpose on a stated date."
    ),
    "acknowledgement_rate": (
        "The acknowledgement rate is the share of issued transmittals whose "
        "recipients have confirmed they received them."
    ),
    "overdue_acknowledgement": (
        "An acknowledgement is overdue when a recipient has not confirmed "
        "receipt by the due date set by the agreed acknowledgement SLA."
    ),
    "response_time": (
        "Response time is the number of whole calendar days between the day a "
        "transmittal was issued and the day a recipient responded."
    ),
}


def explain(term: str) -> str:
    """Return the one-line explainer for a term, or an empty string if unknown.

    Never raises, so it is safe to call straight from a template. Known terms
    are the keys of :data:`EXPLAINERS`.
    """
    return EXPLAINERS.get(term, "")


# ── Date helpers (ISO 8601, timestamp-tolerant) ───────────────────────────


def _iso_date_only(value: str | None) -> str | None:
    """Return the calendar-date part of an ISO date or timestamp, validated.

    Accepts a plain ``YYYY-MM-DD`` date or a full ISO timestamp such as
    ``2026-03-31T09:15:00+00:00`` and keeps only the leading date. Returns
    ``None`` for a blank value and raises :class:`ValueError` (via
    :func:`parse_iso_date`) if the date part is not a real calendar date.
    """
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    head = text.split("T", 1)[0].split(" ", 1)[0]
    return parse_iso_date(head)


# ── Counts by status and by purpose ───────────────────────────────────────


def counts_by_status(statuses: object) -> dict[str, int]:
    """Count transmittals per status, with every known status pre-seeded to 0.

    ``statuses`` is any iterable of status strings (for example the ``status``
    of each transmittal in a project). The result always carries a key for
    every value in :data:`~app.modules.transmittals.logic.VALID_STATUSES` so a
    dashboard has no gaps, plus an ``other`` bucket for any unexpected value.
    An empty or ``None`` input yields all-zero counts, never an error.
    """
    result: dict[str, int] = dict.fromkeys(VALID_STATUSES, 0)
    result["other"] = 0
    if statuses is None:
        return result
    for raw in statuses:
        code = raw if isinstance(raw, str) else str(raw)
        if code in result and code != "other":
            result[code] += 1
        else:
            result["other"] += 1
    return result


def counts_by_purpose(purposes: object) -> dict[str, int]:
    """Count transmittals per purpose code, with every code pre-seeded to 0.

    ``purposes`` is any iterable of purpose-code strings. The result always
    carries a key for every value in
    :data:`~app.modules.transmittals.logic.PURPOSE_CODES`, plus an ``other``
    bucket for any unexpected value. An empty or ``None`` input yields all-zero
    counts, never an error.
    """
    result: dict[str, int] = dict.fromkeys(PURPOSE_CODES, 0)
    result["other"] = 0
    if purposes is None:
        return result
    tally = Counter(str(p) for p in purposes)
    for code, count in tally.items():
        if code in result and code != "other":
            result[code] = count
        else:
            result["other"] += count
    return result


# ── Acknowledgement rate ──────────────────────────────────────────────────


@dataclass(frozen=True)
class AcknowledgementRate:
    """The share of issued transmittals that have been acknowledged.

    Attributes:
        acknowledged: How many issued transmittals have been acknowledged.
        issued: How many transmittals were issued (the denominator).
        fraction: ``acknowledged / issued`` in the range [0, 1]. Zero when
            nothing was issued (a defined answer, not an error).
        percent: The same figure as a percentage in the range [0, 100],
            rounded to one decimal place.
        defined: ``True`` when the rate was computed from a real denominator,
            ``False`` when nothing was issued so the rate is 0 by convention.
        explanation: A one-line, plain-language reading of the figure.
    """

    acknowledged: int
    issued: int
    fraction: float
    percent: float
    defined: bool
    explanation: str


def acknowledgement_rate(acknowledged: int, issued: int) -> AcknowledgementRate:
    """Compute the acknowledgement rate with a division-by-zero guard.

    The rate is ``acknowledged / issued``, kept in [0, 1] (and [0, 100] for the
    percent twin). Guards:

        - Negative ``acknowledged`` or ``issued`` raise :class:`ValueError`;
          counts cannot be negative.
        - ``acknowledged`` greater than ``issued`` raises :class:`ValueError`;
          you cannot acknowledge more than were issued, and silently clamping
          would hide a data problem.
        - ``issued`` of zero returns a defined 0.0 rate (``defined=False``)
          instead of dividing by zero, so a fresh project reads cleanly.

    The result never produces a NaN, an infinity or a value outside range.
    """
    if acknowledged < 0 or issued < 0:
        raise ValueError("Acknowledged and issued counts cannot be negative.")
    if acknowledged > issued:
        raise ValueError(
            f"Acknowledged count ({acknowledged}) cannot exceed the issued count ({issued}). Check the inputs."
        )
    if issued == 0:
        return AcknowledgementRate(
            acknowledged=0,
            issued=0,
            fraction=0.0,
            percent=0.0,
            defined=False,
            explanation="No transmittals have been issued yet, so there is no acknowledgement rate to report.",
        )
    fraction = acknowledged / issued
    percent = round(fraction * 100, 1)
    return AcknowledgementRate(
        acknowledged=acknowledged,
        issued=issued,
        fraction=fraction,
        percent=percent,
        defined=True,
        explanation=(f"{acknowledged} of {issued} issued transmittals acknowledged ({percent} percent)."),
    )


# ── Overdue acknowledgement ───────────────────────────────────────────────


@dataclass(frozen=True)
class OverdueCheck:
    """Whether a recipient has missed the acknowledgement deadline.

    Attributes:
        issued_date: The issue date used as the start of the SLA window, or
            ``None`` if not known.
        due_date: The acknowledgement deadline (``issued_date`` plus
            ``sla_days`` calendar days), or ``None`` if it cannot be computed.
        reference_date: The date the check was made against (for example
            today), or ``None`` if not supplied.
        sla_days: The agreed number of calendar days to acknowledge in.
        acknowledged: Whether the recipient has already acknowledged.
        is_overdue: ``True`` only when not yet acknowledged and the reference
            date is past the due date.
        days_overdue: Whole calendar days past the due date, never negative.
        explanation: A one-line, plain-language reading of the result.
    """

    issued_date: str | None
    due_date: str | None
    reference_date: str | None
    sla_days: int
    acknowledged: bool
    is_overdue: bool
    days_overdue: int
    explanation: str


def acknowledgement_overdue(
    issued_date: str | None,
    reference_date: str | None,
    sla_days: int,
    *,
    acknowledged: bool = False,
) -> OverdueCheck:
    """Flag an overdue acknowledgement from a due date and a reference date.

    The acknowledgement SLA is a parameter (``sla_days`` calendar days from the
    issue date), because the allowed time to acknowledge is a project and
    contract decision, not a fixed worldwide rule. Calendar days are used so
    the rule is correct regardless of local working-day and holiday calendars.

    Rules and guards:

        - ``sla_days`` cannot be negative; a negative SLA raises
          :class:`ValueError`.
        - If the transmittal is already ``acknowledged``, it is never overdue.
        - If the issue date or the reference date is missing, the result is
          "not overdue" with no due date, since there is nothing to compare.
        - Otherwise the due date is the issue date plus ``sla_days`` calendar
          days, and it is overdue only when the reference date is strictly
          after the due date. ``days_overdue`` is clamped at zero so an early
          reference date never yields a misleading negative.

    ``issued_date`` and ``reference_date`` accept a plain ISO date or a full
    ISO timestamp; only the calendar-date part is used.
    """
    if sla_days < 0:
        raise ValueError("Acknowledgement SLA cannot be negative. Use 0 or more calendar days.")

    issued = _iso_date_only(issued_date)
    reference = _iso_date_only(reference_date)
    due = None
    if issued is not None:
        due = (date.fromisoformat(issued) + timedelta(days=sla_days)).isoformat()

    if acknowledged:
        return OverdueCheck(
            issued_date=issued,
            due_date=due,
            reference_date=reference,
            sla_days=sla_days,
            acknowledged=True,
            is_overdue=False,
            days_overdue=0,
            explanation="Already acknowledged, so it is not overdue.",
        )

    if due is None or reference is None:
        return OverdueCheck(
            issued_date=issued,
            due_date=due,
            reference_date=reference,
            sla_days=sla_days,
            acknowledged=False,
            is_overdue=False,
            days_overdue=0,
            explanation=("Not enough dates to judge: an issue date and a reference date are both needed."),
        )

    delta = (date.fromisoformat(reference) - date.fromisoformat(due)).days
    days_overdue = delta if delta > 0 else 0
    is_overdue = days_overdue > 0
    if is_overdue:
        explanation = (
            f"Overdue by {days_overdue} day(s): due {due} under a {sla_days}-day SLA, "
            f"not acknowledged as of {reference}."
        )
    else:
        explanation = f"Within the {sla_days}-day acknowledgement SLA (due {due}, checked {reference})."
    return OverdueCheck(
        issued_date=issued,
        due_date=due,
        reference_date=reference,
        sla_days=sla_days,
        acknowledged=False,
        is_overdue=is_overdue,
        days_overdue=days_overdue,
        explanation=explanation,
    )


# ── Response time ─────────────────────────────────────────────────────────


def response_time_days(issued_date: str | None, responded_date: str | None) -> int | None:
    """Return whole calendar days from issue to response, or ``None`` if unknown.

    Both dates accept a plain ISO date or a full ISO timestamp; only the
    calendar-date part is used. Returns ``None`` when either date is missing,
    since there is nothing to measure. A response dated before the issue date
    raises a clean :class:`ValueError` rather than returning a misleading
    negative, because that ordering is always a data error.
    """
    issued = _iso_date_only(issued_date)
    responded = _iso_date_only(responded_date)
    if issued is None or responded is None:
        return None
    delta = (date.fromisoformat(responded) - date.fromisoformat(issued)).days
    if delta < 0:
        raise ValueError(f"Response date ({responded}) cannot be earlier than the issue date ({issued}).")
    return delta
