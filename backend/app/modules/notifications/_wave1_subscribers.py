"""‌⁠‍Notification subscribers for the 18-modules Wave 1 events.

Wires events emitted by the Wave 1 backend modules (service, subcontractors,
equipment, portal) into ``NotificationService.create()`` so users get visible
feedback in the in-app notification feed.

Each handler:
    1. Pulls the actor / target user-id out of ``event.data``.
    2. Skips silently if the payload is missing the required hint.
    3. Opens its own short-lived session via ``async_session_factory()`` so a
       notification failure cannot roll back the upstream service.
    4. Catches all exceptions and logs at debug.

The registration function ``register_wave1_notification_subscribers()`` is
imported and called from ``notifications/events.py``'s startup hook.
"""

from __future__ import annotations

import logging
from typing import Callable

from app.core.events import Event, event_bus
from app.database import async_session_factory
from app.modules.notifications.service import NotificationService


async def _can_open_isolated_session() -> bool:
    """‌⁠‍Always True post-Epic-B — see :mod:`app.modules.notifications.events`."""
    return True


logger = logging.getLogger(__name__)


# ── Service & Maintenance subscribers ─────────────────────────────────────


async def _on_service_ticket_dispatched(event: Event) -> None:
    """‌⁠‍``service.ticket.dispatched`` → notify the technician."""
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    technician_id = data.get("technician_id") or data.get("assigned_to")
    ticket_id = data.get("ticket_id") or data.get("id")
    if not technician_id or not ticket_id:
        return
    try:
        async with async_session_factory() as session:
            svc = NotificationService(session)
            await svc.create(
                user_id=str(technician_id),
                notification_type="task_assigned",
                title_key="notifications.service.ticket_dispatched.title",
                body_key="notifications.service.ticket_dispatched.body",
                body_context={
                    "ticket_number": str(data.get("ticket_number") or ""),
                    "priority": str(data.get("priority") or ""),
                },
                entity_type="service_ticket",
                entity_id=str(ticket_id),
                action_url=f"/service/tickets/{ticket_id}",
            )
            await session.commit()
    except Exception:
        logger.debug("notifications: _on_service_ticket_dispatched failed", exc_info=True)


async def _on_service_ticket_resolved(event: Event) -> None:
    """``service.ticket.resolved`` → echo to the original reporter."""
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    reporter_id = data.get("reported_by") or data.get("created_by")
    ticket_id = data.get("ticket_id") or data.get("id")
    if not reporter_id or not ticket_id:
        return
    try:
        async with async_session_factory() as session:
            svc = NotificationService(session)
            await svc.create(
                user_id=str(reporter_id),
                notification_type="info",
                title_key="notifications.service.ticket_resolved.title",
                body_key="notifications.service.ticket_resolved.body",
                body_context={"ticket_number": str(data.get("ticket_number") or "")},
                entity_type="service_ticket",
                entity_id=str(ticket_id),
                action_url=f"/service/tickets/{ticket_id}",
            )
            await session.commit()
    except Exception:
        logger.debug("notifications: _on_service_ticket_resolved failed", exc_info=True)


async def _on_service_work_order_billed(event: Event) -> None:
    """``service.work_order.billed`` → notify the dispatcher / finance role."""
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    dispatcher_id = data.get("dispatcher_id") or data.get("created_by")
    wo_id = data.get("work_order_id") or data.get("id")
    if not dispatcher_id or not wo_id:
        return
    try:
        async with async_session_factory() as session:
            svc = NotificationService(session)
            await svc.create(
                user_id=str(dispatcher_id),
                notification_type="info",
                title_key="notifications.service.work_order_billed.title",
                body_key="notifications.service.work_order_billed.body",
                body_context={
                    "wo_number": str(data.get("wo_number") or ""),
                    "amount": str(data.get("amount") or ""),
                    "currency": str(data.get("currency") or ""),
                },
                entity_type="service_work_order",
                entity_id=str(wo_id),
                action_url=f"/service/work-orders/{wo_id}",
            )
            await session.commit()
    except Exception:
        logger.debug("notifications: _on_service_work_order_billed failed", exc_info=True)


# ── Subcontractor Management subscribers ──────────────────────────────────


async def _on_subcontractor_prequalification_submitted(event: Event) -> None:
    """``subcontractors.prequalification.submitted`` → notify reviewer."""
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    reviewer_id = data.get("reviewer_id") or data.get("assigned_to")
    application_id = data.get("application_id") or data.get("id")
    if not reviewer_id or not application_id:
        return
    try:
        async with async_session_factory() as session:
            svc = NotificationService(session)
            await svc.create(
                user_id=str(reviewer_id),
                notification_type="task_assigned",
                title_key="notifications.subcontractors.prequal_submitted.title",
                body_key="notifications.subcontractors.prequal_submitted.body",
                body_context={"subcontractor_name": str(data.get("subcontractor_name") or "")},
                entity_type="prequalification",
                entity_id=str(application_id),
                action_url=f"/subcontractors/prequalifications/{application_id}",
            )
            await session.commit()
    except Exception:
        logger.debug(
            "notifications: _on_subcontractor_prequalification_submitted failed",
            exc_info=True,
        )


async def _on_subcontractor_payment_app_submitted(event: Event) -> None:
    """``subcontractors.payment_application.submitted`` → notify approver(s)."""
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    approver_id = data.get("foreman_id") or data.get("assigned_to")
    pa_id = data.get("payment_application_id") or data.get("id")
    if not approver_id or not pa_id:
        return
    try:
        async with async_session_factory() as session:
            svc = NotificationService(session)
            await svc.create(
                user_id=str(approver_id),
                notification_type="approval_needed",
                title_key="notifications.subcontractors.payment_app_submitted.title",
                body_key="notifications.subcontractors.payment_app_submitted.body",
                body_context={
                    "application_number": str(data.get("application_number") or ""),
                    "net_amount": str(data.get("net_amount") or ""),
                    "currency": str(data.get("currency") or ""),
                },
                entity_type="payment_application",
                entity_id=str(pa_id),
                action_url=f"/subcontractors/payment-applications/{pa_id}",
            )
            await session.commit()
    except Exception:
        logger.debug(
            "notifications: _on_subcontractor_payment_app_submitted failed",
            exc_info=True,
        )


async def _on_subcontractor_retention_released(event: Event) -> None:
    """``subcontractors.retention.released`` → echo to subcontractor's contact."""
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    user_id = data.get("notified_user_id") or data.get("created_by")
    release_id = data.get("retention_release_id") or data.get("id")
    if not user_id or not release_id:
        return
    try:
        async with async_session_factory() as session:
            svc = NotificationService(session)
            await svc.create(
                user_id=str(user_id),
                notification_type="info",
                title_key="notifications.subcontractors.retention_released.title",
                body_key="notifications.subcontractors.retention_released.body",
                body_context={
                    "amount": str(data.get("released_amount") or ""),
                    "currency": str(data.get("currency") or ""),
                },
                entity_type="retention_release",
                entity_id=str(release_id),
                action_url=f"/subcontractors/retention/{release_id}",
            )
            await session.commit()
    except Exception:
        logger.debug(
            "notifications: _on_subcontractor_retention_released failed",
            exc_info=True,
        )


# ── Equipment & Fleet subscribers ─────────────────────────────────────────


async def _on_equipment_assigned(event: Event) -> None:
    """``equipment.assigned`` → notify the project owner / requester."""
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    user_id = data.get("notified_user_id") or data.get("requested_by")
    equipment_id = data.get("equipment_id") or data.get("id")
    if not user_id or not equipment_id:
        return
    try:
        async with async_session_factory() as session:
            svc = NotificationService(session)
            await svc.create(
                user_id=str(user_id),
                notification_type="info",
                title_key="notifications.equipment.assigned.title",
                body_key="notifications.equipment.assigned.body",
                body_context={
                    "equipment_code": str(data.get("equipment_code") or ""),
                    "project_name": str(data.get("project_name") or ""),
                },
                entity_type="equipment",
                entity_id=str(equipment_id),
                action_url=f"/equipment/{equipment_id}",
            )
            await session.commit()
    except Exception:
        logger.debug("notifications: _on_equipment_assigned failed", exc_info=True)


async def _on_equipment_damage_reported(event: Event) -> None:
    """``equipment.damage_reported`` → notify fleet manager."""
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    manager_id = data.get("fleet_manager_id") or data.get("notified_user_id")
    damage_id = data.get("damage_report_id") or data.get("id")
    if not manager_id or not damage_id:
        return
    try:
        async with async_session_factory() as session:
            svc = NotificationService(session)
            await svc.create(
                user_id=str(manager_id),
                notification_type="alert",
                title_key="notifications.equipment.damage_reported.title",
                body_key="notifications.equipment.damage_reported.body",
                body_context={
                    "equipment_code": str(data.get("equipment_code") or ""),
                    "severity": str(data.get("severity") or ""),
                },
                entity_type="equipment_damage",
                entity_id=str(damage_id),
                action_url=f"/equipment/damage/{damage_id}",
            )
            await session.commit()
    except Exception:
        logger.debug("notifications: _on_equipment_damage_reported failed", exc_info=True)


# ── Portal subscribers ─────────────────────────────────────────────────────


async def _on_portal_user_invited(event: Event) -> None:
    """``portal.user.invited`` → echo to the internal user who issued the invite."""
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    inviter_id = data.get("granted_by") or data.get("invited_by")
    portal_user_id = data.get("portal_user_id") or data.get("id")
    if not inviter_id or not portal_user_id:
        return
    try:
        async with async_session_factory() as session:
            svc = NotificationService(session)
            await svc.create(
                user_id=str(inviter_id),
                notification_type="info",
                title_key="notifications.portal.user_invited.title",
                body_key="notifications.portal.user_invited.body",
                body_context={
                    "portal_user_email": str(data.get("email") or ""),
                    "portal_role": str(data.get("portal_role") or ""),
                },
                entity_type="portal_user",
                entity_id=str(portal_user_id),
                action_url=f"/admin/portal/users/{portal_user_id}",
            )
            await session.commit()
    except Exception:
        logger.debug("notifications: _on_portal_user_invited failed", exc_info=True)


# ── Registration ──────────────────────────────────────────────────────────


_WAVE1_SUBSCRIPTIONS: list[tuple[str, Callable[[Event], object]]] = [
    ("service.ticket.dispatched", _on_service_ticket_dispatched),
    ("service.ticket.resolved", _on_service_ticket_resolved),
    ("service.work_order.billed", _on_service_work_order_billed),
    ("subcontractors.prequalification.submitted", _on_subcontractor_prequalification_submitted),
    ("subcontractors.payment_application.submitted", _on_subcontractor_payment_app_submitted),
    ("subcontractors.retention.released", _on_subcontractor_retention_released),
    ("equipment.assigned", _on_equipment_assigned),
    ("equipment.damage_reported", _on_equipment_damage_reported),
    ("portal.user.invited", _on_portal_user_invited),
]


def register_wave1_notification_subscribers() -> None:
    """Wire Wave 1 module events into in-app notifications.

    Idempotent — event bus deduplicates handlers by identity.
    """
    for event_name, handler in _WAVE1_SUBSCRIPTIONS:
        event_bus.subscribe(event_name, handler)
    logger.info(
        "Notifications/Wave1: subscribed to %d cross-module event(s)",
        len(_WAVE1_SUBSCRIPTIONS),
    )
