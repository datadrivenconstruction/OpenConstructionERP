# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Notification subscribers for the document-approval (file_approvals) engine.

The generic approval engine (``approval_routes``) already rides the SLA sweep,
digest and delivery loop. The document-approval engine (``file_approvals``:
submit / decide / withdraw) emitted nothing, so assigning an approval step or
deciding one fired zero notifications. These handlers close that gap: they map
the detached events published by ``file_approvals/service.py`` onto
``NotificationService.create()`` so the ball-holder always gets visible feedback.

Each handler mirrors the Wave subscribers:
    1. Pulls the target user-id out of ``event.data``.
    2. Skips silently when the payload lacks the required hint.
    3. Opens its own short-lived session so a notification failure cannot roll
       back the upstream decision.
    4. Catches everything and logs at debug.

Registered from ``notifications/events.py``'s startup hook.
"""

from __future__ import annotations

import logging

from app.core.events import Event, event_bus
from app.database import async_session_factory
from app.modules.notifications.service import NotificationService

logger = logging.getLogger(__name__)


async def _on_file_approval_needs_approver(event: Event) -> None:
    """``file_approval.submitted`` / ``.step_advanced`` -> notify the approver.

    Both events mean the same thing to a person: a document is now waiting for
    your approval. The submitter approving their own first step is not worth a
    self-notification, so that case is skipped.
    """
    data = event.data or {}
    approver_id = data.get("approver_id")
    workflow_id = data.get("workflow_id")
    if not approver_id or not workflow_id:
        return
    if approver_id == data.get("submitter_id"):
        return
    try:
        async with async_session_factory() as session:
            await NotificationService(session).create(
                user_id=str(approver_id),
                notification_type="approval_needed",
                title_key="notifications.file_approval.needs_approver.title",
                body_key="notifications.file_approval.needs_approver.body",
                body_context={
                    "file_kind": str(data.get("file_kind") or "document"),
                    "role_label": str(data.get("role_label") or ""),
                },
                entity_type="file_approval_workflow",
                entity_id=str(workflow_id),
                # The approval register, as the dashboard inbox links it; it
                # selects no workflow from the URL, the id is in ``entity_id``.
                action_url="/files/approvals",
            )
            await session.commit()
    except Exception:
        logger.debug("notifications: _on_file_approval_needs_approver failed", exc_info=True)


async def _on_file_approval_approved(event: Event) -> None:
    """``file_approval.approved`` (final step) -> tell the submitter it passed."""
    data = event.data or {}
    submitter_id = data.get("submitter_id")
    workflow_id = data.get("workflow_id")
    if not submitter_id or not workflow_id:
        return
    try:
        async with async_session_factory() as session:
            await NotificationService(session).create(
                user_id=str(submitter_id),
                notification_type="approval_decided",
                title_key="notifications.file_approval.approved.title",
                body_key="notifications.file_approval.approved.body",
                body_context={"file_kind": str(data.get("file_kind") or "document")},
                entity_type="file_approval_workflow",
                entity_id=str(workflow_id),
                action_url="/files/approvals",
            )
            await session.commit()
    except Exception:
        logger.debug("notifications: _on_file_approval_approved failed", exc_info=True)


async def _on_file_approval_rejected(event: Event) -> None:
    """``file_approval.rejected`` -> tell the submitter it was returned."""
    data = event.data or {}
    submitter_id = data.get("submitter_id")
    workflow_id = data.get("workflow_id")
    if not submitter_id or not workflow_id:
        return
    try:
        async with async_session_factory() as session:
            await NotificationService(session).create(
                user_id=str(submitter_id),
                notification_type="approval_rejected",
                title_key="notifications.file_approval.rejected.title",
                body_key="notifications.file_approval.rejected.body",
                body_context={
                    "file_kind": str(data.get("file_kind") or "document"),
                    "note": str(data.get("note") or ""),
                },
                entity_type="file_approval_workflow",
                entity_id=str(workflow_id),
                action_url="/files/approvals",
            )
            await session.commit()
    except Exception:
        logger.debug("notifications: _on_file_approval_rejected failed", exc_info=True)


_FILE_APPROVAL_SUBSCRIPTIONS = [
    ("file_approval.submitted", _on_file_approval_needs_approver),
    ("file_approval.step_advanced", _on_file_approval_needs_approver),
    ("file_approval.approved", _on_file_approval_approved),
    ("file_approval.rejected", _on_file_approval_rejected),
]


def register_file_approvals_notification_subscribers() -> None:
    """Wire the document-approval events into in-app notifications.

    Idempotent - the event bus deduplicates handlers by identity.
    """
    for event_name, handler in _FILE_APPROVAL_SUBSCRIPTIONS:
        event_bus.subscribe_once(event_name, handler)
    logger.info(
        "Notifications/FileApprovals: subscribed to %d document-approval event(s)",
        len(_FILE_APPROVAL_SUBSCRIPTIONS),
    )
