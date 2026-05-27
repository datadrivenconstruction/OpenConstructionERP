"""‌⁠‍Notifications event subscribers — turn cross-module mutation events
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


async def _can_open_isolated_session() -> bool:
    """‌⁠‍Return True when it is safe to open a write session right now.

    History: pre-Epic-B this returned False on SQLite because notification
    subscribers were invoked inside the upstream service's transaction,
    and SQLite is single-writer per file — opening a second write session
    blocked on the file lock and turned 50ms requests into 60s ones.

    Epic B / B9: upstream callers now publish via
    :meth:`EventBus.publish_detached`, which schedules the subscriber as
    an asyncio task that fires *after* the request has committed.  The
    writer lock is released before the subscriber tries to take it, so
    SQLite no longer deadlocks.  This helper therefore returns True on
    every dialect — the legacy skip is gone.

    Kept as a function so the existing call sites remain a no-op
    boundary; deleting them entirely would create a large unrelated
    diff and bury the actual Epic B behaviour change.  Future cleanup
    can collapse the call sites in a separate commit.
    """
    return True


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
    """‌⁠‍``boq.boq.created`` → notify the creator."""
    if not await _can_open_isolated_session():
        return
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
                action_url=f"/boq/{boq_id}",
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
    if not await _can_open_isolated_session():
        return
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
        logger.debug("notifications: _on_meeting_action_items_created failed", exc_info=True)


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
    if not await _can_open_isolated_session():
        return
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
        logger.debug("notifications: _on_cde_state_transitioned failed", exc_info=True)


async def _on_rfi_assigned(event: Event) -> None:
    """``rfi.assigned`` → notify the assignee."""
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    assignee_id = data.get("assigned_to") or data.get("assigned_to_user_id") or data.get("assignee_id")
    rfi_id = data.get("rfi_id") or data.get("id")
    if not assignee_id or not rfi_id:
        return
    try:
        async with async_session_factory() as session:
            svc = NotificationService(session)
            await svc.create(
                user_id=assignee_id,
                notification_type="rfi_assigned",
                title_key="notifications.rfi.assigned.title",
                body_key="notifications.rfi.assigned.body",
                body_context={
                    "code": data.get("rfi_number") or "",
                    "title": data.get("subject") or "",
                },
                entity_type="rfi",
                entity_id=str(rfi_id),
                action_url=f"/rfi?id={rfi_id}",
            )
            await session.commit()
    except Exception:
        logger.debug("notifications: _on_rfi_assigned failed", exc_info=True)


async def _on_risk_assigned(event: Event) -> None:
    """``risk.assigned`` → notify the new owner."""
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    owner_id = data.get("owner_user_id") or data.get("assigned_to")
    risk_id = data.get("risk_id") or data.get("id")
    if not owner_id or not risk_id:
        return
    try:
        async with async_session_factory() as session:
            svc = NotificationService(session)
            await svc.create(
                user_id=owner_id,
                notification_type="risk_assigned",
                title_key="notifications.risk.assigned.title",
                body_key="notifications.risk.assigned.body",
                body_context={
                    "code": data.get("code") or "",
                    "title": data.get("title") or "",
                },
                entity_type="risk",
                entity_id=str(risk_id),
                action_url=f"/risks?id={risk_id}",
            )
            await session.commit()
    except Exception:
        logger.debug("notifications: _on_risk_assigned failed", exc_info=True)


async def _on_rfi_responded(event: Event) -> None:
    """``rfi.responded`` → notify the original requester."""
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    requester_id = data.get("raised_by") or data.get("requested_by_user_id") or data.get("ball_in_court")
    rfi_id = data.get("rfi_id") or data.get("id")
    if not requester_id or not rfi_id:
        return
    try:
        async with async_session_factory() as session:
            svc = NotificationService(session)
            await svc.create(
                user_id=requester_id,
                notification_type="rfi_responded",
                title_key="notifications.rfi.responded.title",
                body_key="notifications.rfi.responded.body",
                body_context={
                    "code": data.get("rfi_number") or "",
                    "title": data.get("subject") or "",
                },
                entity_type="rfi",
                entity_id=str(rfi_id),
                action_url=f"/rfi?id={rfi_id}",
            )
            await session.commit()
    except Exception:
        logger.debug("notifications: _on_rfi_responded failed", exc_info=True)


async def _resolve_project_owner(session, project_id: str) -> str | None:
    """Look up the owner_id for a project, returning the UUID as a string."""
    try:
        from app.modules.projects.models import Project

        proj = await session.get(Project, uuid_from_str(project_id))
        if proj is None:
            return None
        return str(proj.owner_id) if proj.owner_id else None
    except Exception:
        return None


def uuid_from_str(value: str):
    import uuid as _uuid

    try:
        return _uuid.UUID(str(value))
    except Exception:
        return value


async def _on_submittal_submitted(event: Event) -> None:
    """``submittal.submitted`` → notify the reviewer + project owner."""
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    reviewer_id = data.get("reviewer_id")
    project_id = data.get("project_id")
    submittal_id = data.get("submittal_id") or data.get("id")
    if not submittal_id:
        return
    targets: set[str] = set()
    if reviewer_id:
        targets.add(str(reviewer_id))
    try:
        async with async_session_factory() as session:
            if project_id:
                owner_id = await _resolve_project_owner(session, project_id)
                if owner_id:
                    targets.add(owner_id)
            if not targets:
                return
            svc = NotificationService(session)
            for uid in targets:
                await svc.create(
                    user_id=uid,
                    notification_type="submittal_submitted",
                    title_key="notifications.submittal.submitted.title",
                    body_key="notifications.submittal.submitted.body",
                    body_context={
                        "code": data.get("submittal_number") or "",
                        "title": data.get("title") or "",
                    },
                    entity_type="submittal",
                    entity_id=str(submittal_id),
                    action_url=f"/submittals?id={submittal_id}",
                )
            await session.commit()
    except Exception:
        logger.debug("notifications: _on_submittal_submitted failed", exc_info=True)


async def _on_submittal_approved(event: Event) -> None:
    """``submittal.approved`` → notify the submitter."""
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    submitter_id = data.get("submitted_by") or data.get("created_by")
    submittal_id = data.get("submittal_id") or data.get("id")
    if not submitter_id or not submittal_id:
        return
    try:
        async with async_session_factory() as session:
            svc = NotificationService(session)
            await svc.create(
                user_id=submitter_id,
                notification_type="submittal_approved",
                title_key="notifications.submittal.approved.title",
                body_key="notifications.submittal.approved.body",
                body_context={
                    "code": data.get("submittal_number") or "",
                    "title": data.get("title") or "",
                },
                entity_type="submittal",
                entity_id=str(submittal_id),
                action_url=f"/submittals?id={submittal_id}",
            )
            await session.commit()
    except Exception:
        logger.debug("notifications: _on_submittal_approved failed", exc_info=True)


async def _on_submittal_rejected(event: Event) -> None:
    """``submittal.rejected`` → notify the submitter with rejection reason."""
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    submitter_id = data.get("submitted_by") or data.get("created_by")
    submittal_id = data.get("submittal_id") or data.get("id")
    if not submitter_id or not submittal_id:
        return
    try:
        async with async_session_factory() as session:
            svc = NotificationService(session)
            await svc.create(
                user_id=submitter_id,
                notification_type="submittal_rejected",
                title_key="notifications.submittal.rejected.title",
                body_key="notifications.submittal.rejected.body",
                body_context={
                    "code": data.get("submittal_number") or "",
                    "title": data.get("title") or "",
                    "reason": (data.get("reason") or "")[:200],
                },
                entity_type="submittal",
                entity_id=str(submittal_id),
                action_url=f"/submittals?id={submittal_id}",
            )
            await session.commit()
    except Exception:
        logger.debug("notifications: _on_submittal_rejected failed", exc_info=True)


async def _on_submittal_revise_resubmit(event: Event) -> None:
    """``submittal.revise_resubmit`` → notify the submitter."""
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    submitter_id = data.get("submitted_by") or data.get("created_by")
    submittal_id = data.get("submittal_id") or data.get("id")
    if not submitter_id or not submittal_id:
        return
    try:
        async with async_session_factory() as session:
            svc = NotificationService(session)
            await svc.create(
                user_id=submitter_id,
                notification_type="submittal_revise_resubmit",
                title_key="notifications.submittal.revise_resubmit.title",
                body_key="notifications.submittal.revise_resubmit.body",
                body_context={
                    "code": data.get("submittal_number") or "",
                    "title": data.get("title") or "",
                    "reason": (data.get("reason") or "")[:200],
                },
                entity_type="submittal",
                entity_id=str(submittal_id),
                action_url=f"/submittals?id={submittal_id}",
            )
            await session.commit()
    except Exception:
        logger.debug("notifications: _on_submittal_revise_resubmit failed", exc_info=True)


async def _on_transmittal_issued(event: Event) -> None:
    """``transmittal.issued`` → notify the recipient."""
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    recipient_id = data.get("recipient_user_id")
    transmittal_id = data.get("transmittal_id") or data.get("id")
    if not recipient_id or not transmittal_id:
        return
    try:
        async with async_session_factory() as session:
            svc = NotificationService(session)
            await svc.create(
                user_id=recipient_id,
                notification_type="transmittal_issued",
                title_key="notifications.transmittal.issued.title",
                body_key="notifications.transmittal.issued.body",
                body_context={
                    "code": data.get("code") or "",
                    "title": data.get("title") or "",
                },
                entity_type="transmittal",
                entity_id=str(transmittal_id),
                action_url=f"/transmittals?id={transmittal_id}",
            )
            await session.commit()
    except Exception:
        logger.debug("notifications: _on_transmittal_issued failed", exc_info=True)


async def _on_transmittal_acknowledged(event: Event) -> None:
    """``transmittal.acknowledged`` → notify the original sender."""
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    sender_id = data.get("sender_user_id")
    transmittal_id = data.get("transmittal_id") or data.get("id")
    if not sender_id or not transmittal_id:
        return
    try:
        async with async_session_factory() as session:
            svc = NotificationService(session)
            await svc.create(
                user_id=sender_id,
                notification_type="transmittal_acknowledged",
                title_key="notifications.transmittal.acknowledged.title",
                body_key="notifications.transmittal.acknowledged.body",
                body_context={
                    "code": data.get("code") or "",
                    "title": data.get("title") or "",
                },
                entity_type="transmittal",
                entity_id=str(transmittal_id),
                action_url=f"/transmittals?id={transmittal_id}",
            )
            await session.commit()
    except Exception:
        logger.debug("notifications: _on_transmittal_acknowledged failed", exc_info=True)


async def _on_transmittal_responded(event: Event) -> None:
    """``transmittal.responded`` → notify the original sender."""
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    sender_id = data.get("sender_user_id")
    transmittal_id = data.get("transmittal_id") or data.get("id")
    if not sender_id or not transmittal_id:
        return
    try:
        async with async_session_factory() as session:
            svc = NotificationService(session)
            await svc.create(
                user_id=sender_id,
                notification_type="transmittal_responded",
                title_key="notifications.transmittal.responded.title",
                body_key="notifications.transmittal.responded.body",
                body_context={
                    "code": data.get("code") or "",
                    "title": data.get("title") or "",
                    "response_summary": (data.get("response_summary") or "")[:200],
                },
                entity_type="transmittal",
                entity_id=str(transmittal_id),
                action_url=f"/transmittals?id={transmittal_id}",
            )
            await session.commit()
    except Exception:
        logger.debug("notifications: _on_transmittal_responded failed", exc_info=True)


async def _on_file_comment_mention(event: Event) -> None:
    """``file_comments.mention.created`` → notify the mentioned user.

    Epic B / B1.  Fires once per resolved ``@mention`` in a file comment;
    the upstream service publishes the event detached so a notification
    failure cannot roll back the comment insert.
    """
    data = event.data or {}
    mentioned_user_id = data.get("mentioned_user_id")
    comment_id = data.get("comment_id")
    if not mentioned_user_id or not comment_id:
        return
    try:
        async with async_session_factory() as session:
            svc = NotificationService(session)
            file_kind = data.get("file_kind") or "document"
            file_id = data.get("file_id") or ""
            project_id = data.get("project_id") or ""
            action_url = (
                f"/files/{file_kind}/{file_id}?comment={comment_id}" if file_id else f"/projects/{project_id}/files"
            )
            await svc.create(
                user_id=mentioned_user_id,
                notification_type="file_comment_mention",
                title_key="notifications.file_comments.mention.title",
                body_key="notifications.file_comments.mention.body",
                body_context={
                    "excerpt": (data.get("body_excerpt") or "")[:160],
                },
                entity_type="file_comment",
                entity_id=str(comment_id),
                action_url=action_url,
                metadata={
                    "project_id": project_id,
                    "file_kind": file_kind,
                    "file_id": file_id,
                    "mention_id": data.get("mention_id"),
                },
            )
            await session.commit()
    except Exception:  # noqa: BLE001
        logger.debug("notifications: _on_file_comment_mention failed", exc_info=True)


# Declarative subscription map.  Adding a new event to this list
# is the ONE place to wire a new notification trigger — keeps the
# event topology auditable from a single grep.
_SUBSCRIPTIONS: list[tuple[str, callable]] = [  # type: ignore[type-arg]
    ("boq.boq.created", _on_boq_created),
    ("meeting.action_items_created", _on_meeting_action_items_created),
    ("bim_hub.element.deleted", _on_bim_element_deleted),
    ("cde.container.state_transitioned", _on_cde_state_transitioned),
    ("rfi.assigned", _on_rfi_assigned),
    ("rfi.responded", _on_rfi_responded),
    ("risk.assigned", _on_risk_assigned),
    ("submittal.submitted", _on_submittal_submitted),
    ("submittal.approved", _on_submittal_approved),
    ("submittal.rejected", _on_submittal_rejected),
    ("submittal.revise_resubmit", _on_submittal_revise_resubmit),
    ("transmittal.issued", _on_transmittal_issued),
    ("transmittal.acknowledged", _on_transmittal_acknowledged),
    ("transmittal.responded", _on_transmittal_responded),
    # Epic B / B1: file-comment @mention bridge
    ("file_comments.mention.created", _on_file_comment_mention),
]


def register_notification_subscribers() -> None:
    """Wire every entry of ``_SUBSCRIPTIONS`` into the global event bus.

    Idempotent: subscribing the same handler twice is harmless because
    the EventBus deduplicates on identity.  Called from the module
    ``on_startup`` hook so it runs once after the module loader has
    finished mounting routers.

    Also activates the wave-N subscription bundles introduced by the
    18-Modules Wave — each bundle owns its own list of upstream events
    and lives in its own file to keep PR-sized diffs reviewable.
    """
    for event_name, handler in _SUBSCRIPTIONS:
        event_bus.subscribe(event_name, handler)
    logger.info(
        "Notifications: subscribed to %d cross-module event(s)",
        len(_SUBSCRIPTIONS),
    )

    # Wave bundles — defer-import so unit tests that exercise only the
    # core list don't pay the cost of every module's event registration.
    from app.modules.notifications._wave1_subscribers import (
        register_wave1_notification_subscribers,
    )
    from app.modules.notifications._wave4_subscribers import (
        register_wave4_notification_subscribers,
    )
    from app.modules.notifications._wave5_cross_module_subscribers import (
        register_wave5_notification_subscribers,
    )
    from app.modules.notifications._wave23_subscribers import (
        register_wave23_notification_subscribers,
    )

    register_wave1_notification_subscribers()
    register_wave23_notification_subscribers()
    register_wave4_notification_subscribers()
    register_wave5_notification_subscribers()
