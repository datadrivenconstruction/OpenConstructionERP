# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure, database-free logic for meeting minutes and the action register.

Everything here is a pure function: given the same input it returns the same
output and never touches a database, ORM, network, or FastAPI. That keeps the
two hard parts of this feature - action-item carry-over across a recurring
series, and building a structured minutes document - trivially unit-testable
and easy for a site engineer to reason about.

Two ideas power the whole feature:

- **Carry-over.** An action raised in an earlier meeting of the same series
  keeps showing up in later meetings as "brought forward" until someone marks
  it done or cancelled. Because each action is one row, closing it once closes
  it for the entire series.
- **Minutes.** From a meeting's agenda plus the discussion and decision
  captured against each item, we assemble a plain document: who was present and
  absent, what was discussed and decided per agenda item, the action items, and
  the next meeting date. It is a draft a human confirms before it is issued.

Action statuses used across the register are ``open``, ``in_progress``,
``done`` and ``cancelled``. Only ``open`` and ``in_progress`` actions carry
forward; only they can be overdue.
"""

from __future__ import annotations

from datetime import date
from typing import Any

# The four canonical action-register statuses. ``open`` and ``in_progress`` are
# the two "still live" statuses that carry forward and can be overdue.
ACTION_STATUSES: tuple[str, ...] = ("open", "in_progress", "done", "cancelled")
LIVE_ACTION_STATUSES: tuple[str, ...] = ("open", "in_progress")

# Map the legacy ``Meeting.action_items`` JSON statuses (open/completed/
# cancelled) onto the richer register statuses when seeding.
_LEGACY_STATUS_MAP: dict[str, str] = {
    "open": "open",
    "in_progress": "in_progress",
    "completed": "done",
    "done": "done",
    "cancelled": "cancelled",
}

# A due date that sorts after every real date, used so actions without a due
# date fall to the bottom of a list ordered by urgency.
_FAR_FUTURE = "9999-12-31"


# ── Dates ────────────────────────────────────────────────────────────────────


def parse_iso_date(value: Any) -> date | None:  # noqa: ANN401 - accepts loose input
    """Parse an ISO 8601 date, returning ``None`` on anything unparseable.

    Accepts a ``date``, a ``datetime`` (its date part is used), or a string
    whose first 10 characters are ``YYYY-MM-DD``. Empty, ``None`` or malformed
    input returns ``None`` rather than raising, so one bad row never breaks a
    whole aggregation.
    """
    from datetime import datetime

    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def is_iso_date(value: Any) -> bool:  # noqa: ANN401 - accepts loose input
    """Return whether ``value`` is a parseable ISO 8601 date."""
    return parse_iso_date(value) is not None


def _date_before(a: Any, b: Any) -> bool:  # noqa: ANN401 - accepts loose input
    """Return whether date ``a`` is strictly before date ``b``.

    Unparseable dates return ``False`` (they cannot be ordered).
    """
    da = parse_iso_date(a)
    db = parse_iso_date(b)
    if da is None or db is None:
        return False
    return da < db


# ── Action helpers ───────────────────────────────────────────────────────────


def normalize_action_status(value: Any) -> str:  # noqa: ANN401 - accepts loose input
    """Coerce any status word into one of :data:`ACTION_STATUSES`.

    Legacy statuses (``completed``) map onto the register equivalent
    (``done``). Anything unrecognized falls back to ``open``.
    """
    norm = str(value or "open").strip().lower() or "open"
    return _LEGACY_STATUS_MAP.get(norm, norm if norm in ACTION_STATUSES else "open")


def action_is_live(status: Any) -> bool:  # noqa: ANN401 - accepts loose input
    """Return whether an action is still live (open or in progress)."""
    return normalize_action_status(status) in LIVE_ACTION_STATUSES


def action_is_overdue(
    due_date: Any,  # noqa: ANN401 - accepts str/date/datetime/None
    reference_date: Any,  # noqa: ANN401 - accepts str/date/datetime/None
    status: Any = "open",  # noqa: ANN401
    *,
    grace_days: int = 0,
) -> bool:
    """Return whether a live action is overdue at ``reference_date``.

    An action is overdue only when it is still live (open or in progress), has
    a parseable due date, the reference date is parseable, and the due date
    plus ``grace_days`` is strictly before the reference date. Done and
    cancelled actions are never overdue. Any unparseable date returns
    ``False``.
    """
    from datetime import timedelta

    if not action_is_live(status):
        return False
    due = parse_iso_date(due_date)
    ref = parse_iso_date(reference_date)
    if due is None or ref is None:
        return False
    if grace_days:
        due = due + timedelta(days=int(grace_days))
    return due < ref


def annotate_action(
    action: dict[str, Any],
    reference_date: Any,  # noqa: ANN401 - accepts str/date/datetime/None
    *,
    grace_days: int = 0,
    brought_forward: bool = False,
) -> dict[str, Any]:
    """Return a copy of an action dict with ``overdue`` and ``brought_forward``.

    The input is never mutated. ``overdue`` is derived from the action's status
    and due date against ``reference_date``.
    """
    return {
        **action,
        "status": normalize_action_status(action.get("status")),
        "overdue": action_is_overdue(
            action.get("due_date"),
            reference_date,
            action.get("status"),
            grace_days=grace_days,
        ),
        "brought_forward": brought_forward,
    }


def _action_sort_key(action: dict[str, Any]) -> tuple[str, str]:
    """Order actions by due date (soonest first), then origin meeting date."""
    due = str(action.get("due_date") or _FAR_FUTURE)
    origin = str(action.get("origin_meeting_date") or _FAR_FUTURE)
    return (due, origin)


def split_actions_for_meeting(
    actions: list[dict[str, Any]],
    target_meeting_id: str,
    target_meeting_date: Any,  # noqa: ANN401 - accepts str/date/datetime/None
    reference_date: Any,  # noqa: ANN401 - accepts str/date/datetime/None
    *,
    grace_days: int = 0,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split a series' actions into this meeting's own and its brought-forward.

    Args:
        actions: Serialized action rows for the whole series (or just this
            meeting for a one-off). Each carries ``origin_meeting_id``,
            ``origin_meeting_date``, ``status`` and ``due_date``.
        target_meeting_id: The meeting being viewed.
        target_meeting_date: Its ISO date, used to decide "earlier in series".
        reference_date: Date to judge overdue against (typically today).
        grace_days: Slack added to a due date before it counts as overdue.

    Returns:
        ``(own, brought_forward)``. ``own`` are actions raised in this meeting.
        ``brought_forward`` are still-live actions raised in an *earlier*
        meeting of the same series that have not been closed - each flagged
        ``brought_forward=True``. Closed actions from other meetings appear in
        neither list (they live in the series register).
    """
    own: list[dict[str, Any]] = []
    brought: list[dict[str, Any]] = []
    for action in actions:
        origin_id = str(action.get("origin_meeting_id") or "")
        if origin_id == str(target_meeting_id):
            own.append(annotate_action(action, reference_date, grace_days=grace_days))
            continue
        # From another meeting: only still-live actions raised strictly earlier
        # carry forward into this meeting.
        if action_is_live(action.get("status")) and _date_before(
            action.get("origin_meeting_date"), target_meeting_date
        ):
            brought.append(
                annotate_action(
                    action,
                    reference_date,
                    grace_days=grace_days,
                    brought_forward=True,
                )
            )
    own.sort(key=_action_sort_key)
    brought.sort(key=_action_sort_key)
    return own, brought


def summarize_register(
    actions: list[dict[str, Any]],
    reference_date: Any,  # noqa: ANN401 - accepts str/date/datetime/None
    *,
    grace_days: int = 0,
) -> dict[str, int]:
    """Count actions by status plus the number of overdue live actions.

    Returns a dict with keys ``total``, ``open``, ``in_progress``, ``done``,
    ``cancelled`` and ``overdue``. Always present, always non-negative.
    """
    counts = {"total": 0, "open": 0, "in_progress": 0, "done": 0, "cancelled": 0, "overdue": 0}
    for action in actions:
        status = normalize_action_status(action.get("status"))
        counts["total"] += 1
        counts[status] = counts.get(status, 0) + 1
        if action_is_overdue(action.get("due_date"), reference_date, status, grace_days=grace_days):
            counts["overdue"] += 1
    return counts


# ── Validation (pure) ────────────────────────────────────────────────────────


def validate_action_fields(
    owner_id: str | None,
    owner_name: str | None,
    due_date: str | None,
    status: str | None,
) -> list[str]:
    """Return a list of plain-language problems with an action item.

    A live action item must have an owner and a due date - that is the whole
    point of tracking it. An empty list means the action is valid.
    """
    problems: list[str] = []
    has_owner = bool((owner_id or "").strip()) or bool((owner_name or "").strip())
    if not has_owner:
        problems.append("An action item needs an owner.")
    if not due_date or not is_iso_date(due_date):
        problems.append("An action item needs a due date (YYYY-MM-DD).")
    if normalize_action_status(status) not in ACTION_STATUSES:
        problems.append(f"Status must be one of: {', '.join(ACTION_STATUSES)}.")
    return problems


def minutes_issue_problems(content: dict[str, Any]) -> list[str]:
    """Return blocking problems that stop minutes from being issued.

    Minutes cannot be issued while a required agenda item is unaddressed (no
    discussion and no decision recorded), or while no attendee is marked
    present. An empty list means the minutes are ready to issue.
    """
    problems: list[str] = []
    agenda = content.get("agenda") or []
    for item in agenda:
        if not isinstance(item, dict):
            continue
        if not item.get("required"):
            continue
        discussed = bool(str(item.get("discussion") or "").strip())
        decided = bool(str(item.get("decision") or "").strip())
        if not discussed and not decided:
            label = str(item.get("topic") or item.get("number") or "").strip() or "an item"
            problems.append(f"Required agenda item '{label}' has no discussion or decision recorded.")
    if not (content.get("attendees_present") or []):
        problems.append("Minutes need at least one attendee marked present.")
    return problems


# ── Minutes content builder (pure) ───────────────────────────────────────────


def _attendee_entry(att: dict[str, Any]) -> dict[str, str]:
    return {
        "name": str(att.get("name") or "").strip(),
        "company": str(att.get("company") or att.get("role") or "").strip(),
    }


def _action_line(action: dict[str, Any]) -> dict[str, Any]:
    """Flatten a serialized action into the minutes' action-line shape."""
    owner = str(action.get("owner_name") or action.get("owner_id") or "").strip()
    return {
        "description": str(action.get("description") or "").strip(),
        "owner": owner,
        "due_date": action.get("due_date"),
        "status": normalize_action_status(action.get("status")),
        "overdue": bool(action.get("overdue")),
        "brought_forward": bool(action.get("brought_forward")),
        "origin_meeting_number": action.get("origin_meeting_number") or "",
    }


def build_minutes_content(
    meeting: dict[str, Any],
    own_actions: list[dict[str, Any]],
    brought_actions: list[dict[str, Any]],
    checked_in_keys: set[str] | None = None,
    next_meeting_date: str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build the structured minutes document from a meeting and its actions.

    Pure and deterministic. ``meeting`` is a plain dict of the meeting fields
    (title, meeting_number, meeting_type, meeting_date, location, chairperson,
    attendees, agenda_items, minutes, metadata). An attendee is counted present
    when their own status says ``present`` or when their name / id appears in
    ``checked_in_keys`` (from signed attendance check-ins). Brought-forward
    actions are listed first so open follow-ups from earlier meetings lead.

    Returns:
        A JSON-friendly dict ready to store on ``MeetingMinutes.content`` and
        render in the UI or a PDF.
    """
    keys = checked_in_keys or set()

    present: list[dict[str, str]] = []
    absent: list[dict[str, str]] = []
    for att in meeting.get("attendees") or []:
        if not isinstance(att, dict):
            continue
        entry = _attendee_entry(att)
        status = str(att.get("status") or "present").strip().lower()
        checked_in = bool(entry["name"] and entry["name"] in keys) or bool(
            att.get("user_id") and str(att.get("user_id")) in keys
        )
        (present if (status == "present" or checked_in) else absent).append(entry)

    agenda: list[dict[str, Any]] = []
    for idx, item in enumerate(meeting.get("agenda_items") or [], 1):
        if not isinstance(item, dict):
            continue
        agenda.append(
            {
                "number": str(item.get("number") or idx),
                "topic": str(item.get("topic") or item.get("title") or "").strip(),
                "presenter": str(item.get("presenter") or "").strip(),
                "discussion": str(item.get("discussion") or item.get("notes") or "").strip(),
                "decision": str(item.get("decision") or "").strip(),
                "required": bool(item.get("required")),
            }
        )

    action_items = [_action_line(a) for a in brought_actions] + [_action_line(a) for a in own_actions]

    decisions: list[str] = [a["decision"] for a in agenda if a["decision"]]
    meta = meeting.get("metadata") or {}
    for dec in meta.get("decisions") or []:
        if isinstance(dec, dict):
            text = str(dec.get("decision") or "").strip()
        else:
            text = str(dec or "").strip()
        if text:
            decisions.append(text)
    open_questions: list[str] = []
    for item in meta.get("open_questions") or []:
        text = str(item.get("question") or "").strip() if isinstance(item, dict) else str(item or "").strip()
        if text:
            open_questions.append(text)

    return {
        "title": str(meeting.get("title") or "").strip(),
        "meeting_number": str(meeting.get("meeting_number") or ""),
        "meeting_type": str(meeting.get("meeting_type") or ""),
        "meeting_date": meeting.get("meeting_date"),
        "location": str(meeting.get("location") or "").strip(),
        "chairperson": str(meeting.get("chairperson") or "").strip(),
        "attendees_present": present,
        "attendees_absent": absent,
        "agenda": agenda,
        "action_items": action_items,
        "decisions": decisions,
        "open_questions": open_questions,
        "next_meeting_date": next_meeting_date,
        "summary": str(meeting.get("minutes") or "").strip(),
        "language": str(meta.get("language") or "").strip() or None,
        "generated_at": generated_at,
    }
