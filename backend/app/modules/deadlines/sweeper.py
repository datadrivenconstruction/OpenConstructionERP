# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cross-module overdue sweep - background push + escalation + digest.

The thin, impure glue that turns the read-only register (:mod:`service`) into a
proactive push. Modeled on ``approval_routes/sla_monitor.py``: a single
forever-loop wakes every :data:`POLL_INTERVAL_SECONDS`, never raises out, and is
started once from the application lifespan. No Celery, single process.

Per sweep, for every currently-overdue item across every project:

* notify the owner (or, when the owner is not a real user, the project
  managers) with an in-app ``deadline_overdue`` notification,
* fan the same event into the notification digest so users on an hourly/daily
  cadence get one rolled-up email instead of a stream,
* publish a ``deadlines.<module>.overdue`` timeline event, and
* once the item has sat past a grace window, escalate it to the project
  managers exactly once (``deadline_escalated``, metadata ``level=1``).

De-duplication is migration-free, exactly like ``sla_monitor``: before
notifying, the sweep reads the notification store for ``deadline_overdue``
rows on the same entity. One inside :data:`RENOTIFY_WINDOW_HOURS` silences
this tick; :data:`MAX_OVERDUE_NUDGES` of them silence the item for good, which
is what stops an item nobody resolves from being nudged forever.
The escalation tier reconstructs from the ``deadline_escalated`` notifications'
``metadata.level`` so a target is escalated at most once. This reuses the
*technique* of ``escalation_service`` (notification-store tier dedup), not the
service itself, which is bound to approval Instance/Route/Step and not reusable.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.database import async_session_factory
from app.modules.deadlines import service as deadlines_service
from app.modules.deadlines.schemas import DeadlineItem
from app.modules.notifications.models import Notification
from app.modules.notifications.service import NotificationService
from app.modules.projects.models import Project
from app.modules.users.models import User

logger = logging.getLogger(__name__)

# Deadlines are day-grained, so an hourly cadence is ample and cheaper than the
# approval SLA's 30-minute tick.
POLL_INTERVAL_SECONDS = 3600

# An overdue item is nudged at most once inside this window, so a long-overdue
# item does not spam its owner on every tick.
RENOTIFY_WINDOW_HOURS = 20.0

# ...and at most this many times in total. The window alone sets the interval
# between nudges, never their number, so an item that is never resolved is
# nudged for as long as the process runs. That is what it did: on the public
# demo the seeded items are overdue on purpose and nobody closes them, so the
# sweep re-sent the same reminders twice a day until the mail host disabled
# outbound sending for the whole account.
MAX_OVERDUE_NUDGES = 3

# Notification types carry the word "overdue"/"escalated" so the inbox severity
# classifier promotes them (see notifications/templates.py:_TYPE_TO_ICON).
OVERDUE_TYPE = "deadline_overdue"
ESCALATED_TYPE = "deadline_escalated"

# Days an item must sit overdue before it escalates up to the managers.
ESCALATE_GRACE_DAYS = 3


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _as_uuid(value: object) -> uuid.UUID | None:
    """Parse a value as a UUID, or None. Non-UUID owners (free text / role
    labels) are never notified directly - the sweep falls back to managers."""
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


async def _project_manager_ids(session: AsyncSession, project_id: uuid.UUID) -> list[uuid.UUID]:
    """Resolve the accountable managers for a project.

    Always includes the project owner (guaranteed present and accountable),
    plus any default-team member in a manager-ish role. Fail-soft: if the teams
    module is unavailable the owner alone is returned.
    """
    ids: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()

    owner = (await session.execute(select(Project.owner_id).where(Project.id == project_id))).scalar_one_or_none()
    if owner is not None:
        ids.append(owner)
        seen.add(owner)

    try:
        from app.modules.teams.models import Team, TeamMembership  # noqa: PLC0415

        team_id = (
            await session.execute(
                select(Team.id).where(Team.project_id == project_id, Team.is_default.is_(True)).limit(1)
            )
        ).scalar_one_or_none()
        if team_id is not None:
            rows = (
                await session.execute(
                    select(TeamMembership.user_id, TeamMembership.role).where(TeamMembership.team_id == team_id)
                )
            ).all()
            for uid, role in rows:
                if uid in seen:
                    continue
                r = (role or "").lower()
                if any(tok in r for tok in ("manag", "admin", "owner", "lead")):
                    ids.append(uid)
                    seen.add(uid)
    except Exception:  # noqa: BLE001 - teams module missing -> owner-only fallback
        logger.debug("Deadline manager resolve fell back to owner for project %s", project_id)

    return ids


async def _is_real_user(session: AsyncSession, user_id: uuid.UUID) -> bool:
    """True when the id names a row that exists in the users table.

    Parsing as a UUID says the value is well formed, not that anybody is behind
    it. ``owner_user_id`` is normalised from columns that carry no foreign key,
    so it can hold the id of a user who was never created or has since been
    removed. Notifying such an id violates the notification foreign key, and the
    failed flush poisons the session for the rest of the sweep.
    """
    found = await session.execute(select(User.id).where(User.id == user_id).limit(1))
    return found.scalar_one_or_none() is not None


async def _overdue_recipients(session: AsyncSession, item: DeadlineItem) -> list[uuid.UUID]:
    """Who to nudge for an overdue item: the owner if a real user, else managers.

    "A real user" has to mean present in the table. An id that merely parses is
    exactly the case the managers fallback exists to cover.
    """
    owner = _as_uuid(item.owner_user_id)
    if owner is not None and await _is_real_user(session, owner):
        return [owner]
    project_id = _as_uuid(item.project_id)
    if project_id is None:
        return []
    return await _project_manager_ids(session, project_id)


async def _already_notified(session: AsyncSession, item: DeadlineItem, now: datetime) -> bool:
    """True when this entity should not be nudged again right now.

    Two reasons to stay quiet, and the second one is the point of this
    function. The first is the window: one nudge per entity per
    :data:`RENOTIFY_WINDOW_HOURS`. The second is the ceiling: an entity gets
    at most :data:`MAX_OVERDUE_NUDGES` overdue nudges in its life.

    Without the ceiling this is a perpetual mailer. A due date that has passed
    stays passed, so an item nobody resolves qualifies on every sweep forever,
    and the window only sets the interval. On the public demo, where the
    seeded items are permanently overdue by design and no one ever closes
    them, that produced two bursts a day for as long as the instance was up.
    Re-nudging is worth something; re-nudging without end is not, and it is
    the same message every time.

    The query drops the time bound so the rows can answer both questions at
    once: a lifetime count for the ceiling, and the newest timestamp for the
    window.
    """
    cutoff = now - timedelta(hours=RENOTIFY_WINDOW_HOURS)
    rows = (
        (
            await session.execute(
                select(Notification).where(
                    Notification.entity_type == item.entity_type,
                    Notification.entity_id == item.entity_id,
                    Notification.notification_type == OVERDUE_TYPE,
                )
            )
        )
        .scalars()
        .all()
    )
    mine = [n for n in rows if (n.metadata_ or {}).get("module") == item.module]
    if len(mine) >= MAX_OVERDUE_NUDGES:
        return True
    return any(n.created_at is not None and n.created_at >= cutoff for n in mine)


async def _already_escalated(session: AsyncSession, item: DeadlineItem) -> bool:
    """True when this entity was already escalated (metadata level >= 1)."""
    rows = (
        (
            await session.execute(
                select(Notification).where(
                    Notification.entity_type == item.entity_type,
                    Notification.entity_id == item.entity_id,
                    Notification.notification_type == ESCALATED_TYPE,
                )
            )
        )
        .scalars()
        .all()
    )
    for n in rows:
        meta = n.metadata_ or {}
        if meta.get("module") == item.module and int(meta.get("level", 0)) >= 1:
            return True
    return False


def _overdue_context(item: DeadlineItem) -> dict[str, object]:
    return {"module": item.module, "title": item.title, "days_overdue": item.days_overdue}


async def _notify_overdue(session: AsyncSession, item: DeadlineItem, recipients: list[uuid.UUID]) -> None:
    """Create the in-app notification and fan the digest for each recipient.

    Called ONLY inside the renotify-dedup gate so a still-overdue item does not
    pile a fresh in-app row or digest row on every tick.
    """
    svc = NotificationService(session)
    context = _overdue_context(item)
    for recipient in recipients:
        await svc.create(
            user_id=recipient,
            notification_type=OVERDUE_TYPE,
            title_key="notifications.deadline.overdue.title",
            entity_type=item.entity_type,
            entity_id=item.entity_id,
            body_key="notifications.deadline.overdue.body",
            body_context=context,
            action_url=item.action_url,
            metadata={"module": item.module, "due_date": item.due_date, "level": 0},
        )
        # Digest fan-out: hourly/daily users get a rolled-up email digest (via
        # the existing NotificationDigestQueue + notification_worker flusher);
        # realtime users get an email dispatch event now.
        await svc.enqueue_or_dispatch(
            event_type=f"deadlines.{item.module}.overdue",
            user_id=recipient,
            payload={
                "title_key": "notifications.deadline.overdue.title",
                "body_key": "notifications.deadline.overdue.body",
                "body_context": context,
                "action_url": item.action_url,
                "entity_type": item.entity_type,
                "entity_id": item.entity_id,
            },
            channel="email",
        )


async def _maybe_escalate(session: AsyncSession, item: DeadlineItem, now: datetime) -> bool:
    """Escalate an item that has sat overdue past the grace window, once.

    Notifies the project managers (excluding the owner who already holds it),
    publishes ``deadlines.<module>.escalated``, and writes ``metadata.level=1``
    which doubles as the migration-free dedup record.
    """
    if item.days_overdue <= ESCALATE_GRACE_DAYS:
        return False
    if await _already_escalated(session, item):
        return False
    project_id = _as_uuid(item.project_id)
    if project_id is None:
        return False
    managers = await _project_manager_ids(session, project_id)
    owner = _as_uuid(item.owner_user_id)
    targets = [m for m in managers if m != owner]
    if not targets:
        # Nobody higher than the current holder - nothing to escalate to.
        return False

    svc = NotificationService(session)
    for recipient in targets:
        await svc.create(
            user_id=recipient,
            notification_type=ESCALATED_TYPE,
            title_key="notifications.deadline.escalated.title",
            entity_type=item.entity_type,
            entity_id=item.entity_id,
            body_key="notifications.deadline.escalated.body",
            body_context=_overdue_context(item),
            action_url=item.action_url,
            metadata={"module": item.module, "due_date": item.due_date, "level": 1},
        )
    event_bus.publish_detached(
        f"deadlines.{item.module}.escalated",
        {
            "entity_type": item.entity_type,
            "entity_id": item.entity_id,
            "project_id": item.project_id,
            "module": item.module,
            "days_overdue": item.days_overdue,
            "level": 1,
        },
        source_module="deadlines",
    )
    return True


async def sweep_overdue(session: AsyncSession, *, now: datetime | None = None) -> int:
    """Scan every overdue item and nudge/escalate the ones not yet handled.

    Operates on the supplied session and flushes its writes (via
    :class:`NotificationService`) but does not commit - the caller owns the
    transaction. Returns the number of fresh overdue nudges actioned this pass.

    Each item runs inside its own SAVEPOINT, so a row that cannot be written
    rolls back alone and the session stays usable for the rest of the pass.
    Catching the exception is not enough on its own: a failed flush leaves the
    session in a rollback-only state, and every later item would then raise
    ``PendingRollbackError`` instead of doing its work. That is how one
    unresolvable row silences deadline notifications for every project.
    """
    now = now or _utc_now()
    overdue = await deadlines_service.collect_overdue_for_sweep(session, now=now)
    actioned = 0
    for item in overdue:
        notified = False
        try:
            async with session.begin_nested():
                recipients = await _overdue_recipients(session, item)
                if recipients and not await _already_notified(session, item, now):
                    await _notify_overdue(session, item, recipients)
                    notified = True
                # Escalation is independently deduped (once per entity), so it
                # runs every tick but fires at most once past the grace window.
                await _maybe_escalate(session, item, now)
        except Exception:
            logger.exception("Deadline sweep failed for item %s", item.id)
            continue
        if notified:
            # Published only after the savepoint released, so the timeline never
            # announces a nudge whose write was rolled back.
            event_bus.publish_detached(
                f"deadlines.{item.module}.overdue",
                {
                    "entity_type": item.entity_type,
                    "entity_id": item.entity_id,
                    "project_id": item.project_id,
                    "module": item.module,
                    "days_overdue": item.days_overdue,
                    "due_date": item.due_date,
                },
                source_module="deadlines",
            )
            actioned += 1
    return actioned


async def _run_once() -> int:
    """Open a session, run one overdue sweep, commit. Returns nudges actioned."""
    async with async_session_factory() as session:
        actioned = await sweep_overdue(session)
        await session.commit()
    return actioned


async def _loop() -> None:
    """Forever-loop: sweep every :data:`POLL_INTERVAL_SECONDS`. Never raises out."""
    while True:
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        try:
            count = await _run_once()
            if count:
                logger.info("deadline sweeper raised %d overdue nudge(s)", count)
        except Exception:
            logger.exception("deadline sweeper tick failed")


def start_deadline_sweeper() -> asyncio.Task[None]:
    """Spawn the background overdue sweep as an asyncio task (wired from main.py)."""
    return asyncio.create_task(_loop())
