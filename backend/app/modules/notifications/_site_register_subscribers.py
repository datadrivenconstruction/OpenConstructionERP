# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Site register notifications: variation requests and change orders.

A register nobody is told about is a register nobody answers. Before this
bundle a variation request could be submitted, approved and rejected, and a
change order submitted, approved and rejected, without a single person being
told: the events either had no subscriber that notified anyone, or were never
published at all.

Who is told, and only from what the record itself names:

* variation request submitted -> whoever holds the ball (``ball_in_court``),
  and when the record names nobody, the project's managers, which is the rule
  the deadline sweep already applies to the same record once it is overdue;
* variation request approved / rejected -> its originator (``requested_by``);
* change order submitted, or handed to the next approver of its chain -> the
  approver of the current step, else ``ball_in_court``, else the managers;
* change order approved / rejected -> whoever submitted it (``submitted_by``).

Nobody is told about their own action, and one person holding two roles is
told once (:func:`pick_recipients`).

These handlers differ from the older ones in ``events.py`` in two ways, both
on purpose.

They run after the commit. The three events they subscribe to are published
with ``publish_after_commit``, and each handler re-reads the record and
requires the status the event announces. A handler that somehow ran early
would find the old status and send nothing, rather than announce a decision
that then rolled back.

They honour preferences. Delivery goes through
``NotificationService.enqueue_or_dispatch`` for the in-app row and for the
e-mail, so a mute or a digest cadence on the event type applies to both.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import Event, event_bus
from app.database import async_session_factory
from app.modules.notifications.models import Notification
from app.modules.notifications.service import NotificationService

logger = logging.getLogger(__name__)

# Events published after commit by the owning modules' services.
VARIATION_REQUEST_EVENT = "variations.notify.request"
CHANGE_ORDER_AWAITING_EVENT = "changeorders.notify.awaiting_approval"
CHANGE_ORDER_DECIDED_EVENT = "changeorders.notify.decided"

VARIATION_ENTITY = "variation_request"
CHANGE_ORDER_ENTITY = "change_order"

AWAITING_APPROVAL_TYPE = "changeorder_awaiting_approval"

_VARIATION_STATUSES = frozenset({"submitted", "approved", "rejected"})
_CHANGE_ORDER_DECISIONS = frozenset({"approved", "rejected"})

# A reason is quoted in a bell row and a subject-sized e-mail, not archived.
_REASON_LIMIT = 300


def _as_uuid(value: object) -> uuid.UUID | None:
    """A user id, or None for anything that is not one.

    ``ball_in_court`` columns are free text in places and may hold a role
    label such as "Engineer"; only a real id is a person who can be told.
    """
    if value is None:
        return None
    try:
        return uuid.UUID(str(value))
    except (AttributeError, TypeError, ValueError):
        return None


def pick_recipients(candidates: Iterable[object], *, actor: object = None) -> list[uuid.UUID]:
    """The people to tell: each once, in order, never the person who acted.

    Args:
        candidates: User ids as the record holds them (UUID, string, None, or
            free text that names no user).
        actor: Whoever performed the action being announced.

    Returns:
        Distinct user ids in first-seen order, without ``actor``.
    """
    acting = _as_uuid(actor)
    picked: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()
    for candidate in candidates:
        uid = _as_uuid(candidate)
        if uid is None or uid == acting or uid in seen:
            continue
        seen.add(uid)
        picked.append(uid)
    return picked


async def _existing(session: AsyncSession, user_ids: list[uuid.UUID]) -> list[uuid.UUID]:
    """The ids that name an active account, in order."""
    from app.modules.deadlines.sweeper import _active_users  # noqa: PLC0415

    return await _active_users(session, user_ids)


async def _holder_or_managers(
    session: AsyncSession,
    holders: Iterable[object],
    project_id: uuid.UUID,
    *,
    actor: object,
) -> list[uuid.UUID]:
    """The named holder of the next action, else the project's managers.

    The managers are asked only when the record names no active user at all.
    A record whose holder is the person who just acted tells nobody: it does
    not fall through to the managers, because the record did name someone.
    """
    named = await _existing(session, pick_recipients(holders))
    if named:
        return pick_recipients(named, actor=actor)
    from app.modules.deadlines.sweeper import _project_manager_ids  # noqa: PLC0415

    return pick_recipients(await _project_manager_ids(session, project_id), actor=actor)


async def _project_name(session: AsyncSession, project_id: uuid.UUID) -> str:
    from app.modules.projects.models import Project  # noqa: PLC0415

    name = (await session.execute(select(Project.name).where(Project.id == project_id))).scalar_one_or_none()
    return name or ""


async def _deliver(
    session: AsyncSession,
    *,
    event_type: str,
    notification_type: str,
    user_ids: list[uuid.UUID],
    title_key: str,
    body_key: str,
    context: dict[str, Any],
    entity_type: str,
    entity_id: str,
    action_url: str,
    metadata: dict[str, Any] | None,
    outbox: list[tuple[str, dict[str, Any]]],
) -> None:
    """Write the in-app row and queue the e-mail for each recipient.

    Both channels pass through the recipient's preferences. Realtime e-mails
    land in ``outbox`` and are published by the caller once this session has
    committed, so no mail goes out for a row that was not written.
    """
    svc = NotificationService(session)
    payload = {
        "title_key": title_key,
        "body_key": body_key,
        "body_context": context,
        "action_url": action_url,
        "entity_type": entity_type,
        "entity_id": entity_id,
    }
    inapp_payload = {**payload, "notification_type": notification_type, "metadata": metadata or {}}
    for user_id in user_ids:
        await svc.enqueue_or_dispatch(event_type, user_id, inapp_payload, channel="inapp")
        await svc.enqueue_or_dispatch(event_type, user_id, payload, channel="email", deferred=outbox)


def _flush_outbox(outbox: list[tuple[str, dict[str, Any]]]) -> None:
    for name, data in outbox:
        event_bus.publish_detached(name, data, source_module="oe_notifications")


# ── Variation requests ────────────────────────────────────────────────────


async def _on_variation_request_notice(event: Event) -> None:
    """``variations.notify.request`` -> holder on submit, originator on a decision."""
    data = event.data or {}
    request_id = _as_uuid(data.get("request_id"))
    to_status = str(data.get("to_status") or "")
    actor = data.get("actor_id")
    if request_id is None or to_status not in _VARIATION_STATUSES:
        return
    outbox: list[tuple[str, dict[str, Any]]] = []
    try:
        from app.modules.variations.models import VariationRequest  # noqa: PLC0415

        async with async_session_factory() as session:
            vr = await session.get(VariationRequest, request_id)
            # The status is the proof the transition is durable: read before
            # the publisher's commit, the row still carries the old one.
            if vr is None or vr.status != to_status:
                return
            if to_status == "submitted":
                recipients = await _holder_or_managers(session, [vr.ball_in_court], vr.project_id, actor=actor)
            else:
                recipients = await _existing(session, pick_recipients([vr.requested_by], actor=actor))
            if not recipients:
                return
            context: dict[str, Any] = {
                "code": vr.code,
                "title": vr.title or vr.code,
                "project": await _project_name(session, vr.project_id),
            }
            body_key = f"notifications.variation.{to_status}.body"
            reason = (vr.decision_notes or "").strip()
            if to_status == "rejected" and reason:
                context["reason"] = reason[:_REASON_LIMIT]
                body_key = "notifications.variation.rejected_reason.body"
            await _deliver(
                session,
                event_type=f"variations.notify.{to_status}",
                notification_type=f"variation_{to_status}",
                user_ids=recipients,
                title_key=f"notifications.variation.{to_status}.title",
                body_key=body_key,
                context=context,
                entity_type=VARIATION_ENTITY,
                entity_id=str(request_id),
                action_url="/variations",
                metadata={"status": to_status},
                outbox=outbox,
            )
            await session.commit()
    except Exception:
        logger.warning("notifications: _on_variation_request_notice failed", exc_info=True)
        return
    _flush_outbox(outbox)


# ── Change orders ─────────────────────────────────────────────────────────


async def _current_approver(session: AsyncSession, order: Any) -> uuid.UUID | None:
    """The approver of the chain step the order is waiting on, if it has one."""
    step = getattr(order, "current_approval_step", None)
    if not step:
        return None
    from app.modules.changeorders.models import ChangeOrderApproval  # noqa: PLC0415

    return (
        await session.execute(
            select(ChangeOrderApproval.approver_user_id).where(
                ChangeOrderApproval.change_order_id == order.id,
                ChangeOrderApproval.step_order == step,
                ChangeOrderApproval.decision == "pending",
            )
        )
    ).scalar_one_or_none()


def already_asked(previous: Iterable[dict[str, Any]], *, submitted_at: object, step: int) -> bool:
    """Whether a person was already asked to approve this submission at this step.

    ``previous`` is the metadata of the awaiting-approval rows that person
    holds for the order. A row from an earlier submission (the order was
    rejected, reworked and submitted again) does not count. Within one
    submission, step 0 is "submitted, no chain yet" and step 1 the first
    chain step: a manager told at step 0 and then named first approver is the
    same person being asked for the same decision, so those two count as one.
    """
    for meta in previous:
        if meta.get("submitted_at") != submitted_at:
            continue
        earlier = int(meta.get("step", 0) or 0)
        if earlier == step or {earlier, step} == {0, 1}:
            return True
    return False


async def _not_yet_asked(
    session: AsyncSession,
    order_id: uuid.UUID,
    user_ids: list[uuid.UUID],
    *,
    submitted_at: object,
    step: int,
) -> list[uuid.UUID]:
    if not user_ids:
        return []
    rows = (
        await session.execute(
            select(Notification.user_id, Notification.metadata_).where(
                Notification.entity_type == CHANGE_ORDER_ENTITY,
                Notification.entity_id == str(order_id),
                Notification.notification_type == AWAITING_APPROVAL_TYPE,
                Notification.user_id.in_(user_ids),
            )
        )
    ).all()
    held: dict[uuid.UUID, list[dict[str, Any]]] = {}
    for user_id, meta in rows:
        held.setdefault(user_id, []).append(meta or {})
    return [u for u in user_ids if not already_asked(held.get(u, []), submitted_at=submitted_at, step=step)]


async def _on_change_order_awaiting_approval(event: Event) -> None:
    """``changeorders.notify.awaiting_approval`` -> whoever has to approve next."""
    data = event.data or {}
    order_id = _as_uuid(data.get("change_order_id"))
    actor = data.get("actor_id")
    if order_id is None:
        return
    outbox: list[tuple[str, dict[str, Any]]] = []
    try:
        from app.modules.changeorders.models import ChangeOrder  # noqa: PLC0415

        async with async_session_factory() as session:
            order = await session.get(ChangeOrder, order_id)
            if order is None or order.status != "submitted":
                return
            step = int(order.current_approval_step or 0)
            approver = await _current_approver(session, order)
            holders = [approver] if approver is not None else [order.ball_in_court]
            recipients = await _holder_or_managers(session, holders, order.project_id, actor=actor)
            recipients = await _not_yet_asked(session, order_id, recipients, submitted_at=order.submitted_at, step=step)
            if not recipients:
                return
            await _deliver(
                session,
                event_type="changeorders.notify.awaiting_approval",
                notification_type=AWAITING_APPROVAL_TYPE,
                user_ids=recipients,
                title_key="notifications.changeorder.awaiting_approval.title",
                body_key="notifications.changeorder.awaiting_approval.body",
                context={
                    "code": order.code,
                    "title": order.title,
                    "project": await _project_name(session, order.project_id),
                },
                entity_type=CHANGE_ORDER_ENTITY,
                entity_id=str(order_id),
                action_url="/changeorders",
                metadata={"submitted_at": order.submitted_at, "step": step},
                outbox=outbox,
            )
            await session.commit()
    except Exception:
        logger.warning("notifications: _on_change_order_awaiting_approval failed", exc_info=True)
        return
    _flush_outbox(outbox)


async def _on_change_order_decided(event: Event) -> None:
    """``changeorders.notify.decided`` -> whoever submitted the order."""
    data = event.data or {}
    order_id = _as_uuid(data.get("change_order_id"))
    decision = str(data.get("decision") or "")
    actor = data.get("actor_id")
    if order_id is None or decision not in _CHANGE_ORDER_DECISIONS:
        return
    outbox: list[tuple[str, dict[str, Any]]] = []
    try:
        from app.modules.changeorders.models import ChangeOrder  # noqa: PLC0415

        async with async_session_factory() as session:
            order = await session.get(ChangeOrder, order_id)
            if order is None or order.status != decision:
                return
            recipients = await _existing(session, pick_recipients([order.submitted_by], actor=actor))
            if not recipients:
                return
            await _deliver(
                session,
                event_type=f"changeorders.notify.{decision}",
                notification_type=f"changeorder_{decision}",
                user_ids=recipients,
                title_key=f"notifications.changeorder.{decision}.title",
                body_key=f"notifications.changeorder.{decision}.body",
                context={
                    "code": order.code,
                    "title": order.title,
                    "project": await _project_name(session, order.project_id),
                },
                entity_type=CHANGE_ORDER_ENTITY,
                entity_id=str(order_id),
                action_url="/changeorders",
                metadata={"status": decision},
                outbox=outbox,
            )
            await session.commit()
    except Exception:
        logger.warning("notifications: _on_change_order_decided failed", exc_info=True)
        return
    _flush_outbox(outbox)


_SITE_REGISTER_SUBSCRIPTIONS = [
    (VARIATION_REQUEST_EVENT, _on_variation_request_notice),
    (CHANGE_ORDER_AWAITING_EVENT, _on_change_order_awaiting_approval),
    (CHANGE_ORDER_DECIDED_EVENT, _on_change_order_decided),
]


def register_site_register_notification_subscribers() -> None:
    """Wire the variation and change order notifications onto the event bus."""
    for event_name, handler in _SITE_REGISTER_SUBSCRIPTIONS:
        event_bus.subscribe_once(event_name, handler)
    logger.info(
        "Notifications: subscribed to %d site register event(s)",
        len(_SITE_REGISTER_SUBSCRIPTIONS),
    )


__all__ = [
    "CHANGE_ORDER_AWAITING_EVENT",
    "CHANGE_ORDER_DECIDED_EVENT",
    "VARIATION_REQUEST_EVENT",
    "already_asked",
    "pick_recipients",
    "register_site_register_notification_subscribers",
]
