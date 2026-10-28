# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure, database-free site-supervision domain logic.

Everything here is side-effect free (except the explicit in-place refusal
helper) so it can be unit tested without a database and reused from the service,
a report generator or a test. It accepts either ORM instances or plain
dicts / namespaces for every visit and entry, so a caller need not construct a
session to reason about a supervision programme.

It answers the questions the design-side inspector actually asks:

- **plan vs fact** - how many visits were planned, how many conducted, which
  planned visits are overdue, and the completion ratio.
- **hidden-works register** - the acceptance-of-hidden-works items and whether
  each has been accepted (the AOSR-style handover gate).
- **motivated refusal** - mark an entry as a reasoned refusal, rejecting an
  empty reason.
- **change-sheet links** - the instructions and deviations that feed the change
  / MOC route.
- **structured export** - a neutral-keyed dict for a visit and its entries,
  ready to serialise to a supervision-log XML (no country-specific field names).
- **plan-coverage validation** (:func:`supervision_plan_coverage`) - every
  planned visit inside the window has an outcome and every hidden-works item is
  accepted, the gate the closeout check enforces.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

# ── Vocabulary (kept in sync with schemas; duplicated here so this module has
#    no dependency on Pydantic and stays import-cheap for unit tests). ────────

HIDDEN_WORKS = "hidden_works"
_ACCEPTED_ENTRY_STATUSES: frozenset[str] = frozenset({"addressed", "closed"})
_CHANGE_FEEDING_CATEGORIES: frozenset[str] = frozenset({"instruction", "deviation"})
_CONDUCTED_VISIT_STATUSES: frozenset[str] = frozenset({"conducted", "reported"})

# Neutral structured-record keys a supervision-log XML is built from.
_STRUCTURED_KEYS: tuple[str, ...] = ("element", "location", "norm_ref", "required_action")


def _get(obj: Any, name: str, default: Any = None) -> Any:
    """Read ``name`` from an ORM instance, dict or namespace."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _set(obj: Any, name: str, value: Any) -> None:
    """Write ``name`` on an ORM instance, dict or namespace."""
    if isinstance(obj, dict):
        obj[name] = value
    else:
        setattr(obj, name, value)


def _ref(obj: Any) -> str | None:
    """A stable reference for a visit / entry for reporting - its id if any."""
    value = _get(obj, "id")
    return str(value) if value is not None else None


def _as_date(value: Any) -> date | None:
    """Coerce a value to a ``date`` for comparison; ``None`` when not a date."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _iso(value: Any) -> str | None:
    """ISO string for a date / datetime, pass through other truthy values."""
    if isinstance(value, datetime | date):
        return value.isoformat()
    return value if value else None


def _visit_has_outcome(visit: Any) -> bool:
    """A visit has an outcome once conducted (actual date or conducted status)."""
    if _as_date(_get(visit, "actual_date")) is not None:
        return True
    return _get(visit, "status") in _CONDUCTED_VISIT_STATUSES


# ── plan vs fact ────────────────────────────────────────────────────────────


def plan_vs_fact(visits: list[Any], *, today: date | None = None) -> dict[str, Any]:
    """Planned-versus-conducted supervision figures.

    Args:
        visits: Supervision visits (ORM instances, dicts or namespaces).
        today: Reference date for overdue detection; defaults to UTC today.

    Returns:
        An explainable breakdown::

            {
                "total": int,
                "planned_count": int,        # a planned_date is set
                "conducted_count": int,      # an actual_date is set
                "reported_count": int,       # status == "reported"
                "overdue_count": int,
                "overdue_refs": list[str | None],
                "completion_ratio": float,   # conducted-of-planned / planned
                "defined": bool,             # False when nothing was planned
                "formula": str,
            }

        Never contains ``NaN``: with no planned visits the ratio is a
        well-defined ``0.0`` flagged ``defined=False``.
    """
    ref_today = today or datetime.now(UTC).date()

    planned_count = 0
    conducted_count = 0
    reported_count = 0
    conducted_of_planned = 0
    overdue_refs: list[str | None] = []

    for visit in visits:
        planned_date = _as_date(_get(visit, "planned_date"))
        has_outcome = _visit_has_outcome(visit)
        is_planned = planned_date is not None

        if is_planned:
            planned_count += 1
        if _as_date(_get(visit, "actual_date")) is not None:
            conducted_count += 1
        if _get(visit, "status") == "reported":
            reported_count += 1
        if is_planned and has_outcome:
            conducted_of_planned += 1
        # Overdue: was planned for a past date and never conducted.
        if is_planned and planned_date < ref_today and not has_outcome:
            overdue_refs.append(_ref(visit))

    defined = planned_count > 0
    completion_ratio = round(conducted_of_planned / planned_count, 4) if defined else 0.0

    return {
        "total": len(visits),
        "planned_count": planned_count,
        "conducted_count": conducted_count,
        "reported_count": reported_count,
        "overdue_count": len(overdue_refs),
        "overdue_refs": overdue_refs,
        "completion_ratio": completion_ratio,
        "defined": defined,
        "formula": "conducted_of_planned / planned_count",
    }


# ── hidden-works register ───────────────────────────────────────────────────


def hidden_works_register(entries: list[Any]) -> list[dict[str, Any]]:
    """The hidden-works acceptance items and whether each is accepted.

    An acceptance-of-hidden-works item is accepted once its status is
    ``addressed`` or ``closed``; ``open`` and ``refused_motivated`` are not.
    """
    register: list[dict[str, Any]] = []
    for entry in entries:
        if _get(entry, "category") != HIDDEN_WORKS:
            continue
        status = _get(entry, "status")
        register.append(
            {
                "ref": _ref(entry),
                "visit_id": (str(_get(entry, "visit_id")) if _get(entry, "visit_id") is not None else None),
                "ordinal": _get(entry, "ordinal", ""),
                "observation": _get(entry, "observation", ""),
                "status": status,
                "accepted": status in _ACCEPTED_ENTRY_STATUSES,
                "structured_fields": dict(_get(entry, "structured_fields") or {}),
            }
        )
    return register


# ── motivated refusal ───────────────────────────────────────────────────────


def motivated_refusal(entry: Any, reason: str) -> Any:
    """Mark ``entry`` as a motivated refusal, recording the required reason.

    Sets ``status='refused_motivated'`` and records the reason on the entry's
    ``structured_fields`` under ``refusal_reason``. A blank reason is rejected -
    a refusal without a stated ground is not a *motivated* refusal.

    Mutates and returns the entry so it works on an ORM instance in the service
    and on a namespace / dict in a unit test.

    Raises:
        ValueError: if ``reason`` is empty or whitespace-only.
    """
    cleaned = (reason or "").strip()
    if not cleaned:
        raise ValueError("A motivated refusal requires a reason.")

    fields = dict(_get(entry, "structured_fields") or {})
    fields["refusal_reason"] = cleaned
    _set(entry, "structured_fields", fields)
    _set(entry, "status", "refused_motivated")
    return entry


# ── change-sheet links ──────────────────────────────────────────────────────


def change_sheet_links(entries: list[Any]) -> list[dict[str, Any]]:
    """Instructions / deviations that carry a change reference.

    These are the observations that feed the change / MOC route: an instruction
    or a deviation with ``links_to_change_ref`` set.
    """
    links: list[dict[str, Any]] = []
    for entry in entries:
        if _get(entry, "category") not in _CHANGE_FEEDING_CATEGORIES:
            continue
        change_ref = _get(entry, "links_to_change_ref")
        if not change_ref:
            continue
        links.append(
            {
                "ref": _ref(entry),
                "ordinal": _get(entry, "ordinal", ""),
                "category": _get(entry, "category"),
                "status": _get(entry, "status"),
                "links_to_change_ref": change_ref,
            }
        )
    return links


# ── structured export ───────────────────────────────────────────────────────


def export_visit(visit: Any, entries: list[Any]) -> dict[str, Any]:
    """Serialise a visit and its entries to a neutral-keyed structured dict.

    Ready to hand to an XML serialiser (a supervision log / ЖАН-style record):
    the keys are jurisdiction-neutral (``element`` / ``location`` / ``norm_ref``
    / ``required_action``), never a country's field names. Dates are rendered as
    ISO strings so the payload is JSON-serialisable as-is.
    """
    visit_block = {
        "id": _ref(visit),
        "project_id": (str(_get(visit, "project_id")) if _get(visit, "project_id") is not None else None),
        "discipline": _get(visit, "discipline", "general"),
        "visitor": _get(visit, "visitor", ""),
        "planned_date": _iso(_get(visit, "planned_date")),
        "actual_date": _iso(_get(visit, "actual_date")),
        "status": _get(visit, "status", "planned"),
        "summary": _get(visit, "summary", ""),
        "photo_refs": list(_get(visit, "photo_refs") or []),
    }

    entry_blocks: list[dict[str, Any]] = []
    for entry in entries:
        structured = dict(_get(entry, "structured_fields") or {})
        block: dict[str, Any] = {
            "ordinal": _get(entry, "ordinal", ""),
            "category": _get(entry, "category"),
            "observation": _get(entry, "observation", ""),
            "status": _get(entry, "status"),
            "links_to_change_ref": _get(entry, "links_to_change_ref"),
        }
        for key in _STRUCTURED_KEYS:
            block[key] = structured.get(key)
        # Preserve any pack-specific extras under a nested key so nothing is lost.
        extras = {k: v for k, v in structured.items() if k not in _STRUCTURED_KEYS}
        if extras:
            block["extra"] = extras
        entry_blocks.append(block)

    return {
        "format_version": "1.0",
        "record_type": "site_supervision_visit",
        "visit": visit_block,
        "entries": entry_blocks,
    }


# ── plan-coverage validation ────────────────────────────────────────────────


def supervision_plan_coverage(
    visits: list[Any],
    entries: list[Any],
    *,
    today: date | None = None,
    window_end: date | None = None,
) -> dict[str, Any]:
    """Validate supervision plan coverage for closeout.

    The gate is twofold:

    1. **Every planned visit inside the window has an outcome.** A visit planned
       on or before ``window_end`` (default: ``today``) must have been conducted
       (an actual date, or a conducted / reported status). A planned visit still
       in the future is not yet due and does not fail.
    2. **Every hidden-works item is accepted.** Any acceptance-of-hidden-works
       entry that is not ``addressed`` / ``closed`` blocks closeout - hidden
       works cannot be signed off retrospectively once covered.

    Returns an explainable result::

        {
            "passed": bool,
            "planned_without_outcome": list[str | None],
            "hidden_works_not_accepted": list[str | None],
            "issues": list[str],
            "checked_visits": int,
            "checked_hidden_works": int,
        }
    """
    ref_today = today or datetime.now(UTC).date()
    ref_window = window_end or ref_today

    planned_without_outcome: list[str | None] = []
    checked_visits = 0
    for visit in visits:
        planned_date = _as_date(_get(visit, "planned_date"))
        if planned_date is None or planned_date > ref_window:
            continue  # not a due, planned visit
        checked_visits += 1
        if not _visit_has_outcome(visit):
            planned_without_outcome.append(_ref(visit))

    hidden_works_not_accepted: list[str | None] = []
    checked_hidden_works = 0
    for entry in entries:
        if _get(entry, "category") != HIDDEN_WORKS:
            continue
        checked_hidden_works += 1
        if _get(entry, "status") not in _ACCEPTED_ENTRY_STATUSES:
            hidden_works_not_accepted.append(_ref(entry))

    issues: list[str] = []
    if planned_without_outcome:
        issues.append(
            f"{len(planned_without_outcome)} planned supervision visit(s) inside the window have no recorded outcome."
        )
    if hidden_works_not_accepted:
        issues.append(f"{len(hidden_works_not_accepted)} hidden-works item(s) are not yet accepted.")

    return {
        "passed": not issues,
        "planned_without_outcome": planned_without_outcome,
        "hidden_works_not_accepted": hidden_works_not_accepted,
        "issues": issues,
        "checked_visits": checked_visits,
        "checked_hidden_works": checked_hidden_works,
    }


__all__ = [
    "change_sheet_links",
    "export_visit",
    "hidden_works_register",
    "motivated_refusal",
    "plan_vs_fact",
    "supervision_plan_coverage",
]
