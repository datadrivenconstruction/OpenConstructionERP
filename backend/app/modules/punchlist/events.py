# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Punch List event subscribers (task #156).

The punchlist module owns the operational defect workflow (status FSM:
open -> in_progress -> resolved -> verified -> closed, photo evidence,
trades, assignment). Property Development's Snag entity is the
buyer/handover-facing surface of the same physical defect. To avoid
forcing site staff to track the same defect in two places, this module
subscribes to ``property_dev.snag.created`` and auto-creates a matching
punchlist item.

The bridge:

* Walks snag -> handover -> plot -> development -> project to find the
  ``project_id`` punchlist needs (punchlist is project-scoped, snag is
  handover-scoped — same data, different anchor).
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
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.core.events import Event, event_bus
from app.database import async_session_factory

logger = logging.getLogger(__name__)

_SUBSCRIBED_FLAG = "_punchlist_subscribers_registered"

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

    Payload (best-effort — missing fields skip cleanly):
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

            # Build the punch item directly — we deliberately do NOT go
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


def register_punchlist_event_subscribers() -> None:
    """Wire cross-module subscribers. Idempotent."""
    if getattr(event_bus, _SUBSCRIBED_FLAG, False):
        return
    event_bus.subscribe("property_dev.snag.created", _on_snag_created)
    setattr(event_bus, _SUBSCRIBED_FLAG, True)
    logger.info("punchlist cross-module subscribers registered")


__all__ = ["register_punchlist_event_subscribers"]
