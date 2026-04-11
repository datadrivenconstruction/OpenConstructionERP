"""Notifications event subscribers — turn cross-module mutation events
into in-app notifications.

Until v1.4.6 the notifications module was a "ghost component" — the
service had ``create()`` and ``notify_users()`` methods but nothing
in the rest of the platform actually called them.  Mutating actions
in contacts, collaboration, cde, transmittals, meetings, etc. fired
no notifications, no audit log, no real-time alerts.

This module wires the existing mutation events from upstream modules
into ``NotificationService.create()`` so users get visibility into
the work happening on their projects.  The subscribers are
deliberately conservative: they only fire on events whose payload
includes a clear user-id target (or that we can resolve to one
without a chain of joins), and the subscriber catches all exceptions
so a misformed event payload can never break the upstream service.

Events currently consumed:

* ``meeting.action_items_created`` →  task owners (one per item)
* ``boq.boq.created`` →  the creator (acks the create operation)
* ``bim_hub.element.deleted`` →  the deleter (audit echo)
* ``cde.container.state_transitioned`` →  the actor

Other modules can extend this list by adding to ``_SUBSCRIPTIONS``
without touching the rest of the file.
"""

from __future__ import annotations

import logging

from app.core.events import Event, event_bus
from app.database import async_session_factory
from app.modules.notifications.service import NotificationService

logger = logging.getLogger(__name__)


# ── Per-event handlers ────────────────────────────────────────────────────
#
# Each handler:
#   1. Pulls the user-id target out of event.data (or skips silently if
#      missing — the subscriber must never break a successful upstream
#      mutation)
#   2. Opens its own short-lived session via async_session_factory()
#   3. Calls NotificationService.create() with i18n keys
#   4. Catches all exceptions and logs at debug
#
# The async_session_factory() pattern matches the bim_hub vector
# event subscribers: each handler runs in its own transaction,
# isolated from the upstream caller, so a notification failure
# does not roll back the original CRUD operation.


async def _on_boq_created(event: Event) -> None:
    """``boq.boq.created`` → notify the creator."""
    data = event.data or {}
    actor_id = data.get("created_by") or data.get("user_id")
    boq_id = data.get("boq_id") or data.get("id")
    if not actor_id or not boq_id:
        return
    try:
        async with async_session_factory() as session:
            svc = NotificationService(session)
            await svc.create(
                user_id=actor_id,
                notification_type="info",
                title_key="notifications.boq.created.title",
                body_key="notifications.boq.created.body",
                body_context={"boq_name": data.get("name") or data.get("boq_name") or ""},
                entity_type="boq",
                entity_id=str(boq_id),
                action_url=f"/boq?id={boq_id}",
            )
            await session.commit()
    except Exception:
        logger.debug("notifications: _on_boq_created failed", exc_info=True)


async def _on_meeting_action_items_created(event: Event) -> None:
    """``meeting.action_items_created`` → notify each task owner.

    The meetings service publishes the per-item array under
    ``action_items`` (only the items that actually produced a Task
    row, after the v1.4.6 fix to stop lying about creation count).
    Each item carries an ``owner_id`` if the meeting transcript
    extracted one.
    """
    data = event.data or {}
    items = data.get("action_items") or []
    meeting_id = data.get("meeting_id")
    meeting_number = data.get("meeting_number") or ""
    if not isinstance(items, list) or not meeting_id:
        return
    try:
        async with async_session_factory() as session:
            svc = NotificationService(session)
            for item in items:
                if not isinstance(item, dict):
                    continue
                owner_id = item.get("owner_id")
                if not owner_id:
                    continue
                task_id = item.get("task_id")
                await svc.create(
                    user_id=owner_id,
                    notification_type="task_assigned",
                    title_key="notifications.meeting.action_assigned.title",
                    body_key="notifications.meeting.action_assigned.body",
                    body_context={
                        "meeting_number": meeting_number,
                        "description": (item.get("description") or "")[:200],
                    },
                    entity_type="task",
                    entity_id=str(task_id) if task_id else None,
                    action_url=(f"/tasks?id={task_id}" if task_id else None),
                )
            await session.commit()
    except Exception:
        logger.debug(
            "notifications: _on_meeting_action_items_created failed", exc_info=True
        )


async def _on_bim_element_deleted(event: Event) -> None:
    """``bim_hub.element.deleted`` → audit echo for the actor.

    The bim_hub service publishes ``project_id`` and ``element_id``
    but not the deleting user.  We don't have enough context to
    target a specific user without a project-membership lookup, so
    this handler is intentionally a no-op skeleton — kept here as a
    documented hook so adding the user-id payload to the upstream
    event is enough to enable the notification without router
    changes.
    """
    return


async def _on_cde_state_transitioned(event: Event) -> None:
    """``cde.container.state_transitioned`` → notify the actor."""
    data = event.data or {}
    actor_id = data.get("user_id") or data.get("actor_id")
    container_id = data.get("container_id") or data.get("id")
    new_state = data.get("new_state") or data.get("to_state") or ""
    if not actor_id or not container_id:
        return
    try:
        async with async_session_factory() as session:
            svc = NotificationService(session)
            await svc.create(
                user_id=actor_id,
                notification_type="info",
                title_key="notifications.cde.state_transitioned.title",
                body_key="notifications.cde.state_transitioned.body",
                body_context={"new_state": new_state},
                entity_type="cde_container",
                entity_id=str(container_id),
                action_url=f"/cde?id={container_id}",
            )
            await session.commit()
    except Exception:
        logger.debug(
            "notifications: _on_cde_state_transitioned failed", exc_info=True
        )


# Declarative subscription map.  Adding a new event to this list
# is the ONE place to wire a new notification trigger — keeps the
# event topology auditable from a single grep.
_SUBSCRIPTIONS: list[tuple[str, callable]] = [  # type: ignore[type-arg]
    ("boq.boq.created", _on_boq_created),
    ("meeting.action_items_created", _on_meeting_action_items_created),
    ("bim_hub.element.deleted", _on_bim_element_deleted),
    ("cde.container.state_transitioned", _on_cde_state_transitioned),
]


def register_notification_subscribers() -> None:
    """Wire every entry of ``_SUBSCRIPTIONS`` into the global event bus.

    Idempotent: subscribing the same handler twice is harmless because
    the EventBus deduplicates on identity.  Called from the module
    ``on_startup`` hook so it runs once after the module loader has
    finished mounting routers.
    """
    for event_name, handler in _SUBSCRIPTIONS:
        event_bus.subscribe(event_name, handler)
    logger.info(
        "Notifications: subscribed to %d cross-module event(s)",
        len(_SUBSCRIPTIONS),
    )
