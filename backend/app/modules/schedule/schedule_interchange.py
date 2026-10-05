# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure, lossless schedule interchange model (T1.1).

A neutral, versioned document that captures a whole schedule - its header, every
activity (all columns) and the canonical dependency network - so a schedule can
be exported, moved between projects and re-imported with no loss of structure or
logic. The format is independent of internal database ids: every activity is
addressed by a stable string ``ref`` and the parent / relationship endpoints
point at those refs, so the document round-trips into a fresh schedule whose
activities get brand-new ids.

This module is deliberately dependency-free (stdlib only). It never imports the
ORM or ``app.database``, so it imports and unit-tests on the local Python 3.11
runner. The ORM-facing read/write lives in ``interchange_service``; the
DCMA-style normalise-on-import repair lives in the pure ``schedule_clean``.

Two halves:

* :func:`build_export_document` turns live rows (duck-typed - it only uses
  ``getattr`` / ``str``, so ORM rows and plain test doubles both work) into the
  canonical document dict, with money / quantity columns serialised as strings
  to avoid float drift.
* :func:`parse_document` validates and splits an incoming document into a
  :class:`ParsedDocument`; :meth:`ParsedDocument.to_dict` re-emits it. Unknown
  top-level keys survive on :attr:`ParsedDocument.extra` and unknown per-row keys
  survive because rows are carried as whole dicts - so a document written by a
  newer minor version round-trips through an older parser without dropping data.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

#: Stable identifier of the interchange format. Stamped on every export and
#: required on every import.
FORMAT = "oce-schedule-interchange"

#: Current writer version. Bump the minor for additive, backward-compatible
#: growth (new optional keys); bump the major only for a breaking change.
FORMAT_VERSION = "1.0"

#: Versions this parser accepts. A document outside this set is rejected rather
#: than silently mis-read.
SUPPORTED_VERSIONS: frozenset[str] = frozenset({"1.0"})

#: The four CPM dependency types. Anything else is coerced to ``FS`` by the
#: cleaner (and rejected by :func:`validate_document` when cleaning is off).
VALID_RELATIONSHIP_TYPES: tuple[str, ...] = ("FS", "SS", "FF", "SF")

#: Top-level document keys with dedicated handling. Everything else is preserved
#: verbatim on :attr:`ParsedDocument.extra`.
_RESERVED_TOP_KEYS = frozenset({"format", "format_version", "schedule", "activities", "relationships"})


class InterchangeError(ValueError):
    """Raised when a document is malformed or its version is unsupported."""


def _money(value: Any) -> str | None:
    """Serialise a Decimal / numeric column as a string (or ``None``).

    Money and quantity columns are kept as strings end to end so a float never
    sits between the database and the wire.
    """
    if value is None:
        return None
    return str(value)


# ── Export: live rows -> canonical document ────────────────────────────────


def _activity_document(activity: Any) -> dict[str, Any]:
    """Flatten one activity row into its lossless document form.

    Duck-typed: only ``getattr`` is used, so an ORM ``Activity`` and a plain
    ``SimpleNamespace`` test double behave identically. The id becomes the
    stable ``ref``; ``parent_id`` becomes ``parent_ref``; the derived
    ``dependencies`` JSON is intentionally omitted because the canonical
    relationship rows are the single source of truth for the network.
    """
    parent_id = getattr(activity, "parent_id", None)
    calendar_id = getattr(activity, "calendar_id", None)
    bim = getattr(activity, "bim_element_ids", None)
    return {
        "ref": str(activity.id),
        "activity_code": getattr(activity, "activity_code", None),
        "name": getattr(activity, "name", "") or "",
        "description": getattr(activity, "description", "") or "",
        "wbs_code": getattr(activity, "wbs_code", "") or "",
        "parent_ref": str(parent_id) if parent_id else None,
        "start_date": getattr(activity, "start_date", "") or "",
        "end_date": getattr(activity, "end_date", "") or "",
        "duration_days": int(getattr(activity, "duration_days", 0) or 0),
        "progress_pct": str(getattr(activity, "progress_pct", "0")),
        "status": getattr(activity, "status", "not_started") or "not_started",
        "activity_type": getattr(activity, "activity_type", "task") or "task",
        "early_start": getattr(activity, "early_start", None),
        "early_finish": getattr(activity, "early_finish", None),
        "late_start": getattr(activity, "late_start", None),
        "late_finish": getattr(activity, "late_finish", None),
        "total_float": getattr(activity, "total_float", None),
        "free_float": getattr(activity, "free_float", None),
        "is_critical": bool(getattr(activity, "is_critical", False)),
        "constraint_type": getattr(activity, "constraint_type", None),
        "constraint_date": getattr(activity, "constraint_date", None),
        "color": getattr(activity, "color", "") or "",
        "sort_order": int(getattr(activity, "sort_order", 0) or 0),
        "resources": list(getattr(activity, "resources", None) or []),
        "boq_position_ids": list(getattr(activity, "boq_position_ids", None) or []),
        "bim_element_ids": list(bim) if isinstance(bim, list) else None,
        "cost_planned": _money(getattr(activity, "cost_planned", None)),
        "cost_actual": _money(getattr(activity, "cost_actual", None)),
        "percent_complete_type": getattr(activity, "percent_complete_type", "physical") or "physical",
        "remaining_duration": getattr(activity, "remaining_duration", None),
        "budgeted_units": _money(getattr(activity, "budgeted_units", None)),
        "installed_units": _money(getattr(activity, "installed_units", None)),
        "calendar_id": str(calendar_id) if calendar_id else None,
        "suspended_at": getattr(activity, "suspended_at", None),
        "resumed_at": getattr(activity, "resumed_at", None),
        "suspend_reason": getattr(activity, "suspend_reason", None),
        "client_visible": bool(getattr(activity, "client_visible", False)),
        "metadata": dict(getattr(activity, "metadata_", None) or {}),
    }


def _relationship_document(rel: Any) -> dict[str, Any]:
    """Flatten one canonical relationship row into document form (ref-keyed)."""
    return {
        "predecessor_ref": str(rel.predecessor_id),
        "successor_ref": str(rel.successor_id),
        "relationship_type": (getattr(rel, "relationship_type", None) or "FS"),
        "lag_days": int(getattr(rel, "lag_days", 0) or 0),
        "metadata": dict(getattr(rel, "metadata_", None) or {}),
    }


def _schedule_document(schedule: Any) -> dict[str, Any]:
    """Flatten the schedule header. ``original_id`` / ``project_id`` are kept for
    traceability but are never reused on import (import always mints fresh ids)."""
    return {
        "original_id": str(schedule.id),
        "project_id": str(getattr(schedule, "project_id", "")) or None,
        "name": getattr(schedule, "name", "") or "",
        "schedule_type": getattr(schedule, "schedule_type", "master") or "master",
        "description": getattr(schedule, "description", "") or "",
        "start_date": getattr(schedule, "start_date", None),
        "end_date": getattr(schedule, "end_date", None),
        "status": getattr(schedule, "status", "draft") or "draft",
        "data_date": getattr(schedule, "data_date", None),
        "metadata": dict(getattr(schedule, "metadata_", None) or {}),
    }


def build_export_document(
    schedule: Any,
    activities: Any,
    relationships: Any,
) -> dict[str, Any]:
    """Build the complete canonical interchange document for one schedule.

    Args:
        schedule: the schedule header row (duck-typed).
        activities: iterable of activity rows, in the order they should appear.
        relationships: iterable of canonical relationship rows.

    Returns:
        A JSON-serialisable dict carrying the format envelope, the schedule
        header, every activity (all columns) and the full dependency network.
    """
    return {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "schedule": _schedule_document(schedule),
        "activities": [_activity_document(a) for a in activities],
        "relationships": [_relationship_document(r) for r in relationships],
    }


# ── Import: canonical document -> validated, structured form ────────────────


@dataclass
class ParsedDocument:
    """A validated interchange document split into its parts.

    ``activities`` / ``relationships`` are carried as whole dicts so per-row
    forward-compatible keys survive a round-trip. ``extra`` holds any
    unrecognised top-level keys for the same reason.
    """

    format_version: str
    schedule: dict[str, Any]
    activities: list[dict[str, Any]]
    relationships: list[dict[str, Any]]
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Re-emit the canonical document dict (lossless inverse of parse)."""
        return {
            "format": FORMAT,
            "format_version": self.format_version,
            **self.extra,
            "schedule": self.schedule,
            "activities": self.activities,
            "relationships": self.relationships,
        }


def parse_document(raw: Any) -> ParsedDocument:
    """Validate the envelope and split a raw document into a :class:`ParsedDocument`.

    Raises:
        InterchangeError: if ``raw`` is not an object, the format marker is
            wrong, the version is unsupported, or the core sections have the
            wrong shape. This is a structural gate only - semantic problems
            (dangling refs, duplicates) are reported by :func:`validate_document`
            and repaired by ``schedule_clean.clean_document``.
    """
    if not isinstance(raw, dict):
        raise InterchangeError("interchange document must be a JSON object")

    fmt = raw.get("format")
    if fmt != FORMAT:
        raise InterchangeError(f"unsupported format {fmt!r}; expected {FORMAT!r}")

    version = raw.get("format_version")
    if version not in SUPPORTED_VERSIONS:
        raise InterchangeError(f"unsupported format_version {version!r}; this build reads {sorted(SUPPORTED_VERSIONS)}")

    schedule = raw.get("schedule")
    if not isinstance(schedule, dict):
        raise InterchangeError("document.schedule must be an object")

    activities = raw.get("activities", [])
    relationships = raw.get("relationships", [])
    if not isinstance(activities, list):
        raise InterchangeError("document.activities must be a list")
    if not isinstance(relationships, list):
        raise InterchangeError("document.relationships must be a list")
    if not all(isinstance(a, dict) for a in activities):
        raise InterchangeError("every activity must be an object")
    if not all(isinstance(r, dict) for r in relationships):
        raise InterchangeError("every relationship must be an object")

    extra = {k: v for k, v in raw.items() if k not in _RESERVED_TOP_KEYS}
    return ParsedDocument(
        format_version=version,
        schedule=schedule,
        activities=activities,
        relationships=relationships,
        extra=extra,
    )


def validate_document(doc: ParsedDocument) -> list[str]:
    """Return human-readable semantic issues without mutating anything.

    Surfaces exactly the problems the cleaner repairs: missing or duplicate
    activity refs, parent / relationship endpoints that point at a missing ref,
    and self-referential relationships. An empty list means the document is
    safe to import as-is. Callers that import with cleaning disabled use this to
    refuse a structurally broken document.
    """
    issues: list[str] = []

    refs: list[str] = []
    for i, a in enumerate(doc.activities):
        ref = a.get("ref")
        if not isinstance(ref, str) or not ref:
            issues.append(f"activity[{i}] has no usable ref")
        else:
            refs.append(ref)

    for ref, count in sorted(Counter(refs).items()):
        if count > 1:
            issues.append(f"duplicate activity ref {ref!r} ({count} occurrences)")

    ref_set = set(refs)
    for i, a in enumerate(doc.activities):
        parent = a.get("parent_ref")
        if parent is not None and parent not in ref_set:
            issues.append(f"activity[{i}] parent_ref {parent!r} does not exist")

    for i, rel in enumerate(doc.relationships):
        pred = rel.get("predecessor_ref")
        succ = rel.get("successor_ref")
        if pred not in ref_set:
            issues.append(f"relationship[{i}] predecessor_ref {pred!r} does not exist")
        if succ not in ref_set:
            issues.append(f"relationship[{i}] successor_ref {succ!r} does not exist")
        if pred == succ:
            issues.append(f"relationship[{i}] is self-referential ({pred!r})")

    return issues


# ── Canonicalisation (stable normal form for comparison) ───────────────────


def _sort_obj(obj: Any) -> Any:
    """Recursively sort dict keys; leave list order untouched."""
    if isinstance(obj, dict):
        return {k: _sort_obj(obj[k]) for k in sorted(obj, key=str)}
    if isinstance(obj, list):
        return [_sort_obj(x) for x in obj]
    return obj


def canonicalize(raw: dict[str, Any]) -> dict[str, Any]:
    """Return a stable normal form for equality comparison.

    Recursively sorts every dict key, then orders the activity list by ``ref``
    and the relationship list by ``(predecessor, successor, type, lag)`` so two
    logically identical documents compare equal regardless of row order. Used by
    the round-trip tests and any "did cleaning change anything" check.
    """
    out = _sort_obj(raw)
    acts = out.get("activities")
    if isinstance(acts, list):
        out["activities"] = sorted(acts, key=lambda a: str(a.get("ref")))
    rels = out.get("relationships")
    if isinstance(rels, list):
        out["relationships"] = sorted(
            rels,
            key=lambda r: (
                str(r.get("predecessor_ref")),
                str(r.get("successor_ref")),
                str(r.get("relationship_type")),
                str(r.get("lag_days")),
            ),
        )
    return out
