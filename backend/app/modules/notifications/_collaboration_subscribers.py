# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Notification subscriber for Project Discussion comments (issue #279).

Pre-#279 the collaboration module's ``create_comment`` published no event,
so a new comment on a discussion thread was invisible to everyone except
whoever happened to reload the thread. This subscriber listens for the
detached ``collaboration.comment.created`` event and notifies the OTHER
participants of the thread / project (never the author).

Recipient resolution (bounded and fail-safe):

    * every distinct prior commenter on the same entity (the people already
      taking part in the discussion), plus
    * the owning project's owner (so the project lead always sees activity),

    minus the comment author (nobody is notified about their own comment).

Because the integrations connector bridge (also issue #279) subscribes to
``notifications.notification.created``, these notifications automatically
reach Telegram / Slack / Teams / Discord / WhatsApp for any recipient who
connected a chat connector.

Conventions match the other notification subscribers:
    1. Pull the hints out of ``event.data``; skip silently if the required
       ones are missing - the subscriber must never break a successful
       upstream comment insert.
    2. Open a short-lived isolated session via ``async_session_factory()``.
    3. Catch all exceptions and log at debug.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select

from app.core.events import Event, event_bus
from app.database import async_session_factory
from app.modules.notifications.service import NotificationService

logger = logging.getLogger(__name__)

# Hard cap so a very busy thread cannot fan out an unbounded number of
# notification rows from a single comment.
_MAX_RECIPIENTS = 50


def _coerce_uuid(value: object) -> uuid.UUID | None:
    """Parse ``value`` into a UUID, returning None when it is not one."""
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


async def _resolve_prior_commenters(
    session,
    entity_type: str,
    entity_id: str,
) -> set[str]:
    """Return the distinct set of author ids who have commented on the entity."""
    from app.modules.collaboration.models import Comment

    try:
        stmt = select(Comment.author_id).where(
            Comment.entity_type == entity_type,
            Comment.entity_id == entity_id,
        )
        rows = (await session.execute(stmt)).scalars().all()
        return {str(r) for r in rows if r is not None}
    except Exception:  # noqa: BLE001 - resolution is best-effort
        logger.debug(
            "notifications: prior-commenter resolve failed for %s/%s",
            entity_type,
            entity_id,
            exc_info=True,
        )
        return set()


async def _resolve_project_owner(session, project_id: str) -> str | None:
    """Look up the owner_id for a project as a string, or None."""
    pid = _coerce_uuid(project_id)
    if pid is None:
        return None
    try:
        from app.modules.projects.models import Project

        proj = await session.get(Project, pid)
        if proj is None or not proj.owner_id:
            return None
        return str(proj.owner_id)
    except Exception:  # noqa: BLE001 - best-effort
        return None


async def _on_collaboration_comment_created(event: Event) -> None:
    """``collaboration.comment.created`` -> notify other thread participants.

    Notifies prior commenters on the same entity plus the project owner,
    excluding the author. Best-effort and isolated: any failure is logged at
    debug and swallowed so it can never affect the comment insert.
    """
    data = event.data or {}
    entity_type = str(data.get("entity_type") or "").strip()
    entity_id = str(data.get("entity_id") or "").strip()
    comment_id = data.get("comment_id")
    author_id = str(data.get("author_id") or "").strip()
    if not entity_type or not entity_id or not comment_id:
        return

    try:
        async with async_session_factory() as session:
            recipients: set[str] = await _resolve_prior_commenters(session, entity_type, entity_id)

            project_id = data.get("project_id")
            if project_id:
                owner_id = await _resolve_project_owner(session, str(project_id))
                if owner_id:
                    recipients.add(owner_id)

            # Never notify the author about their own comment.
            if author_id:
                recipients.discard(author_id)

            recipients_list = sorted(recipients)[:_MAX_RECIPIENTS]
            if not recipients_list:
                return

            # Deep-link to the commented entity. A project-level discussion
            # points at the project route; any other entity has no discussion
            # page of its own, so the reader lands on its project, or on the
            # collaboration hub when the event carries none.
            if entity_type == "project":
                action_url = f"/projects/{entity_id}"
            elif project_id:
                action_url = f"/projects/{project_id}"
            else:
                action_url = "/collaboration"

            svc = NotificationService(session)
            await svc.notify_users(
                recipients_list,
                notification_type="comment_added",
                title_key="notifications.collaboration.comment_added.title",
                body_key="notifications.collaboration.comment_added.body",
                body_context={
                    "entity_type": entity_type.replace("_", " "),
                    "excerpt": str(data.get("body_excerpt") or "")[:160],
                },
                entity_type=entity_type,
                entity_id=entity_id,
                action_url=action_url,
                metadata={
                    "comment_id": str(comment_id),
                    "project_id": str(project_id or ""),
                    "parent_comment_id": str(data.get("parent_comment_id") or ""),
                },
            )
            await session.commit()
    except Exception:  # noqa: BLE001 - never break the upstream comment insert
        logger.debug("notifications: _on_collaboration_comment_created failed", exc_info=True)


def register_collaboration_notification_subscribers() -> None:
    """Wire the Project Discussion comment event into in-app notifications.

    Idempotent - the event bus deduplicates handlers by identity is NOT
    guaranteed, so guard on the already-registered qualname.
    """
    existing = event_bus.list_handlers().get("collaboration.comment.created", [])
    if _on_collaboration_comment_created.__qualname__ in existing:
        return
    event_bus.subscribe_once("collaboration.comment.created", _on_collaboration_comment_created)
    logger.info("Notifications: subscribed to collaboration.comment.created")


__all__ = [
    "_on_collaboration_comment_created",
    "register_collaboration_notification_subscribers",
]
