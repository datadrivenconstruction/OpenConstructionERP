# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure event-to-timeline mapping (no app.* imports, py3.11-testable).

The unified project timeline is built on top of the existing activity-log
store (``oe_activity_log``). A bridge subscriber listens to the in-memory
event bus and persists the *significant* cross-module domain events so the
timeline survives a restart (the event bus itself is in-memory only).

This module is deliberately dependency-free: it imports only the standard
library so it can be unit-tested under Python 3.11 without standing up the
application, a database, or the event bus. Every function is defensive and
never raises - a malformed event must never break the publisher.

Naming contract
---------------
Events follow dot-notation ``{module}.{entity}.{action}`` (see
``app.core.events``). Significance is decided by :data:`ALLOWLIST_PREFIXES`
(whole families) plus :data:`ALLOWLIST_EVENTS` (individual names inside a
family that is otherwise out of scope).

Both lists are derived from the event names ``app/`` actually publishes, and
``tests/modules/timeline/test_timeline_coverage.py`` holds them to that. The
earlier version of this module guessed at names - ``changeorder.`` where the
publisher says ``changeorders.``, ``schedule.`` where it says
``schedule_advanced.`` - and nine of its sixteen prefixes matched nothing at
all, so the timeline recorded 13 of 225 published events and looked healthy
while doing it.

Two rules govern what may be listed here, and the coverage test enforces both:

1. **It must be published.** An entry matching no name in ``app/`` is dead
   weight that reads like coverage.
2. **It must be routable.** Every publish site for the name must carry a
   project id (``project_id`` / ``projectId``). :func:`map_event` has no other
   way to reach a project, so an event without one produces a row that no
   project timeline can ever return - written, billed for, and invisible.

``correspondence.outbound.requested`` is the worked example of rule 2 and the
reason ``correspondence.`` is absent below: its publisher
(``app/modules/property_dev/service.py``) sends ``instalment_id`` and
``schedule_id`` but no project id, so every row it produced was unreachable.
Adding the project id at that publisher is the fix that would let the family
back in; that file is outside this module and was left alone.
"""

from __future__ import annotations

import uuid as _uuid
from typing import Any

# Significant cross-module domain-event families. Every event named under one
# of these prefixes is published somewhere in ``app/`` and carries a project id
# at every publish site.
ALLOWLIST_PREFIXES: tuple[str, ...] = (
    "approval.",
    "boq.",
    "cc.",
    "cde.",
    "changeorders.",
    "closeout.",
    "compliance_docs.",
    "cost.",
    "credentials.",
    "cvr.",
    "daily_diary.",
    "esg.",
    "field_diary.",
    "fieldreports.",
    "hse_advanced.",
    "inspection.",
    "invoice.",
    "meeting.",
    "moc.",
    "ncr.",
    "procurement.",
    "punchlist.",
    "record.",
    "rfq.",
    "safety.",
    "variation.",
)

# Individual significant events from families that are otherwise out of scope,
# either because the rest of the family is plumbing or because the rest of it
# does not carry a project id. Listing them by name keeps the timeline from
# swallowing a whole noisy family to reach a handful of milestones.
ALLOWLIST_EVENTS: frozenset[str] = frozenset(
    {
        "bid_management.bid_package.created_from_opportunity",
        "bid_management.bids.opened",
        "bid_management.invitations.dispatched",
        "bid_management.package.awarded",
        "bid_management.package.published",
        "carbon.inventory.auto_enriched",
        "carbon.inventory.finalized",
        "carbon.inventory.lcc_computed",
        "carbon.inventory.operational_computed",
        "carbon.report.generated",
        "contracts.contract.drafted_from_bid_award",
        "contracts.contract.signed",
        "equipment.assigned",
        "equipment.fuel_logged",
        "equipment.parts_logged",
        "equipment.rental_returned",
        "finance.invoice.created_from_claim",
        "qms.audit.completed",
        "qms.audit.finding_raised",
        "qms.calibration.expiring",
        "qms.inspection.approval_requested",
        "qms.inspection.hold_point_released",
        "qms.itp.activated",
        "qms.itp.cloned_from_template",
        "qms.ncr.closed",
        "qms.ncr.escalated_to_variation",
        "qms.ncr.mirrored_from_hse",
        "qms.ncr.raised",
        "qms.punch.closed",
        "qms.punch.created",
        "resources.assignment.confirmed",
        "resources.assignment.proposed",
        "resources.portfolio.overload_detected",
        "resources.request.fulfilled",
        "resources.request.opened",
        "schedule_advanced.actuals_update",
        "service.work_order.material_requested",
        "service.work_order.ncr_filed",
        "subcontractors.defect.recorded",
        "validation.report.created",
        "validation.results.errors_found",
    }
)

# Keys an event payload uses to carry the umbrella project id.
_PROJECT_ID_KEYS: tuple[str, ...] = ("project_id", "projectId")

# Keys an event payload uses to carry the acting user. Without this the bridge
# writes every row with ``actor_id=None`` and the timeline cannot answer "who".
ACTOR_ID_KEYS: tuple[str, ...] = (
    "actor_id",
    "created_by",
    "created_by_id",
    "performed_by",
    "user_id",
)

# Id-shaped keys that never identify the *subject* of the event, so the
# last-resort scan in :func:`_extract_entity_id` must skip them.
_NON_ENTITY_ID_KEYS: frozenset[str] = frozenset(
    {
        "project_id",
        "projectId",
        "tenant_id",
        "parent_id",
        "owner_id",
        *ACTOR_ID_KEYS,
    }
)


def is_significant(event_name: str) -> bool:
    """Return True when *event_name* is a significant cross-module event.

    Decided from the name alone, against :data:`ALLOWLIST_EVENTS` first and
    :data:`ALLOWLIST_PREFIXES` second. Defensive: a non-string or empty name is
    simply not significant (never raises).
    """
    if not event_name or not isinstance(event_name, str):
        return False
    if event_name in ALLOWLIST_EVENTS:
        return True
    return event_name.startswith(ALLOWLIST_PREFIXES)


def _derive_module(event_name: str) -> str:
    """First dotted token of the event name (the logical module)."""
    return event_name.split(".", 1)[0]


def _derive_entity_type(event_name: str) -> str:
    """Logical entity type for the row.

    Uses the first dotted token, or ``first.second`` when the event has at
    least three tokens (``module.entity.action``) so a richer name like
    ``moc.entry.auto_proposed`` records ``entity_type="moc.entry"`` while a
    two-token name like ``ncr.created`` records ``entity_type="ncr"``.
    """
    parts = event_name.split(".")
    if len(parts) >= 3:
        return f"{parts[0]}.{parts[1]}"
    return parts[0]


def _coerce_id(value: Any) -> str | None:
    """Best-effort coercion of an id-like value to a non-empty string."""
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        return value or None
    # ints, UUIDs, and anything else with a sensible str() form.
    try:
        text = str(value).strip()
    except Exception:
        return None
    return text or None


def _first_present(data: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    """First key in *keys* that carries a usable id, else None."""
    for key in keys:
        if key in data:
            coerced = _coerce_id(data.get(key))
            if coerced is not None:
                return coerced
    return None


def _extract_entity_id(module: str, entity_type: str, data: dict[str, Any]) -> str | None:
    """Pull the affected entity id from the payload.

    Tries, in order: ``id``; ``{module}_id``; ``{entity}_id`` derived from the
    second token of a three-token event name; ``entity_id``; and finally the
    first ``*_id`` key that is not a project, tenant or actor reference.

    The last two steps exist because publishers name the key after the record,
    not after the event: ``cost.back_charge.recorded`` sends ``back_charge_id``
    and ``moc.candidate_from_ncr`` sends ``ncr_id``. Looking only for
    ``{module}_id`` left 6 of the 14 captured publish sites with no entity id
    at all, which is a timeline row that cannot be linked back to its record.
    """
    tail = entity_type.split(".")[-1]
    keys: tuple[str, ...] = ("id", f"{module}_id", f"{tail}_id", "entity_id")
    found = _first_present(data, keys)
    if found is not None:
        return found

    for key, value in data.items():
        if not isinstance(key, str) or not key.endswith("_id"):
            continue
        if key in _NON_ENTITY_ID_KEYS:
            continue
        coerced = _coerce_id(value)
        if coerced is not None:
            return coerced
    return None


def _extract_project_id(data: dict[str, Any]) -> str | None:
    """Pull the umbrella project id from common payload keys."""
    return _first_present(data, _PROJECT_ID_KEYS)


def _extract_actor_id(data: dict[str, Any]) -> _uuid.UUID | None:
    """Pull the acting user id, but only when it is a real UUID.

    ``ActivityLog.actor_id`` is a GUID column, so a display name or an email
    in ``created_by`` has to be dropped rather than written - it would fail the
    insert, and the bridge swallows failures, so the whole row would vanish.
    """
    raw = _first_present(data, ACTOR_ID_KEYS)
    if raw is None:
        return None
    try:
        return _uuid.UUID(raw)
    except (ValueError, AttributeError, TypeError):
        return None


def is_routable(mapped: dict[str, Any]) -> bool:
    """Return True when a mapped row can be reached by a timeline query.

    The project timeline selects on ``parent_entity_id`` or ``entity_id``. A
    row carrying neither is written and then unreachable forever, which is
    worse than not recording it: it costs a write and reads as coverage.
    """
    return bool(mapped.get("parent_entity_id") or mapped.get("entity_id"))


def map_event(event_name: str, data: dict[str, Any] | None) -> dict[str, Any] | None:
    """Map an event to an activity-log row payload, or None if not significant.

    Returns a dict with the keys ``entity_type``, ``entity_id``, ``action``,
    ``module``, ``parent_entity_type``, ``parent_entity_id``, ``actor_id`` and
    ``metadata`` when the event is significant; otherwise ``None``.

    Derivations:
        module             - first dotted token of the event name.
        entity_type        - first token, or ``first.second`` for 3+ tokens.
        action             - the full event name (verbatim).
        entity_id          - see :func:`_extract_entity_id`.
        parent_entity_type - ``"project"`` when a project id is present, else
                             ``None``.
        parent_entity_id   - from ``project_id`` / ``projectId``.
        actor_id           - the acting user, when the payload names one and it
                             parses as a UUID.
        metadata           - a shallow copy of the original payload so the
                             timeline keeps the full event context.

    Defensive: never raises. A non-dict ``data`` is treated as empty.
    """
    if not is_significant(event_name):
        return None

    payload: dict[str, Any] = data if isinstance(data, dict) else {}

    module = _derive_module(event_name)
    entity_type = _derive_entity_type(event_name)
    entity_id = _extract_entity_id(module, entity_type, payload)
    project_id = _extract_project_id(payload)

    parent_entity_type: str | None = "project" if project_id is not None else None

    # Shallow copy so callers can safely augment without mutating the event.
    metadata: dict[str, Any] = dict(payload)

    return {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "action": event_name,
        "module": module,
        "parent_entity_type": parent_entity_type,
        "parent_entity_id": project_id,
        "actor_id": _extract_actor_id(payload),
        "metadata": metadata,
    }


__all__ = [
    "ACTOR_ID_KEYS",
    "ALLOWLIST_EVENTS",
    "ALLOWLIST_PREFIXES",
    "is_routable",
    "is_significant",
    "map_event",
]
