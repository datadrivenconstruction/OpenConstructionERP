# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Adapters between schedule data and the pure diff-engine envelope.

:mod:`app.modules.schedule.diff_engine` compares two *normalized envelopes*
(plain dicts) and is deliberately ignorant of the ORM and of how baselines are
stored. This module is the thin, pure glue that builds such an envelope from a
live schedule's rows (:func:`live_envelope`) and that coerces an arbitrary,
client-captured ``ScheduleBaseline.snapshot_data`` blob into the same canonical
shape (:func:`normalize_envelope`).

Kept free of FastAPI / SQLAlchemy imports - it only reads attributes off
row-like objects and keys off plain dicts - so it imports under plain CPython
and is unit-testable without the app / DB. JSON-unsafe scalars (UUID, Decimal)
are stringified; the diff engine re-parses them with its tolerant coercers.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

# Activity attributes the diff engine knows how to compare. Anything missing on
# a given row is simply omitted (the engine treats an absent field as unchanged
# / empty), so this list can stay ahead of sparse rows safely.
_ACTIVITY_KEYS: tuple[str, ...] = (
    "id",
    "wbs_code",
    "name",
    "parent_id",
    "start_date",
    "end_date",
    "duration_days",
    "early_start",
    "early_finish",
    "late_start",
    "late_finish",
    "total_float",
    "free_float",
    "is_critical",
    "progress_pct",
    "status",
    "actual_start",
    "actual_finish",
    "cost_planned",
    "cost_actual",
    "constraint_type",
    "constraint_date",
    "calendar_id",
)


def _scalar(value: Any) -> Any:
    """Render a scalar JSON-safe without losing diff fidelity.

    ``bool`` / ``int`` / ``float`` / ``str`` pass through; everything else
    (UUID, Decimal, date-like) is stringified. The diff engine's tolerant
    parsers turn the strings back into Decimal / date for comparison.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def _activity_row(activity: Any) -> dict[str, Any]:
    """Flatten one ORM-ish activity into a diff-engine activity dict."""
    row: dict[str, Any] = {}
    for key in _ACTIVITY_KEYS:
        value = getattr(activity, key, None)
        if value is not None:
            row[key] = _scalar(value)
    # BOQ links ride along (the diff ignores them) so a revision-impact report
    # can name the positions of an activity the later plan removed.
    links = getattr(activity, "boq_position_ids", None)
    if isinstance(links, list) and links:
        row["boq_position_ids"] = [str(x) for x in links]
    return row


def _relationship_row(rel: Any) -> dict[str, Any]:
    """Flatten one ORM-ish relationship into a diff-engine relationship dict."""
    return {
        "predecessor_id": _scalar(getattr(rel, "predecessor_id", None)),
        "successor_id": _scalar(getattr(rel, "successor_id", None)),
        "relationship_type": getattr(rel, "relationship_type", None) or "FS",
        "lag_days": int(getattr(rel, "lag_days", 0) or 0),
    }


def _project_finish(activities: list) -> str | None:
    """Latest activity finish (ISO strings sort lexicographically)."""
    ends = [getattr(a, "end_date", None) for a in activities]
    ends = [e for e in ends if e]
    return max(str(e) for e in ends) if ends else None


def live_envelope(activities: list, relationships: list) -> dict[str, Any]:
    """Build a canonical diff envelope from a live schedule's rows."""
    env: dict[str, Any] = {
        "activities": [_activity_row(a) for a in activities],
        "relationships": [_relationship_row(r) for r in relationships],
        "calendars": {},
    }
    finish = _project_finish(activities)
    if finish is not None:
        env["project_finish"] = finish
    return env


def normalize_envelope(raw: Any) -> dict[str, Any]:
    """Coerce an arbitrary stored snapshot blob into a canonical envelope.

    Handles the shapes a captured ``snapshot_data`` may take:

    * the canonical ``{"activities": [...], "relationships": [...],
      "calendars": {...}}`` envelope (passed through);
    * a bare ``list`` of activity dicts;
    * a dict that nests activities under ``activities`` / ``tasks`` and links
      under ``relationships`` / ``links``;
    * a dict keyed by activity id whose values are activity dicts.

    Anything unrecognised degrades to an empty envelope (the diff then reports
    every activity on the other side as added / removed rather than raising).
    """
    empty: dict[str, Any] = {"activities": [], "relationships": [], "calendars": {}}
    if raw is None:
        return empty
    if isinstance(raw, list):
        return {"activities": list(raw), "relationships": [], "calendars": {}}
    if not isinstance(raw, dict):
        return empty

    activities = raw.get("activities")
    if activities is None:
        activities = raw.get("tasks")
    relationships = raw.get("relationships")
    if relationships is None:
        relationships = raw.get("links")
    calendars = raw.get("calendars")

    if activities is None:
        # A dict keyed by activity id -> activity dict.
        values = list(raw.values())
        if values and all(isinstance(v, dict) for v in values):
            activities = values
        else:
            activities = []

    env: dict[str, Any] = {
        "activities": list(activities) if isinstance(activities, list) else [],
        "relationships": list(relationships) if isinstance(relationships, list) else [],
        "calendars": calendars if isinstance(calendars, dict) else {},
    }
    if raw.get("project_finish"):
        env["project_finish"] = raw["project_finish"]
    return env
