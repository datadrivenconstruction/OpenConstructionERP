# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""What this module tells the rest of the platform.

Every publish is DETACHED (``publish_detached``): subscribers open their
own session, and awaiting them from inside a request that still holds an
open transaction deadlocks the writer. A subscriber that throws can never
take the action with it - moving a board to Wiring must not fail because
a webhook is down.

The in-app bell is NOT driven off these events: it is written directly
through the notifications service in ``notifying.py``, in the same
transaction as the action, so a raised request and its notification
either both land or neither does.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

SOURCE = "work_requests"

REQUEST_RAISED = "work_requests.request.raised"
STATUS_CHANGED = "work_requests.request.status_changed"
STAGE_CHANGED = "work_requests.request.stage_changed"
NEEDS_INFO = "work_requests.request.needs_info"
ANSWERED = "work_requests.request.answered"
HANDOFF = "work_requests.request.handoff"
MENTION = "work_requests.request.mention"
OVERDUE = "work_requests.request.overdue"
DUE_TOMORROW = "work_requests.request.due_tomorrow"


def _publish(name: str, data: dict[str, Any]) -> None:
    """Fire and forget. A failed publish never fails the action."""
    try:
        from app.core.events import event_bus

        event_bus.publish_detached(name, data, source_module=SOURCE)
    except Exception:  # noqa: BLE001 - the bell is not the work
        logger.debug("Could not publish %s", name, exc_info=True)


def _base(req: Any) -> dict[str, Any]:
    return {
        "project_id": str(req.project_id),
        "request_id": str(req.id),
        "reference": req.reference,
        "department": req.department,
        "title": req.title or "",
        "status": req.status,
        "stage": req.stage or "",
        "due_date": req.due_date or "",
    }


def request_raised(req: Any) -> None:
    _publish(REQUEST_RAISED, _base(req))


def status_changed(req: Any, previous: str) -> None:
    _publish(STATUS_CHANGED, {**_base(req), "previous": previous})


def stage_changed(req: Any, previous: str | None) -> None:
    _publish(STAGE_CHANGED, {**_base(req), "previous": previous or ""})


def needs_info(req: Any, question: str) -> None:
    _publish(NEEDS_INFO, {**_base(req), "question": question})


def answered(req: Any, answer: str) -> None:
    _publish(ANSWERED, {**_base(req), "answer": answer})


def handoff(parent: Any, child: Any) -> None:
    _publish(
        HANDOFF,
        {
            **_base(child),
            "parent_id": str(parent.id),
            "parent_reference": parent.reference,
            "from_department": parent.department,
        },
    )


def mention(req: Any, user_ids: list[str]) -> None:
    _publish(MENTION, {**_base(req), "user_ids": list(user_ids)})


def overdue(req: Any, days_late: int) -> None:
    _publish(OVERDUE, {**_base(req), "days_late": days_late})


def due_tomorrow(req: Any) -> None:
    _publish(DUE_TOMORROW, _base(req))
