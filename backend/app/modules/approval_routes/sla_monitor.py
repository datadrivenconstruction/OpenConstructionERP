# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Approval-SLA breach monitor - background sweep + reminder notifications.

The pure verdict logic lives in :mod:`app.modules.approval_routes.sla_engine`
(no I/O, unit-tested on py3.11). This module is the thin, impure glue that:

* scans every still-pending approval instance whose current step carries an
  ``sla_hours`` budget,
* reconstructs when that step became active (the schema has no per-step start
  timestamp - see :func:`sla_engine.current_step_baseline`),
* asks the engine whether the step has breached its SLA, and
* for a fresh breach, notifies the responsible approver and publishes an
  ``approval.overdue`` event so the unified project timeline records it.

It mirrors the in-process asyncio scheduler pattern used elsewhere in the app
(see :mod:`app.modules.ai_agents.scheduler`): a single forever-loop wakes every
:data:`POLL_INTERVAL_SECONDS`, never raises out, and is started once from the
application lifespan. No Celery, single process, which is acceptable for the
single-process deploy.

De-duplication is migration-free: before sending a reminder the monitor checks
the notification store for a recent ``approval_overdue`` row already raised for
the same instance and step, so a long-overdue approval is nudged at most once
per :data:`RENOTIFY_WINDOW_HOURS`, not on every tick, and at most
:data:`MAX_STEP_REMINDERS` times for that step in total.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.database import async_session_factory
from app.modules.approval_routes import delegation_engine, escalation_service, sla_engine
from app.modules.approval_routes.delegation_engine import DelegationView
from app.modules.approval_routes.models import Delegation, Instance, Route, Step, StepState
from app.modules.approval_routes.service import delegation_views_from_rows
from app.modules.notifications.models import Notification
from app.modules.notifications.service import NotificationService

logger = logging.getLogger(__name__)

# How often the breach sweep runs. SLA windows are measured in hours, so a
# 30-minute cadence is ample and keeps the background cost negligible.
POLL_INTERVAL_SECONDS = 1800

# A breached step is nudged at most once inside this window, so a stuck
# approval does not spam its approver on every tick.
RENOTIFY_WINDOW_HOURS = 20.0

# ...and at most this many times for the same step. A window bounds the rate,
# not the total, and a step nobody ever approves would otherwise be reminded
# about forever. Advancing to the next step starts a fresh count.
MAX_STEP_REMINDERS = 3

# notification_type carries the word "overdue" on purpose: the inbox severity
# classifier promotes overdue/breach/escalation notifications to "critical".
OVERDUE_TYPE = "approval_overdue"
ENTITY_TYPE = "approval_instance"


def _utc_now() -> datetime:
    return datetime.now(UTC)


async def _prior_step_decisions(session: AsyncSession, instance: Instance) -> list[datetime | None]:
    """Decision timestamps on the step immediately before the current one.

    Empty for the first step (there is no prior step). The latest of these is
    when the current step became active - see
    :func:`sla_engine.current_step_baseline`.
    """
    if instance.current_step_ordinal <= 1:
        return []
    rows = await session.execute(
        select(StepState.decided_at)
        .join(Step, Step.id == StepState.step_id)
        .where(
            StepState.instance_id == instance.id,
            Step.ordinal == instance.current_step_ordinal - 1,
        )
    )
    return list(rows.scalars().all())


async def _already_notified(
    session: AsyncSession,
    instance_id: uuid.UUID,
    step_ordinal: int,
    now: datetime,
) -> bool:
    """True when this instance+step should not be nudged again right now.

    Keyed on the instance id (stored in ``entity_id``) plus the step ordinal
    (stored in the notification metadata), so advancing to a new step lets a
    fresh reminder through while a stuck step is nudged only once per window.

    The window sets the interval between reminders and never their number, so
    a step that is never approved is reminded about for as long as the process
    runs. :data:`MAX_STEP_REMINDERS` bounds it. Advancing the step resets the
    count, which is the behaviour worth keeping: a new step is a new fact,
    the fourth reminder about the same one is not.
    """
    cutoff = now - timedelta(hours=RENOTIFY_WINDOW_HOURS)
    rows = await session.execute(
        select(Notification).where(
            Notification.entity_type == ENTITY_TYPE,
            Notification.entity_id == str(instance_id),
            Notification.notification_type == OVERDUE_TYPE,
        )
    )
    mine = [n for n in rows.scalars().all() if (n.metadata_ or {}).get("step_ordinal") == step_ordinal]
    if len(mine) >= MAX_STEP_REMINDERS:
        return True
    return any(n.created_at is not None and n.created_at >= cutoff for n in mine)


async def _raise_breach(
    session: AsyncSession,
    instance: Instance,
    step: Step,
    route: Route,
    status: sla_engine.BreachStatus,
    now: datetime,
    delegations: list[DelegationView],
) -> None:
    """Notify the responsible approver and publish the timeline event.

    The recipient is, in order of precedence: the per-instance assignee
    override (a one-tap reassignment), the named step approver resolved through
    any active out-of-office delegation, or - for a role-based step the engine
    cannot expand to members - the user who started the instance. This keeps a
    breach nudge actionable rather than a silent miss.
    """
    overdue = round(status.hours_overdue, 1)
    ordinal = instance.current_step_ordinal
    if instance.current_assignee_user_id is not None:
        recipient = instance.current_assignee_user_id
    elif step.approver_user_id is not None:
        recipient = delegation_engine.resolve_delegate(
            step.approver_user_id,
            delegations,
            now=now,
            project_id=route.project_id,
        )
    else:
        recipient = instance.started_by

    if recipient is not None:
        await NotificationService(session).create(
            user_id=recipient,
            notification_type=OVERDUE_TYPE,
            title_key="notifications.approval.overdue.title",
            entity_type=ENTITY_TYPE,
            entity_id=str(instance.id),
            body_key="notifications.approval.overdue.body",
            body_context={
                "target_kind": instance.target_kind,
                "step_ordinal": ordinal,
                "hours_overdue": overdue,
            },
            action_url=f"/approvals/{instance.id}",
            metadata={
                "step_ordinal": ordinal,
                "hours_overdue": overdue,
                "sla_hours": step.sla_hours,
                "due_at": status.due_at.isoformat() if status.due_at else None,
            },
        )

    project_id = route.project_id
    event_bus.publish_detached(
        "approval.overdue",
        {
            "id": str(instance.id),
            "project_id": str(project_id) if project_id else None,
            "target_kind": instance.target_kind,
            "target_id": str(instance.target_id),
            "step_ordinal": ordinal,
            "hours_overdue": overdue,
            "sla_hours": step.sla_hours,
        },
        source_module="approval_routes",
    )


async def _maybe_escalate(
    session: AsyncSession,
    instance: Instance,
    route: Route,
    now: datetime,
) -> None:
    """Escalate a breached step to the next authority once past its grace window.

    Delegates the decision to :func:`escalation_service.evaluate_escalation`,
    which derives the chain from the route's later approvers and reads the
    already-escalated set from the notification store. When an escalation is due
    the next target is notified and an ``approval.escalated`` event is published;
    the notification doubles as the de-dup record so each target is escalated to
    at most once per step.
    """
    view = await escalation_service.evaluate_escalation(session, instance, route, now=now)
    if not (view.should_escalate and view.next_target):
        return
    try:
        recipient = uuid.UUID(view.next_target)
    except (ValueError, TypeError):
        return

    await NotificationService(session).create(
        user_id=recipient,
        notification_type=escalation_service.ESCALATED_TYPE,
        title_key="notifications.approval.escalated.title",
        entity_type=ENTITY_TYPE,
        entity_id=str(instance.id),
        body_key="notifications.approval.escalated.body",
        body_context={
            "target_kind": instance.target_kind,
            "step_ordinal": view.current_step_ordinal,
            "level": view.level,
        },
        action_url=f"/approvals/{instance.id}",
        metadata={
            "step_ordinal": view.current_step_ordinal,
            "escalated_to": view.next_target,
            "level": view.level,
            "severity": view.severity,
        },
    )

    project_id = route.project_id
    event_bus.publish_detached(
        "approval.escalated",
        {
            "id": str(instance.id),
            "project_id": str(project_id) if project_id else None,
            "target_kind": instance.target_kind,
            "target_id": str(instance.target_id),
            "step_ordinal": view.current_step_ordinal,
            "escalated_to": view.next_target,
            "level": view.level,
            "severity": view.severity,
        },
        source_module="approval_routes",
    )


async def check_sla_breaches(session: AsyncSession, *, now: datetime | None = None) -> int:
    """Scan pending instances and nudge any whose current step has breached.

    Operates on the supplied session and flushes its writes (via
    :class:`NotificationService`) but does not commit - the caller owns the
    transaction. Returns the number of fresh breaches actioned this pass.

    Only the current step of each pending instance is considered, and only when
    that step declares an ``sla_hours`` budget. A per-instance failure is logged
    and skipped so one bad row never stalls the sweep.
    """
    now = now or _utc_now()
    actioned = 0

    # Load active out-of-office delegations once per sweep so a breached
    # approval still nudges whoever actually covers it while the named
    # approver is away (the pure engine resolves the chain per instance).
    delegation_rows = (await session.execute(select(Delegation).where(Delegation.is_active.is_(True)))).scalars().all()
    delegations = delegation_views_from_rows(list(delegation_rows))

    result = await session.execute(
        select(Instance, Step, Route)
        .join(Step, and_(Step.route_id == Instance.route_id, Step.ordinal == Instance.current_step_ordinal))
        .join(Route, Route.id == Instance.route_id)
        .where(Instance.status == "pending", Step.sla_hours.is_not(None))
    )

    for instance, step, route in result.all():
        try:
            prior = await _prior_step_decisions(session, instance)
            baseline = sla_engine.current_step_baseline(instance.started_at, prior)
            status = sla_engine.breach_status(baseline, step.sla_hours, now)
            if not status.is_breached:
                continue
            if not await _already_notified(session, instance.id, instance.current_step_ordinal, now):
                await _raise_breach(session, instance, step, route, status, now, delegations)
                actioned += 1
            # Escalation depth: once the breach has sat past its grace window,
            # walk the approval chain to the next authority (once per target).
            await _maybe_escalate(session, instance, route, now)
        except Exception:
            logger.exception("SLA check failed for approval instance %s", getattr(instance, "id", "?"))

    return actioned


async def _run_once() -> int:
    """Open a session, run one breach sweep, commit. Returns breaches actioned."""
    async with async_session_factory() as session:
        actioned = await check_sla_breaches(session)
        await session.commit()
    return actioned


async def _sla_checker_loop() -> None:
    """Forever-loop: sweep every :data:`POLL_INTERVAL_SECONDS`. Never raises out."""
    while True:
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        try:
            count = await _run_once()
            if count:
                logger.info("approval SLA monitor raised %d breach reminder(s)", count)
        except Exception:
            logger.exception("approval SLA monitor tick failed")


def start_sla_checker() -> asyncio.Task[None]:
    """Spawn the background SLA sweep as an asyncio task (wired from main.py)."""
    return asyncio.create_task(_sla_checker_loop())
