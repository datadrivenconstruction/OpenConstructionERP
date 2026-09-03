# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""What this module tells the rest of the platform.

Everything the module computes - overdue, a gate sitting open, an award,
a chase falling due - used to be pull-only. It was visible if you were
already looking at the tab and invisible if you were not, which for a
deadline is the same as absent: the whole point of an overdue RFI is
that it finds you.

The platform already has the bus and the bell; sibling modules publish
onto it and this one published nothing. So: four events, named for what
happened rather than for what changed.

Every publish is DETACHED (``publish_detached``). Subscribers open their
own session, and awaiting them from inside a request that still holds an
open transaction deadlocks the writer. It also means a subscriber that
throws can never take the workflow action with it - ticking a gate must
not fail because the notification service is down.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

SOURCE = "register_workflow"

#: The event names. Kept as constants because a typo'd event name is a
#: notification that silently never arrives - nothing raises, nothing
#: logs, the bell just stays quiet.
ITEM_RAISED = "register_workflow.item_raised"
GATE_OPEN = "register_workflow.gate_open"
ITEM_OVERDUE = "register_workflow.item_overdue"
AWARD_MADE = "register_workflow.award_made"
CHASE_DUE = "register_workflow.chase_due"


def _publish(name: str, data: dict[str, Any]) -> None:
    """Fire and forget. A failed notification never fails the action."""
    try:
        from app.core.events import event_bus

        event_bus.publish_detached(name, data, source_module=SOURCE)
    except Exception:  # noqa: BLE001 - the bell is not the work
        logger.debug("Could not publish %s", name, exc_info=True)


def item_raised(item: Any) -> None:
    _publish(
        ITEM_RAISED,
        {
            "project_id": str(item.project_id),
            "item_id": str(item.id),
            "reference": item.reference,
            "kind": item.kind,
            "title": item.title or "",
            "due_date": item.due_date or "",
        },
    )


def gate_open(item: Any, step: Any) -> None:
    """A hold point is now the current step and somebody must sign it."""
    _publish(
        GATE_OPEN,
        {
            "project_id": str(item.project_id),
            "item_id": str(item.id),
            "reference": item.reference,
            "gate": step.name,
            "owner": step.owner or "",
        },
    )


def item_overdue(item: Any, days_late: int) -> None:
    _publish(
        ITEM_OVERDUE,
        {
            "project_id": str(item.project_id),
            "item_id": str(item.id),
            "reference": item.reference,
            "kind": item.kind,
            "title": item.title or "",
            "due_date": item.due_date or "",
            "days_late": days_late,
        },
    )


def chase_due(item: Any, supplier: str, days_waiting: int) -> None:
    _publish(
        CHASE_DUE,
        {
            "project_id": str(item.project_id),
            "item_id": str(item.id),
            "reference": item.reference,
            "supplier": supplier,
            "days_waiting": days_waiting,
        },
    )


def award_made(item: Any, supplier: str, amount: str, po_number: str = "") -> None:
    _publish(
        AWARD_MADE,
        {
            "project_id": str(item.project_id),
            "item_id": str(item.id),
            "reference": item.reference,
            "supplier": supplier,
            "amount": amount,
            "po_number": po_number,
        },
    )
