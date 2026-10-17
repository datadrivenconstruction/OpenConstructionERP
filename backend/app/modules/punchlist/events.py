# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Punch List event subscribers (task #156).

The punchlist module owns the operational defect workflow (status FSM:
open -> in_progress -> resolved -> verified -> closed, photo evidence,
trades, assignment). Property Development's Snag entity is the
buyer/handover-facing surface of the same physical defect. To avoid
forcing site staff to track the same defect in two places, this module
subscribes to ``property_dev.snag.created`` and auto-creates a matching
punchlist item.

The snag bridge:

* Walks snag -> handover -> plot -> development -> project to find the
  ``project_id`` punchlist needs (punchlist is project-scoped, snag is
  handover-scoped - same data, different anchor).
* Maps snag.severity -> punch.priority:
    cosmetic/minor -> low
    major          -> high
    safety         -> critical
* Copies snag.category 1:1 when it's in the punchlist allow-list,
  falls back to 'general'.
* Writes the link back to snag.linked_punch_item_id so the two rows
  stay traceable in either direction.
* Fail-soft: every exception is logged but never raises (the event bus
  swallows exceptions anyway, but we belt-and-braces it so a punchlist
  outage cannot break snag writes).

Two further bridges turn coordination/quality signals into actionable
site work:

* ``clash.high_severity.detected`` -> one punch item capturing the clash
  (disciplines/level in the title, element ids + severity in the body).
  Idempotent on ``PunchItem.clash_result_id`` so a re-published event
  never spawns a second item.
* ``inspection.completed.failed`` -> one punch item per failed checklist
  item, idempotent on the (inspection_id, item-key) pair recorded in
  ``metadata_`` so re-completing the inspection does not duplicate.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select

from app.core.events import Event, event_bus
from app.database import async_session_factory

logger = logging.getLogger(__name__)


# Snag severity -> punch priority. Punchlist priority allow-list:
# low / medium / high / critical.
_SEVERITY_TO_PRIORITY: dict[str, str] = {
    "cosmetic": "low",
    "minor": "low",
    "major": "high",
    "safety": "critical",
}

# Punchlist category allow-list (mirrors PunchItemCreate.category regex).
_PUNCH_CATEGORIES: frozenset[str] = frozenset(
    {
        "structural",
        "mechanical",
        "electrical",
        "architectural",
        "fire_safety",
        "plumbing",
        "finishing",
        "hvac",
        "exterior",
        "landscaping",
        "general",
    }
)


def _coerce_uuid(value: Any) -> uuid.UUID | None:
    if value is None:
        return None
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


async def _resolve_project_id(
    session: Any,
    handover_id: uuid.UUID,
) -> uuid.UUID | None:
    """Walk handover -> plot -> development -> project_id.

    Returns None when any link is missing; the bridge then skips
    item creation rather than guessing.
    """
    from app.modules.property_dev.models import Development, Handover, Plot

    handover = await session.get(Handover, handover_id)
    if handover is None:
        return None
    plot = await session.get(Plot, handover.plot_id)
    if plot is None:
        return None
    development = await session.get(Development, plot.development_id)
    if development is None:
        return None
    return development.project_id


async def _on_snag_created(event: Event) -> None:
    """Subscriber for ``property_dev.snag.created``.

    Payload (best-effort - missing fields skip cleanly):
        snag_id        UUID
        handover_id    UUID
        buyer_id       UUID | None
        category       str  (snag category, may differ from punch list)
        severity       str  (cosmetic|minor|major|safety)
        description    str  (first 200 chars from publisher)
        cost_impact    str  (Decimal serialised)
    """
    try:
        data = event.data or {}
        snag_id = _coerce_uuid(data.get("snag_id"))
        handover_id = _coerce_uuid(data.get("handover_id"))
        if snag_id is None or handover_id is None:
            logger.debug("snag bridge: missing IDs in payload, skipping")
            return

        severity = str(data.get("severity") or "minor").lower()
        priority = _SEVERITY_TO_PRIORITY.get(severity, "medium")

        raw_category = str(data.get("category") or "general").lower()
        category = raw_category if raw_category in _PUNCH_CATEGORIES else "general"

        description = str(data.get("description") or "")
        # Title is required + min_length=1; first 80 chars of description
        # with a sensible fallback so we never hand the schema an empty
        # string.
        title = description.strip()[:80] or f"Snag {snag_id.hex[:8]}"

        async with async_session_factory() as session:
            project_id = await _resolve_project_id(session, handover_id)
            if project_id is None:
                logger.info(
                    "snag bridge: cannot resolve project_id for handover %s, skipping punchlist creation",
                    handover_id,
                )
                return

            # Build the punch item directly - we deliberately do NOT go
            # through PunchListService.create_item() because it runs an
            # additional event publish that could fan out indefinitely
            # if a future subscriber writes back to snag.
            from app.modules.property_dev.models import Snag
            from app.modules.punchlist.models import PunchItem

            punch = PunchItem(
                project_id=project_id,
                title=title,
                description=description,
                priority=priority,
                status="open",
                category=category,
                metadata_={
                    "source": "property_dev.snag",
                    "snag_id": str(snag_id),
                    "handover_id": str(handover_id),
                    "cost_impact": str(data.get("cost_impact") or "0"),
                },
            )
            session.add(punch)
            await session.flush()

            # Write the back-link onto the snag so both rows know about
            # each other.
            snag = await session.get(Snag, snag_id)
            if snag is not None:
                snag.linked_punch_item_id = punch.id

            await session.commit()
            logger.info(
                "snag bridge: created punchlist %s for snag %s (project %s)",
                punch.id,
                snag_id,
                project_id,
            )
    except Exception:
        logger.exception("snag bridge: unexpected error, swallowed")


# ── clash.high_severity.detected -> punch item ──────────────────────────

# Clash severity -> punch priority. High/critical are the only severities
# the clash module publishes for, so both map to the top punch bands.
_CLASH_SEVERITY_TO_PRIORITY: dict[str, str] = {
    "critical": "critical",
    "high": "high",
}


def _clash_punch_title(data: dict[str, Any]) -> str:
    """Build a readable punch title from a clash payload.

    Prefers the two element names ("Wall-12 vs Pipe-7"); falls back to the
    clash type. Always returns a non-empty string within the 255-char
    column limit and the schema's min_length=1.
    """
    a_name = str(data.get("a_name") or "").strip()
    b_name = str(data.get("b_name") or "").strip()
    clash_type = str(data.get("clash_type") or "clash").strip() or "clash"
    if a_name and b_name:
        body = f"{a_name} vs {b_name}"
    elif a_name or b_name:
        body = a_name or b_name
    else:
        body = clash_type
    return f"Clash: {body}"[:255]


async def _on_clash_high_severity(event: Event) -> None:
    """``clash.high_severity.detected`` -> auto-create a punch item.

    Captures every high/critical clash as a site-actionable punch item so
    the coordination finding does not stay locked inside the clash module.
    Idempotent: guarded on ``PunchItem.clash_result_id`` so a re-published
    or confirmed event for the same clash never creates a duplicate.

    Fail-soft - any error is logged and swallowed.
    """
    try:
        data = event.data or {}
        result_id = data.get("result_id")
        project_id = _coerce_uuid(data.get("project_id"))
        if not result_id or project_id is None:
            logger.debug("clash->punch: missing result_id/project_id, skipping")
            return

        result_id_s = str(result_id)
        severity = str(data.get("severity") or "high").lower()
        priority = _CLASH_SEVERITY_TO_PRIORITY.get(severity, "high")

        title = _clash_punch_title(data)
        description_lines = [
            f"Auto-created from a {severity}-severity clash.",
            f"Elements: {data.get('a_name') or '?'} <-> {data.get('b_name') or '?'}",
            f"Clash type: {data.get('clash_type') or 'n/a'}",
        ]
        run_id = data.get("run_id")
        if run_id:
            description_lines.append(f"Clash run: {run_id}")
        description = "\n".join(description_lines)

        async with async_session_factory() as session:
            from app.modules.punchlist.models import PunchItem

            # Idempotency - bail if a punch item already links this clash.
            existing = (
                await session.execute(
                    select(PunchItem.id).where(
                        PunchItem.project_id == project_id,
                        PunchItem.clash_result_id == result_id_s,
                    )
                )
            ).first()
            if existing is not None:
                logger.debug("clash->punch: punch item already exists for clash %s", result_id_s)
                return

            assigned_to = str(data.get("assigned_to") or "").strip() or None
            punch = PunchItem(
                project_id=project_id,
                title=title,
                description=description,
                priority=priority,
                status="open",
                category="general",
                assigned_to=assigned_to,
                clash_result_id=result_id_s,
                metadata_={
                    "source": "clash",
                    "result_id": result_id_s,
                    "run_id": str(run_id) if run_id else "",
                    "severity": severity,
                    "clash_type": data.get("clash_type") or "",
                },
            )
            session.add(punch)
            await session.commit()
            logger.info(
                "clash->punch: created punch item %s for clash %s (project %s, %s)",
                punch.id,
                result_id_s,
                project_id,
                severity,
            )
    except Exception:
        logger.exception("clash->punch bridge: unexpected error, swallowed")


# ── inspection.completed.failed -> punch item(s) ────────────────────────


def _failed_item_key(item: dict[str, Any], index: int) -> str:
    """Return a stable per-checklist-item key for idempotency.

    Prefers an explicit item id; falls back to the question/description
    text; last resort is the positional index so two truly-identical
    items still get distinct keys.
    """
    for field in ("id", "item_id", "question", "description"):
        val = item.get(field)
        if val:
            return str(val)[:200]
    return f"idx:{index}"


def _failed_item_label(item: dict[str, Any]) -> str:
    """Human-readable label for a failed checklist item."""
    label = item.get("question") or item.get("description") or "Checklist item"
    return str(label).strip()[:255] or "Checklist item"


async def _on_inspection_completed_failed(event: Event) -> None:
    """``inspection.completed.failed`` -> one punch item per failed item.

    A failed or partial inspection carries a ``failed_items`` array; each
    entry becomes its own punch item so the defect is tracked and assignable
    on the punch list. Idempotent on the (inspection_id, item-key) pair
    recorded in ``metadata_`` so re-completing the same inspection does not
    create duplicates.

    Fail-soft - any error is logged and swallowed.
    """
    try:
        data = event.data or {}
        inspection_id = data.get("inspection_id")
        project_id = _coerce_uuid(data.get("project_id"))
        failed_items = data.get("failed_items")
        if not inspection_id or project_id is None:
            logger.debug("inspection->punch: missing inspection_id/project_id, skipping")
            return
        if not isinstance(failed_items, list) or not failed_items:
            logger.debug("inspection->punch: no failed_items, skipping")
            return

        inspection_id_s = str(inspection_id)
        inspection_number = str(data.get("inspection_number") or "").strip()

        async with async_session_factory() as session:
            from app.modules.punchlist.models import PunchItem

            # Load existing item-keys already materialised for this inspection
            # so the whole batch is idempotent in a single query.
            rows = (
                (
                    await session.execute(
                        select(PunchItem.metadata_).where(
                            PunchItem.project_id == project_id,
                        )
                    )
                )
                .scalars()
                .all()
            )
            existing_keys: set[str] = set()
            for md in rows:
                if not isinstance(md, dict):
                    continue
                if md.get("source") == "inspection" and md.get("inspection_id") == inspection_id_s:
                    key = md.get("item_key")
                    if key:
                        existing_keys.add(str(key))

            created = 0
            for index, item in enumerate(failed_items):
                if not isinstance(item, dict):
                    continue
                item_key = _failed_item_key(item, index)
                if item_key in existing_keys:
                    continue
                existing_keys.add(item_key)

                label = _failed_item_label(item)
                is_critical = bool(item.get("critical"))
                note = str(item.get("notes") or "").strip()
                prefix = f"Inspection {inspection_number}".strip() or "Inspection"
                description_lines = [f"Failed item from {prefix}: {label}"]
                if note:
                    description_lines.append(f"Notes: {note}")
                description = "\n".join(description_lines)

                punch = PunchItem(
                    project_id=project_id,
                    title=label,
                    description=description,
                    priority="critical" if is_critical else "high",
                    status="open",
                    category="general",
                    metadata_={
                        "source": "inspection",
                        "inspection_id": inspection_id_s,
                        "inspection_number": inspection_number,
                        "item_key": item_key,
                        "critical": is_critical,
                    },
                )
                session.add(punch)
                created += 1

            if created:
                await session.commit()
                logger.info(
                    "inspection->punch: created %d punch item(s) for inspection %s (project %s)",
                    created,
                    inspection_id_s,
                    project_id,
                )
    except Exception:
        logger.exception("inspection->punch bridge: unexpected error, swallowed")


def register_punchlist_event_subscribers() -> None:
    """Wire cross-module subscribers. Idempotent."""
    event_bus.subscribe_once("property_dev.snag.created", _on_snag_created)
    event_bus.subscribe_once("clash.high_severity.detected", _on_clash_high_severity)
    event_bus.subscribe_once("inspection.completed.failed", _on_inspection_completed_failed)
    logger.info("punchlist cross-module subscribers registered")


__all__ = ["register_punchlist_event_subscribers"]
