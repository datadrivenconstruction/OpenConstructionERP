# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""What the submittal register is asked every week, as pure functions.

A contractor that installs equipment (mechanical, electrical, plumbing, but
also a facade or a lift) cannot order it until its submittal comes back
approved, and the equipment takes weeks to arrive. So the register has to
answer three questions that the stored columns alone do not:

* **What did the reviewer stamp?** The workflow status says where the document
  is. The stamp says what the reviewer decided, and it has to survive the
  submittal being closed or sent in again. The decision is one of the four
  outcomes this module always had; the *code* printed on the stamp ("B", "2",
  "AAN") is whatever the project's reviewer writes, so it is stored as written
  and only defaulted from :data:`DEFAULT_REVIEW_CODES` when nobody supplied one.
* **How long has it been with the reviewer, and is that late?** Late is
  measured against the contract's review period, which is a number on the
  submittal. When it is not set the answer is "unknown", never a guess.
* **By when must it be approved for the equipment to arrive?** Required on
  site less the lead time. Past that date without an approval, the delivery
  date is already lost.

Like :mod:`app.modules.submittals.validators` this file is standard library
only, and the clock is always an argument.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

__all__ = [
    "APPROVAL_SCOPE_STATUSES",
    "AWAITING_REVIEW_STATUSES",
    "DEFAULT_REVIEW_CODES",
    "DISCIPLINES",
    "DISCIPLINE_CODES",
    "PROCEED_OUTCOMES",
    "REVIEW_OUTCOMES",
    "Discipline",
    "Tracking",
    "approval_late_days",
    "approval_needed_by",
    "days_in_review",
    "default_review_code",
    "effective_outcome",
    "history_entry",
    "latest_history_entry",
    "may_proceed",
    "parse_day",
    "replaces_returned_revision",
    "review_due_date",
    "review_overdue_days",
    "review_stamp",
    "submit_by_date",
    "summarise",
    "track",
]

#: The four decisions a reviewer records. Mirrors ``intl.REVIEW_OUTCOMES`` and
#: the pattern on ``SubmittalReviewRequest.status``.
REVIEW_OUTCOMES: tuple[str, ...] = ("approved", "approved_as_noted", "revise_and_resubmit", "rejected")

#: Outcomes after which the contractor may order and install. Approved as noted
#: is an approval subject to the corrections written on it.
PROCEED_OUTCOMES: frozenset[str] = frozenset({"approved", "approved_as_noted"})

#: The stamp letter printed when the reviewer supplied none. A project whose
#: reviewer uses other marks records them per review; these are a default, not
#: a rule.
DEFAULT_REVIEW_CODES: dict[str, str] = {
    "approved": "A",
    "approved_as_noted": "B",
    "revise_and_resubmit": "C",
    "rejected": "D",
}

#: Statuses in which the document is with the reviewer.
AWAITING_REVIEW_STATUSES: frozenset[str] = frozenset({"submitted", "under_review"})

#: Statuses in which an approval is still being pursued. A closed submittal is
#: finished whatever it was closed as.
APPROVAL_SCOPE_STATUSES: frozenset[str] = frozenset(
    {"draft", "submitted", "under_review", "revise_and_resubmit", "rejected"}
)


@dataclass(frozen=True)
class Discipline:
    """One entry of the default discipline list.

    Attributes:
        code: The stored value.
        short: The two letter mark firms put in a document number.
        labels: The printed word, by language.
    """

    code: str
    short: str
    labels: dict[str, str]


#: The disciplines offered by default. This is data, not an enum: the column
#: accepts any lower-case code, so a project that splits or names its trades
#: differently is not refused, and an unknown code prints as stored.
DISCIPLINES: tuple[Discipline, ...] = (
    Discipline("mechanical", "ME", {"en": "Mechanical", "tr": "Mekanik"}),
    Discipline("hvac", "HV", {"en": "HVAC", "tr": "İklimlendirme"}),
    Discipline("plumbing", "PL", {"en": "Plumbing and drainage", "tr": "Sıhhi tesisat"}),
    Discipline("fire_protection", "FP", {"en": "Fire protection", "tr": "Yangın tesisatı"}),
    Discipline("electrical", "EL", {"en": "Electrical", "tr": "Elektrik"}),
    Discipline("lighting", "LT", {"en": "Lighting", "tr": "Aydınlatma"}),
    Discipline("elv", "LC", {"en": "Low current", "tr": "Zayıf akım"}),
    Discipline("bms", "BM", {"en": "Building automation", "tr": "Bina otomasyonu"}),
    Discipline("architectural", "AR", {"en": "Architectural", "tr": "Mimari"}),
    Discipline("structural", "ST", {"en": "Structural", "tr": "Statik"}),
    Discipline("civil", "CV", {"en": "Civil", "tr": "İnşaat"}),
)

DISCIPLINE_CODES: tuple[str, ...] = tuple(item.code for item in DISCIPLINES)


def parse_day(raw: Any) -> date | None:
    """The leading ``YYYY-MM-DD`` of a stored date, or ``None`` when unreadable."""
    if isinstance(raw, date):
        return raw
    text = str(raw or "").strip()
    if len(text) < 10:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _whole_number(raw: Any) -> int | None:
    """A non-negative whole number, or ``None`` for anything else (booleans included)."""
    if raw is None or isinstance(raw, bool):
        return None
    try:
        number = int(raw)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def effective_outcome(status: Any, review_outcome: Any) -> str | None:
    """The reviewer's decision on the current revision, or ``None`` when there is none yet.

    The stored outcome wins. A row written before the outcome column existed
    has none, and then a status that is itself a decision is the outcome, so
    an old "approved" row still counts as approved.
    """
    stored = str(review_outcome or "").strip()
    if stored:
        return stored
    current = str(status or "").strip()
    return current if current in REVIEW_OUTCOMES else None


def default_review_code(outcome: Any) -> str | None:
    """The default stamp letter for an outcome, or ``None`` for no outcome."""
    return DEFAULT_REVIEW_CODES.get(str(outcome or "").strip())


def may_proceed(outcome: Any) -> bool:
    """Whether the outcome releases the work for ordering and installation."""
    return str(outcome or "").strip() in PROCEED_OUTCOMES


def days_in_review(status: Any, date_submitted: Any, date_returned: Any, as_of: Any) -> int | None:
    """Calendar days the current revision spent, or has so far spent, with the reviewer.

    Returned: submission to return. Still with the reviewer: submission to
    ``as_of``. Anything else (never submitted, or dates that run backwards)
    is ``None`` rather than a number that means nothing.
    """
    submitted = parse_day(date_submitted)
    if submitted is None:
        return None
    end = parse_day(date_returned)
    if end is None:
        if str(status or "") not in AWAITING_REVIEW_STATUSES:
            return None
        end = parse_day(as_of)
    if end is None or end < submitted:
        return None
    return (end - submitted).days


def review_due_date(date_submitted: Any, review_period_days: Any) -> date | None:
    """When the contract says the review is due, or ``None`` when that is unknown.

    Unknown means either the submittal was not submitted or no review period
    was recorded for it. There is no default period.
    """
    submitted = parse_day(date_submitted)
    period = _whole_number(review_period_days)
    if submitted is None or period is None:
        return None
    return submitted + timedelta(days=period)


def review_overdue_days(status: Any, date_submitted: Any, review_period_days: Any, as_of: Any) -> int | None:
    """Days the reviewer is past the contractual review period.

    Returns:
        ``None`` when the question cannot be answered or does not apply: the
        document is not with the reviewer, or no review period is recorded.
        Otherwise the number of days past the due date, ``0`` when not late.
    """
    if str(status or "") not in AWAITING_REVIEW_STATUSES:
        return None
    due = review_due_date(date_submitted, review_period_days)
    today = parse_day(as_of)
    if due is None or today is None:
        return None
    return max((today - due).days, 0)


def approval_needed_by(required_on_site_date: Any, lead_time_weeks: Any) -> date | None:
    """The last day an approval still lets the item arrive when the site needs it.

    Required on site less the lead time. ``None`` when either is missing: an
    item with no lead time recorded has no computable date, and guessing one
    would print a deadline nobody agreed.
    """
    on_site = parse_day(required_on_site_date)
    weeks = _whole_number(lead_time_weeks)
    if on_site is None or weeks is None:
        return None
    return on_site - timedelta(weeks=weeks)


def approval_late_days(status: Any, outcome: Any, needed_by: date | None, as_of: Any) -> int | None:
    """Days past the latest useful approval date, while the item is still not approved.

    Returns:
        ``None`` when there is no needed-by date or the question no longer
        applies (approved, or closed). Otherwise the days past it, ``0`` when
        the date has not come yet.
    """
    if needed_by is None or may_proceed(outcome) or str(status or "") not in APPROVAL_SCOPE_STATUSES:
        return None
    today = parse_day(as_of)
    if today is None:
        return None
    return max((today - needed_by).days, 0)


def submit_by_date(needed_by: date | None, review_period_days: Any) -> date | None:
    """The last day to submit so one full review still ends by the needed-by date."""
    period = _whole_number(review_period_days)
    if needed_by is None or period is None:
        return None
    return needed_by - timedelta(days=period)


# ── Review history ───────────────────────────────────────────────────────


def history_entry(
    *,
    revision: Any,
    outcome: str,
    code: str | None,
    date_submitted: Any,
    date_returned: Any,
    reviewer_id: Any,
    notes: str | None = None,
    resubmit_for_record: bool = False,
) -> dict[str, Any]:
    """One finished review cycle, as it is appended to ``review_history``.

    A revision is revised in place: resubmitting raises ``current_revision``
    and overwrites the dates. This entry is what is left of the revision that
    was replaced, and it is the link from a resubmission back to it.
    """
    return {
        "revision": _whole_number(revision) or 0,
        "outcome": outcome,
        "code": code or default_review_code(outcome),
        "date_submitted": str(date_submitted)[:10] if date_submitted else None,
        "date_returned": str(date_returned)[:10] if date_returned else None,
        "reviewer_id": str(reviewer_id) if reviewer_id else None,
        "notes": (notes or "").strip() or None,
        "resubmit_for_record": bool(resubmit_for_record),
    }


def _entries(history: Any) -> list[dict[str, Any]]:
    return [entry for entry in history if isinstance(entry, dict)] if isinstance(history, list) else []


def latest_history_entry(history: Any, revision: Any = None) -> dict[str, Any] | None:
    """The last recorded review, of one revision when ``revision`` is given."""
    entries = _entries(history)
    if revision is not None:
        wanted = _whole_number(revision)
        entries = [entry for entry in entries if _whole_number(entry.get("revision")) == wanted]
    return entries[-1] if entries else None


def review_stamp(
    submittal: Any,
    outcome: str,
    *,
    code: str | None,
    reviewer_id: Any,
    date_returned: Any,
    notes: str | None = None,
    resubmit_for_record: bool = False,
) -> dict[str, Any]:
    """The columns a review decision writes besides the status.

    Returned as a plain dict so the service adds it to the update it already
    builds. The history list is copied, never mutated in place: the ORM does
    not see an append to a JSON list it already holds.
    """
    mark = (code or "").strip() or default_review_code(outcome)
    history = list(_entries(getattr(submittal, "review_history", None)))
    history.append(
        history_entry(
            revision=getattr(submittal, "current_revision", None),
            outcome=outcome,
            code=mark,
            date_submitted=getattr(submittal, "date_submitted", None),
            date_returned=date_returned,
            reviewer_id=reviewer_id,
            notes=notes,
            # Only an approval as noted can owe a corrected copy for the record.
            resubmit_for_record=resubmit_for_record and outcome == "approved_as_noted",
        )
    )
    return {"review_outcome": outcome, "review_code": mark, "review_history": history}


def replaces_returned_revision(submittal: Any) -> bool:
    """Whether submitting now sends in a new revision of something already returned.

    True after revise and resubmit, and after a rejection that was taken back
    to draft: either way the reviewer already answered the current revision,
    so what goes in next is the one after it.
    """
    if str(getattr(submittal, "status", "") or "") == "revise_and_resubmit":
        return True
    return str(getattr(submittal, "review_outcome", "") or "") in ("revise_and_resubmit", "rejected")


# ── The register header ──────────────────────────────────────────────────


def summarise(items: Any, as_of: Any) -> dict[str, Any]:
    """Count a project's submittals the way the register header shows them.

    Every count is over the rows given, so the caller decides the scope. The
    by-code maps keep first-seen order and are not zero-filled: a discipline
    is free text, so there is no closed list to fill from.
    """
    by_status: dict[str, int] = {}
    by_type: dict[str, int] = {}
    by_discipline: dict[str, int] = {}
    by_outcome: dict[str, int] = dict.fromkeys(REVIEW_OUTCOMES, 0)
    counts = dict.fromkeys(
        (
            "total",
            "awaiting_review",
            "review_overdue",
            "review_period_unknown",
            "long_lead",
            "long_lead_awaiting_approval",
            "approval_late",
            "long_lead_without_lead_time",
        ),
        0,
    )
    for item in items:
        figures = track(item, as_of)
        status = str(getattr(item, "status", "") or "")
        counts["total"] += 1
        by_status[status] = by_status.get(status, 0) + 1
        kind = str(getattr(item, "submittal_type", "") or "")
        by_type[kind] = by_type.get(kind, 0) + 1
        discipline = str(getattr(item, "discipline", "") or "")
        by_discipline[discipline] = by_discipline.get(discipline, 0) + 1
        if figures.outcome:
            by_outcome[figures.outcome] = by_outcome.get(figures.outcome, 0) + 1
        if status in AWAITING_REVIEW_STATUSES:
            counts["awaiting_review"] += 1
            if figures.review_overdue_days is None:
                counts["review_period_unknown"] += 1
            elif figures.review_overdue_days > 0:
                counts["review_overdue"] += 1
        open_for_approval = status in APPROVAL_SCOPE_STATUSES and not figures.may_proceed
        if getattr(item, "long_lead", False):
            counts["long_lead"] += 1
            if open_for_approval:
                counts["long_lead_awaiting_approval"] += 1
                if figures.approval_needed_by is None:
                    counts["long_lead_without_lead_time"] += 1
        if figures.approval_late:
            counts["approval_late"] += 1
    return {
        **counts,
        "by_status": by_status,
        "by_type": by_type,
        "by_discipline": by_discipline,
        "by_outcome": by_outcome,
    }


# ── One row, answered ────────────────────────────────────────────────────


@dataclass(frozen=True)
class Tracking:
    """Everything derived for one submittal as of one day.

    ``None`` on any field means "cannot be said from what is recorded", which
    the API and the printed register pass on as an empty cell.
    """

    outcome: str | None
    code: str | None
    may_proceed: bool
    resubmit_for_record: bool
    days_in_review: int | None
    review_due_date: date | None
    review_overdue_days: int | None
    approval_needed_by: date | None
    approval_late_days: int | None
    submit_by_date: date | None

    @property
    def review_overdue(self) -> bool:
        return bool(self.review_overdue_days)

    @property
    def approval_late(self) -> bool:
        return bool(self.approval_late_days)


def track(item: Any, as_of: Any) -> Tracking:
    """Derive the register figures for a submittal row or anything shaped like one.

    Every attribute is read with a default, so a row from before these columns
    existed (all of them ``NULL``) and a plain namespace in a test both work.
    """
    status = getattr(item, "status", None)
    outcome = effective_outcome(status, getattr(item, "review_outcome", None))
    stored_code = str(getattr(item, "review_code", None) or "").strip()
    period = getattr(item, "review_period_days", None)
    needed_by = approval_needed_by(getattr(item, "required_on_site_date", None), getattr(item, "lead_time_weeks", None))
    current = latest_history_entry(getattr(item, "review_history", None), getattr(item, "current_revision", None))
    return Tracking(
        outcome=outcome,
        code=(stored_code or default_review_code(outcome)) if outcome else None,
        may_proceed=may_proceed(outcome),
        resubmit_for_record=bool(outcome == "approved_as_noted" and current and current.get("resubmit_for_record")),
        days_in_review=days_in_review(
            status, getattr(item, "date_submitted", None), getattr(item, "date_returned", None), as_of
        ),
        review_due_date=review_due_date(getattr(item, "date_submitted", None), period),
        review_overdue_days=review_overdue_days(status, getattr(item, "date_submitted", None), period, as_of),
        approval_needed_by=needed_by,
        approval_late_days=approval_late_days(status, outcome, needed_by, as_of),
        submit_by_date=submit_by_date(needed_by, period),
    )
