# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure completeness and date-ordering checks for a submittal.

Validation is first-class for this module (platform principle #4). Submission
is the moment a submittal stops being the contractor's private draft and starts
consuming somebody else's review time, and it is the last point at which the
person who filed it is still looking at it. Everything after submission is
chasing: the register sorts by spec section, the overdue view counts days
against ``date_required``, and ball-in-court hands the item to
``reviewer_id``. A submittal filed without those is not merely incomplete, it
is invisible to every mechanism meant to move it along, and it surfaces again
only when the work it was blocking is already late.

Like ``procurement/validators.py`` this module is deliberately
**dependency-free**: standard library only (plus this module's own
``tracking``, which is standard library only too), no ORM, no FastAPI, no
session. The
rule classes in ``app.core.validation.rules`` stay thin wrappers translating a
:class:`Finding` into a ``RuleResult``, so the checks are unit-testable without
a database.

What is deliberately not checked here
-------------------------------------
Format. ``schemas.py`` already pins ``date_submitted`` / ``date_required`` /
``date_returned`` to ``^\\d{4}-\\d{2}-\\d{2}$`` and ``submittal_type`` to the
seven known types, so a rule re-checking either would pass forever and teach
the reader that it guards something it does not. These checks are about
ordering, ownership and reviewability, which no schema can express.

The clock is data, never ``date.today()``
-----------------------------------------
:data:`AS_OF_KEY` carries the date the checks treat as today. The service fills
it; a test passes it explicitly. A rule that asks the system clock what day it
is cannot be pinned by a test that still passes next year.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.modules.submittals.schemas import SUBMITTAL_TYPES
from app.modules.submittals.tracking import approval_late_days, approval_needed_by, effective_outcome

#: Payload key carrying the date the checks should consider "now".
AS_OF_KEY = "as_of"

#: A review shorter than this is not a review. Specifications normally allow
#: ten working days for a submittal review; fourteen calendar days is the same
#: window expressed without a working calendar, which this module does not have.
MIN_REVIEW_DAYS = 14


@dataclass(frozen=True)
class Finding:
    """One failed check on one submittal.

    :param element_ref: what the user should look at -- the submittal number,
        or its title when the number is missing. Never ``None``: a finding the
        UI cannot anchor is a finding the user cannot act on.
    :param params: placeholders for the translated message, pre-formatted as
        strings so the message layer never formats dates itself.
    :param details: machine-readable context for the report payload.
    """

    element_ref: str
    params: dict[str, str] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)


def parse_date(raw: Any) -> date | None:
    """Parse the leading ``YYYY-MM-DD`` of a date value, or ``None``.

    Anything unparseable is treated as absent rather than as a finding: the
    schema already refuses a malformed date at the API boundary, so a value
    that fails here came from a path with its own problem, and shouting about
    the format would bury the ordering question this module is asking.
    """
    if isinstance(raw, date):
        return raw
    text = str(raw or "").strip()
    if len(text) < 10:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _as_of(submittal: dict[str, Any]) -> date | None:
    """The date the checks treat as today, or ``None`` when the caller omitted it."""
    return parse_date(submittal.get(AS_OF_KEY))


def _ref(submittal: dict[str, Any]) -> str:
    number = str(submittal.get("submittal_number") or "").strip()
    if number:
        return number
    title = str(submittal.get("title") or "").strip()
    return title[:40] if title else str(submittal.get("id") or "?")


def _linked_items(submittal: dict[str, Any]) -> list[Any]:
    linked = submittal.get("linked_boq_item_ids")
    return [i for i in linked if str(i or "").strip()] if isinstance(linked, list) else []


# ── Checks ───────────────────────────────────────────────────────────────────


def check_reviewer_assigned(submittal: dict[str, Any]) -> list[Finding]:
    """A submitted submittal must name the reviewer it is waiting on.

    ``submit_submittal`` moves ball-in-court to ``reviewer_id`` only when one is
    set. Without it the submittal is submitted and in nobody's court: it appears
    on no reviewer's queue, and the only thing that will ever move it is
    somebody remembering it exists.
    """
    if str(submittal.get("reviewer_id") or "").strip():
        return []
    return [Finding(element_ref=_ref(submittal), details={"reviewer_id": None})]


def check_required_date_present(submittal: dict[str, Any]) -> list[Finding]:
    """A submitted submittal must carry the date the review is needed by.

    The overdue register counts days against ``date_required``; a submittal
    without one can never be reported late, however long it sits. Submission is
    exactly when that date is known, because it is driven by the work the
    submittal releases.
    """
    if parse_date(submittal.get("date_required")) is not None:
        return []
    return [Finding(element_ref=_ref(submittal), details={"date_required": None})]


def check_required_date_after_submitted(submittal: dict[str, Any]) -> list[Finding]:
    """The review cannot be due before the submittal was filed.

    Measured against ``date_submitted`` where it exists, otherwise against
    :data:`AS_OF_KEY`, because the service stamps ``date_submitted`` at the same
    moment this runs. A due date already in the past means the item is late on
    arrival and no reviewer can meet it.
    """
    required = parse_date(submittal.get("date_required"))
    if required is None:
        return []
    reference = parse_date(submittal.get("date_submitted")) or _as_of(submittal)
    if reference is None or required >= reference:
        return []
    return [
        Finding(
            element_ref=_ref(submittal),
            params={"required": required.isoformat(), "submitted": reference.isoformat()},
            details={
                "date_required": required.isoformat(),
                "reference_date": reference.isoformat(),
            },
        )
    ]


def check_review_window_sufficient(submittal: dict[str, Any]) -> list[Finding]:
    """The reviewer needs a workable window, not a nominal one.

    A due date a day or two after submission is a deadline nobody agreed to and
    the reviewer will miss it, which then reads as the reviewer's delay rather
    than as a scheduling problem in the submittal. WARNING rather than ERROR:
    genuinely urgent submittals exist, and this rule's job is to make the
    urgency a decision instead of an accident.
    """
    required = parse_date(submittal.get("date_required"))
    if required is None:
        return []
    reference = parse_date(submittal.get("date_submitted")) or _as_of(submittal)
    if reference is None or required < reference:
        # Already covered by :func:`check_required_date_after_submitted`;
        # reporting the same date pair twice would double-count one problem.
        return []
    days = (required - reference).days
    if days >= MIN_REVIEW_DAYS:
        return []
    return [
        Finding(
            element_ref=_ref(submittal),
            params={"days": str(days), "minimum": str(MIN_REVIEW_DAYS)},
            details={"review_days": days, "minimum_days": MIN_REVIEW_DAYS},
        )
    ]


def check_spec_section_present(submittal: dict[str, Any]) -> list[Finding]:
    """A submittal should say which part of the specification it answers.

    The register is filed and searched by spec section, and closeout is assembled
    from it. An unfiled submittal is found by scrolling, which at a few hundred
    items means it is not found at all. WARNING: the section is sometimes
    assigned by the reviewer rather than the submitter.
    """
    if str(submittal.get("spec_section") or "").strip():
        return []
    return [Finding(element_ref=_ref(submittal), details={"spec_section": None})]


def check_approver_distinct_from_reviewer(submittal: dict[str, Any]) -> list[Finding]:
    """Review and approval should not be the same person.

    The two-stage workflow exists so that a technical review is confirmed by
    somebody with the authority to accept the consequence. One person holding
    both roles gets the process without the second pair of eyes it was built
    for. WARNING, because small teams legitimately run short-handed.
    """
    reviewer = str(submittal.get("reviewer_id") or "").strip()
    approver = str(submittal.get("approver_id") or "").strip()
    if not reviewer or not approver or reviewer != approver:
        return []
    return [
        Finding(
            element_ref=_ref(submittal),
            params={"person": reviewer},
            details={"reviewer_id": reviewer, "approver_id": approver},
        )
    ]


def check_linked_scope_present(submittal: dict[str, Any]) -> list[Finding]:
    """A submittal should point at the scope it belongs to.

    ``linked_boq_item_ids`` is what lets the platform answer "what is still
    unapproved on this package"; without it the submittal is tracked but never
    rolls up, so a package can read as ready while an unreviewed submittal for
    it is still open. WARNING, since general submittals with no single BOQ owner
    are legitimate.
    """
    if _linked_items(submittal):
        return []
    return [Finding(element_ref=_ref(submittal), details={"linked_boq_item_ids": []})]


# ── The register: outcome, revision link, procurement dates ──────────────────
#
# These read the columns that make the submittal log a procurement tool: the
# reviewer's stamp, the review history, required on site and lead time. The
# arithmetic is the one the API and the printed register use
# (:mod:`app.modules.submittals.tracking`, also standard library only), so a
# finding and the figure next to it on the screen cannot disagree.

#: Statuses that are themselves a review decision.
_DECISION_STATUSES = frozenset({"approved", "approved_as_noted", "revise_and_resubmit", "rejected"})
#: Statuses in which the current revision has not been answered yet.
_UNANSWERED_STATUSES = frozenset({"submitted", "under_review"})
#: Submittal types that offer a product somebody manufactures.
#: Named one at a time and checked against the module's one list of types, so
#: a type renamed there fails here at import instead of silently never matching.
_PRODUCT_DATA = "product_data"
_SAMPLE = "sample"
MATERIAL_TYPES = frozenset((_PRODUCT_DATA, _SAMPLE))
if not MATERIAL_TYPES.issubset(SUBMITTAL_TYPES):  # pragma: no cover - import-time guard
    raise RuntimeError(f"material types {sorted(MATERIAL_TYPES)} are not all submittal types")


def _whole(raw: Any) -> int | None:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        number = int(raw)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def check_resubmission_linked(submittal: dict[str, Any]) -> list[Finding]:
    """A resubmission must be traceable to the revision it replaces.

    Revisions are revised in place, so the only trace of revision 1 once
    revision 2 is in is its entry in ``review_history``: what was stamped on
    it, when it went in and when it came back. A submittal at revision 2 or
    later with no entry for the revision before is a resubmission whose
    reason nobody can read, which happens when the revision number is typed
    in rather than reached through a review. WARNING: the record is thin, the
    submittal itself may be perfectly good.
    """
    revision = _whole(submittal.get("current_revision"))
    if revision is None or revision < 2:
        return []
    history = submittal.get("review_history")
    reviewed = (
        {_whole(entry.get("revision")) for entry in history if isinstance(entry, dict)}
        if isinstance(history, list)
        else set()
    )
    if revision - 1 in reviewed:
        return []
    return [
        Finding(
            element_ref=_ref(submittal),
            params={"revision": str(revision), "previous": str(revision - 1)},
            details={"current_revision": revision, "reviewed_revisions": sorted(r for r in reviewed if r is not None)},
        )
    ]


def check_outcome_matches_status(submittal: dict[str, Any]) -> list[Finding]:
    """The stamp and the workflow status must tell the same story.

    Three ways they cannot: a status that is a decision with a different
    decision stamped; a document still with the reviewer that already carries
    a stamp; a closed submittal stamped "revise and resubmit", which the
    workflow never closes. No stamp at all is not a contradiction: rows from
    before the stamp was stored have none.
    """
    outcome = str(submittal.get("review_outcome") or "").strip()
    if not outcome:
        return []
    status = str(submittal.get("status") or "").strip()
    contradicts = (
        (status in _DECISION_STATUSES and status != outcome)
        or status in _UNANSWERED_STATUSES
        or (status == "closed" and outcome == "revise_and_resubmit")
    )
    if not contradicts:
        return []
    return [
        Finding(
            element_ref=_ref(submittal),
            params={"outcome": outcome, "status": status},
            details={"review_outcome": outcome, "status": status},
        )
    ]


def check_required_on_site_after_submitted(submittal: dict[str, Any]) -> list[Finding]:
    """An item cannot be needed on site before its submittal was even filed.

    Measured against ``date_submitted`` only. A draft has no submission date
    and the planner is still free to set one that works.
    """
    on_site = parse_date(submittal.get("required_on_site_date"))
    submitted = parse_date(submittal.get("date_submitted"))
    if on_site is None or submitted is None or on_site >= submitted:
        return []
    return [
        Finding(
            element_ref=_ref(submittal),
            params={"on_site": on_site.isoformat(), "submitted": submitted.isoformat()},
            details={"required_on_site_date": on_site.isoformat(), "date_submitted": submitted.isoformat()},
        )
    ]


def check_long_lead_has_lead_time(submittal: dict[str, Any]) -> list[Finding]:
    """A long-lead item must say how long the lead is.

    The flag alone moves nothing: the date an approval is needed by is
    required on site less the lead time, and without the lead time there is
    no such date, so the one item that most needs chasing drops out of the
    late list.
    """
    if submittal.get("long_lead") is not True or _whole(submittal.get("lead_time_weeks")) is not None:
        return []
    return [Finding(element_ref=_ref(submittal), details={"long_lead": True, "lead_time_weeks": None})]


def check_approval_needed_by_not_passed(submittal: dict[str, Any]) -> list[Finding]:
    """Past required on site less lead time, an item not yet approved is already late.

    From that day every further day in review is a day the delivery slips.
    WARNING, with the number of days: nothing about the submittal is wrong,
    the programme is.
    """
    needed_by = approval_needed_by(submittal.get("required_on_site_date"), submittal.get("lead_time_weeks"))
    status = submittal.get("status")
    outcome = effective_outcome(status, submittal.get("review_outcome"))
    late = approval_late_days(status, outcome, needed_by, submittal.get(AS_OF_KEY))
    if not late or needed_by is None:
        return []
    return [
        Finding(
            element_ref=_ref(submittal),
            params={"days": str(late), "needed_by": needed_by.isoformat()},
            details={"approval_needed_by": needed_by.isoformat(), "days_late": late, "status": str(status or "")},
        )
    ]


def check_material_has_manufacturer(submittal: dict[str, Any]) -> list[Finding]:
    """A material submittal should name who makes the product.

    The reviewer approves a product from a manufacturer, not a description,
    and the approved-brand list is built from this field. WARNING: a generic
    material is sometimes submitted before the brand is chosen.
    """
    if str(submittal.get("submittal_type") or "") not in MATERIAL_TYPES:
        return []
    if str(submittal.get("manufacturer") or "").strip():
        return []
    return [Finding(element_ref=_ref(submittal), details={"manufacturer": None})]
