# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Notification service - business logic for in-app notifications.

Stateless service layer.  Wraps the repository and provides convenience
helpers like ``notify_users`` for bulk delivery.

Event publishing (slice E):
    notifications.notification.created  - new notification row
    notifications.notification.read     - single mark-read
    notifications.notification.bulk_read - mark-all-read
    notifications.notification.deleted  - single delete

Preferences + digest (Wave 3 / T9):
    set_preference / get_preferences           - per-channel user prefs
    enqueue_or_dispatch                        - pref-aware fan-out
    flush_digest_queue                         - hourly/daily batch flush
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.modules.notifications.models import (
    Notification,
    NotificationDigestQueue,
    NotificationPreference,
)
from app.modules.notifications.repository import NotificationRepository

logger = logging.getLogger(__name__)
_logger_ev = logging.getLogger(__name__ + ".events")


async def _safe_publish(name: str, data: dict, source_module: str = "oe_notifications") -> None:
    """Best-effort event publish - never blocks the caller on failure."""
    try:
        event_bus.publish_detached(name, data, source_module=source_module)
    except Exception:
        _logger_ev.debug("Event publish skipped: %s", name)


class NotificationService:
    """Business logic for notification operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = NotificationRepository(session)

    # ── Create ──────────────────────────────────────────────────────────────

    async def create(
        self,
        user_id: uuid.UUID | str,
        notification_type: str,
        title_key: str,
        *,
        entity_type: str | None = None,
        entity_id: str | None = None,
        body_key: str | None = None,
        body_context: dict[str, Any] | None = None,
        action_url: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Notification:
        """Create a single notification for one user."""
        uid = uuid.UUID(str(user_id)) if not isinstance(user_id, uuid.UUID) else user_id
        notification = Notification(
            user_id=uid,
            notification_type=notification_type,
            entity_type=entity_type,
            entity_id=entity_id,
            title_key=title_key,
            body_key=body_key,
            body_context=body_context or {},
            action_url=action_url,
            metadata_=metadata or {},
        )
        notification = await self.repo.create(notification)

        await _safe_publish(
            "notifications.notification.created",
            {
                "notification_id": str(notification.id),
                "user_id": str(uid),
                "notification_type": notification_type,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "title_key": title_key,
                # Mirror the fields the in-app NotificationResponse carries so
                # connector sinks (Telegram/Slack/Teams/Discord/WhatsApp) can
                # render the SAME interpolated title + body. Without body_key /
                # body_context the bridge rendered placeholders raw and dropped
                # the body entirely.
                "body_key": body_key,
                "body_context": body_context or {},
                "action_url": action_url,
            },
        )

        logger.info(
            "Notification created: type=%s user=%s title_key=%s",
            notification_type,
            uid,
            title_key,
        )
        return notification

    async def notify_users(
        self,
        user_ids: list[uuid.UUID | str],
        notification_type: str,
        title_key: str,
        *,
        entity_type: str | None = None,
        entity_id: str | None = None,
        body_key: str | None = None,
        body_context: dict[str, Any] | None = None,
        action_url: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> list[Notification]:
        """Create the same notification for multiple recipients."""
        notifications: list[Notification] = []
        for uid in user_ids:
            n = await self.create(
                user_id=uid,
                notification_type=notification_type,
                title_key=title_key,
                entity_type=entity_type,
                entity_id=entity_id,
                body_key=body_key,
                body_context=body_context,
                action_url=action_url,
                metadata=metadata,
            )
            notifications.append(n)
        logger.info(
            "Bulk notifications sent: type=%s count=%d title_key=%s",
            notification_type,
            len(notifications),
            title_key,
        )
        return notifications

    # ── Read ────────────────────────────────────────────────────────────────

    async def list_for_user(
        self,
        user_id: uuid.UUID | str,
        *,
        is_read: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Notification], int]:
        """List notifications for a user."""
        uid = uuid.UUID(str(user_id)) if not isinstance(user_id, uuid.UUID) else user_id
        return await self.repo.list_for_user(uid, is_read=is_read, limit=limit, offset=offset)

    async def count_unread(self, user_id: uuid.UUID | str) -> int:
        """Count unread notifications for a user."""
        uid = uuid.UUID(str(user_id)) if not isinstance(user_id, uuid.UUID) else user_id
        return await self.repo.count_unread(uid)

    # ── Mark read ───────────────────────────────────────────────────────────

    async def mark_read(self, notification_id: uuid.UUID, user_id: uuid.UUID | str) -> bool:
        """Mark a single notification as read."""
        uid = uuid.UUID(str(user_id)) if not isinstance(user_id, uuid.UUID) else user_id
        ok = await self.repo.mark_read(notification_id, uid)
        if ok:
            await _safe_publish(
                "notifications.notification.read",
                {
                    "notification_id": str(notification_id),
                    "user_id": str(uid),
                },
            )
        return ok

    async def mark_all_read(self, user_id: uuid.UUID | str) -> int:
        """Mark all notifications as read for a user."""
        uid = uuid.UUID(str(user_id)) if not isinstance(user_id, uuid.UUID) else user_id
        count = await self.repo.mark_all_read(uid)
        if count:
            await _safe_publish(
                "notifications.notification.bulk_read",
                {
                    "user_id": str(uid),
                    "count": count,
                },
            )
        logger.info("Marked %d notifications as read for user=%s", count, uid)
        return count

    # ── Delete ──────────────────────────────────────────────────────────────

    async def delete(self, notification_id: uuid.UUID, user_id: uuid.UUID | str) -> bool:
        """Delete a single notification."""
        uid = uuid.UUID(str(user_id)) if not isinstance(user_id, uuid.UUID) else user_id
        ok = await self.repo.delete_by_id(notification_id, uid)
        if ok:
            await _safe_publish(
                "notifications.notification.deleted",
                {
                    "notification_id": str(notification_id),
                    "user_id": str(uid),
                },
            )
        return ok

    async def delete_old(self, days: int = 90) -> int:
        """Cleanup: delete notifications older than ``days``."""
        count = await self.repo.delete_old(days)
        if count:
            logger.info("Cleaned up %d old notifications (older than %d days)", count, days)
        return count

    # ── Preferences (Wave 3 / T9) ──────────────────────────────────────────

    async def set_preference(
        self,
        user_id: uuid.UUID | str,
        event_type: str,
        channel: str,
        *,
        enabled: bool = True,
        digest: str = "realtime",
    ) -> NotificationPreference:
        """Upsert a per-user, per-event-type, per-channel preference.

        Channel must be one of ``email|inapp|webhook|none``; digest must be
        one of ``realtime|hourly|daily``.  Validation is enforced by the
        Pydantic schema at the router edge - service layer trusts callers.
        """
        uid = uuid.UUID(str(user_id)) if not isinstance(user_id, uuid.UUID) else user_id
        stmt = select(NotificationPreference).where(
            NotificationPreference.user_id == uid,
            NotificationPreference.event_type == event_type,
            NotificationPreference.channel == channel,
        )
        existing = (await self.session.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            existing.enabled = enabled
            existing.digest = digest
            await self.session.flush()
            return existing

        pref = NotificationPreference(
            user_id=uid,
            event_type=event_type,
            channel=channel,
            enabled=enabled,
            digest=digest,
        )
        self.session.add(pref)
        await self.session.flush()
        return pref

    async def get_preferences(
        self,
        user_id: uuid.UUID | str,
    ) -> list[NotificationPreference]:
        """Fetch all notification preferences for a user."""
        uid = uuid.UUID(str(user_id)) if not isinstance(user_id, uuid.UUID) else user_id
        stmt = select(NotificationPreference).where(
            NotificationPreference.user_id == uid,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_preference(
        self,
        user_id: uuid.UUID,
        event_type: str,
        channel: str,
    ) -> NotificationPreference | None:
        """Internal helper - look up a single pref row."""
        stmt = select(NotificationPreference).where(
            NotificationPreference.user_id == user_id,
            NotificationPreference.event_type == event_type,
            NotificationPreference.channel == channel,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    # ── Dispatch + digest queue (Wave 3 / T9) ──────────────────────────────

    async def enqueue_or_dispatch(
        self,
        event_type: str,
        user_id: uuid.UUID | str,
        payload: dict[str, Any],
        channel: str = "inapp",
        *,
        deferred: list[tuple[str, dict[str, Any]]] | None = None,
    ) -> str:
        """Route an event for a user honouring their preference.

        Returns one of: ``"dispatched"``, ``"queued"``, ``"suppressed"``.

        * No preference row, or pref says ``realtime`` → dispatch immediately
          via the existing notification sink (in-app store for ``inapp``,
          ``notifications.dispatch.{channel}`` event for everything else).
        * Pref disabled, or channel ``none`` → suppress.
        * Pref says ``hourly`` / ``daily`` → append to the digest queue with
          ``scheduled_for = now() + interval``.
        """
        uid = uuid.UUID(str(user_id)) if not isinstance(user_id, uuid.UUID) else user_id

        if channel == "none":
            return "suppressed"

        pref = await self.get_preference(uid, event_type, channel)
        cadence = "realtime"
        if pref is not None:
            if not pref.enabled:
                return "suppressed"
            cadence = pref.digest

        if cadence == "realtime":
            await self._dispatch(event_type, uid, payload, channel, deferred=deferred)
            return "dispatched"

        # Queue for digest.
        interval = timedelta(hours=1) if cadence == "hourly" else timedelta(days=1)
        scheduled = datetime.now(UTC) + interval
        row = NotificationDigestQueue(
            user_id=uid,
            event_type=event_type,
            channel=channel,
            payload=payload or {},
            scheduled_for=scheduled,
        )
        self.session.add(row)
        await self.session.flush()
        return "queued"

    async def _dispatch(
        self,
        event_type: str,
        user_id: uuid.UUID,
        payload: dict[str, Any],
        channel: str,
        *,
        deferred: list[tuple[str, dict[str, Any]]] | None = None,
    ) -> None:
        """Send a single notification through the requested channel.

        ``inapp`` writes to the existing ``oe_notifications_notification``
        table via the service.  All other channels (``email``, ``webhook``)
        are surfaced as event-bus events so out-of-process sinks can pick
        them up without bloating this module.
        """
        if channel == "inapp":
            title_key = payload.get("title_key") or f"notifications.{event_type}.title"
            await self.create(
                user_id=user_id,
                notification_type=event_type,
                title_key=title_key,
                body_key=payload.get("body_key"),
                body_context=payload.get("body_context") or {},
                action_url=payload.get("action_url"),
                entity_type=payload.get("entity_type"),
                entity_id=payload.get("entity_id"),
            )
            return

        name = f"notifications.dispatch.{channel}"
        data = {
            "user_id": str(user_id),
            "event_type": event_type,
            "channel": channel,
            "payload": payload,
        }
        if deferred is not None:
            deferred.append((name, data))
            return
        await _safe_publish(name, data)

    async def flush_digest_queue(
        self,
        channel: str,
        before: datetime | None = None,
    ) -> int:
        """Flush pending digest rows for ``channel`` whose ``scheduled_for``
        is ``<= before``.

        Rows are grouped by ``(user_id, channel)`` and a single combined
        notification per group is dispatched, then every contributing row
        is stamped with ``sent_at``.  Returns the total number of queued
        rows that were sent (NOT the number of digests).
        """
        cutoff = before if before is not None else datetime.now(UTC)
        stmt = select(NotificationDigestQueue).where(
            NotificationDigestQueue.channel == channel,
            NotificationDigestQueue.scheduled_for <= cutoff,
            NotificationDigestQueue.sent_at.is_(None),
        )
        rows = list((await self.session.execute(stmt)).scalars().all())
        if not rows:
            return 0

        # Claim before sending. The in-process worker flushes every five
        # minutes and the admin endpoint can flush on demand; two flushes that
        # both read the same unsent rows used to both send the digest. The
        # conditional UPDATE takes the row locks, so a concurrent flush waits
        # for this one to commit and then finds nothing left to claim.
        now = datetime.now(UTC)
        claimed = set(
            (
                await self.session.execute(
                    update(NotificationDigestQueue)
                    .where(
                        NotificationDigestQueue.id.in_([r.id for r in rows]),
                        NotificationDigestQueue.sent_at.is_(None),
                    )
                    .values(sent_at=now)
                    .returning(NotificationDigestQueue.id)
                )
            )
            .scalars()
            .all()
        )
        rows = [r for r in rows if r.id in claimed]
        if not rows:
            return 0

        # Group by user.  Channel is already filtered, so the key is just
        # the user id.
        by_user: dict[uuid.UUID, list[NotificationDigestQueue]] = {}
        for r in rows:
            by_user.setdefault(r.user_id, []).append(r)

        sent_total = 0
        for uid, group in by_user.items():
            events_summary = [
                {
                    "event_type": r.event_type,
                    "payload": r.payload or {},
                    "queued_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in group
            ]
            combined_payload = {
                "channel": channel,
                "count": len(group),
                "events": events_summary,
            }
            if channel == "inapp":
                await self.create(
                    user_id=uid,
                    notification_type="notifications.digest",
                    title_key="notifications.digest.title",
                    body_key="notifications.digest.body",
                    body_context={"count": len(group), "channel": channel},
                    metadata=combined_payload,
                )
            else:
                await _safe_publish(
                    f"notifications.dispatch.{channel}",
                    {
                        "user_id": str(uid),
                        "event_type": "notifications.digest",
                        "channel": channel,
                        "payload": combined_payload,
                    },
                )
            sent_total += len(group)

        await self.session.flush()
        logger.info(
            "Notification digest flush: channel=%s users=%d rows=%d",
            channel,
            len(by_user),
            sent_total,
        )
        return sent_total


# ── Background flusher stub (manual trigger via router) ────────────────────


async def _DIGEST_FLUSHER(channel: str = "email") -> int:
    """Stub background-task hook - opens its own session + flushes once.

    Real cron / Celery wiring is out of scope for T9; the router exposes a
    manual-trigger endpoint that calls this so operators (and tests) can
    drain the queue on demand.
    """
    from app.database import async_session_factory

    async with async_session_factory() as session:
        svc = NotificationService(session)
        count = await svc.flush_digest_queue(channel)
        await session.commit()
        return count


# ── Known event-type catalogue (Wave 3 / T9) ───────────────────────────────


KNOWN_EVENT_TYPES: list[dict[str, str]] = [
    # BOQ
    {"event_type": "boq.boq.created", "module": "boq", "description": "BOQ created"},
    {"event_type": "boq.position.created", "module": "boq", "description": "BOQ position created"},
    {"event_type": "boq.position.updated", "module": "boq", "description": "BOQ position updated"},
    {
        "event_type": "boq.positions.resource_propagated",
        "module": "boq",
        "description": "Shared resource change applied to other BOQ positions",
    },
    # Change orders
    {
        "event_type": "changeorders.approval.advanced",
        "module": "changeorders",
        "description": "Change-order approval advanced",
    },
    {"event_type": "changeorders.approval.approved", "module": "changeorders", "description": "Change-order approved"},
    {"event_type": "changeorders.approval.rejected", "module": "changeorders", "description": "Change-order rejected"},
    # Risk
    {"event_type": "risk.assigned", "module": "risk", "description": "Risk assigned"},
    {"event_type": "risk.simulated", "module": "risk", "description": "Risk simulation completed"},
    # RFI
    {"event_type": "rfi.assigned", "module": "rfi", "description": "RFI assigned to you"},
    {"event_type": "rfi.responded", "module": "rfi", "description": "RFI response received"},
    # Submittals
    {"event_type": "submittal.submitted", "module": "submittals", "description": "Submittal submitted"},
    {"event_type": "submittal.approved", "module": "submittals", "description": "Submittal approved"},
    {"event_type": "submittal.rejected", "module": "submittals", "description": "Submittal rejected"},
    {"event_type": "submittal.revise_resubmit", "module": "submittals", "description": "Submittal needs revision"},
    # Transmittals
    {"event_type": "transmittal.issued", "module": "transmittals", "description": "Transmittal issued"},
    {"event_type": "transmittal.acknowledged", "module": "transmittals", "description": "Transmittal acknowledged"},
    {"event_type": "transmittal.responded", "module": "transmittals", "description": "Transmittal responded"},
    # Meetings
    {"event_type": "meeting.action_items_created", "module": "meetings", "description": "Action item assigned to you"},
    # Procurement
    {"event_type": "procurement.po.created", "module": "procurement", "description": "Purchase order created"},
    {"event_type": "procurement.po.approved", "module": "procurement", "description": "Purchase order approved"},
    # CDE
    {"event_type": "cde.container.state_transitioned", "module": "cde", "description": "CDE container state changed"},
    # BIM
    {"event_type": "bim_hub.element.deleted", "module": "bim_hub", "description": "BIM element deleted"},
    # HSE
    {"event_type": "hse.incident.created", "module": "hse", "description": "Safety incident reported"},
    {"event_type": "hse.corrective_action.assigned", "module": "hse", "description": "Corrective action assigned"},
    # Tendering
    {"event_type": "tendering.bid.received", "module": "tendering", "description": "Tender bid received"},
    {"event_type": "tendering.addendum.published", "module": "tendering", "description": "Tender addendum published"},
    # File comments (Epic B / B1)
    {
        "event_type": "file_comments.mention.created",
        "module": "file_comments",
        "description": "You were @mentioned in a file comment",
    },
    # Project discussions (collaboration comments, issue #279)
    {
        "event_type": "collaboration.comment.created",
        "module": "collaboration",
        "description": "New comment in a discussion you take part in",
    },
    # Cross-module overdue escalation (deadlines register + sweep, item #18)
    {
        "event_type": "deadlines.correspondence.overdue",
        "module": "deadlines",
        "description": "Correspondence past its response deadline",
    },
    {
        "event_type": "deadlines.qms_ncr_action.overdue",
        "module": "deadlines",
        "description": "NCR corrective action overdue",
    },
    {
        "event_type": "deadlines.punchlist.overdue",
        "module": "deadlines",
        "description": "Punch item overdue",
    },
    {
        "event_type": "deadlines.rfi.overdue",
        "module": "deadlines",
        "description": "RFI past the date its answer is due",
    },
    {
        "event_type": "deadlines.submittals.overdue",
        "module": "deadlines",
        "description": "Submittal past the date it must be returned",
    },
    {
        "event_type": "deadlines.variations.overdue",
        "module": "deadlines",
        "description": "Variation request past its decision deadline",
    },
    {
        "event_type": "deadlines.temporary_works.overdue",
        "module": "deadlines",
        "description": "Temporary-works design check overdue",
    },
    {
        "event_type": "deadlines.temporary_works_permit.overdue",
        "module": "deadlines",
        "description": "Temporary-works permit past the end of its validity",
    },
    {
        "event_type": "deadlines.defects_liability.overdue",
        "module": "deadlines",
        "description": "Defect past its rectification date",
    },
    {
        "event_type": "deadlines.inspections.overdue",
        "module": "deadlines",
        "description": "Quality inspection still scheduled after its date",
    },
    {
        "event_type": "deadlines.compliance_docs.overdue",
        "module": "deadlines",
        "description": "Insurance / permit / certification past its expiry",
    },
    {
        "event_type": "deadlines.bid_management.overdue",
        "module": "deadlines",
        "description": "Bid package past its submission deadline",
    },
    {
        "event_type": "deadlines.signing.overdue",
        "module": "deadlines",
        "description": "Signature session past its expiry",
    },
]
