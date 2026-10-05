# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Wave 2 + Wave 3 notification subscribers.

Wires the highest-signal events from Wave 2 (contracts, crm, resources, carbon)
and Wave 3 (property_dev, bid_management, variations, schedule_advanced,
hse_advanced, daily_diary) into the in-app notification feed.

Same conventions as ``_wave1_subscribers.py``:
    1. Skip silently on SQLite (single-writer; foreground commit already shipped
       the work).
    2. Open a short-lived isolated session so a failure here can't roll back
       the upstream service.
    3. Catch all exceptions at debug.

We don't fan out to every event - only ones a human is plausibly waiting on.
Pure status-change events (e.g. ``crm.opportunity.stage_changed``) stay
unsubscribed; analytics modules can listen separately.
"""

from __future__ import annotations

import logging
from typing import Callable

from app.core.events import Event, event_bus
from app.database import async_session_factory
from app.modules.notifications.service import NotificationService

logger = logging.getLogger(__name__)


async def _can_open_isolated_session() -> bool:
    """Always True post-Epic-B - see :mod:`app.modules.notifications.events`."""
    return True


async def _notify(
    user_id: str,
    notification_type: str,
    title_key: str,
    body_key: str,
    body_context: dict[str, str],
    entity_type: str,
    entity_id: str,
    action_url: str,
) -> None:
    """One-shot in-app notification create; safe to call from any handler."""
    try:
        async with async_session_factory() as session:
            svc = NotificationService(session)
            await svc.create(
                user_id=user_id,
                notification_type=notification_type,
                title_key=title_key,
                body_key=body_key,
                body_context=body_context,
                entity_type=entity_type,
                entity_id=entity_id,
                action_url=action_url,
            )
            await session.commit()
    except Exception:
        logger.debug("notifications: _notify (%s) failed", title_key, exc_info=True)


# ── Contracts ─────────────────────────────────────────────────────────


async def _on_contract_signed(event: Event) -> None:
    """``contracts.contract.signed`` → contract owner."""
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    target = data.get("owner_user_id") or data.get("actor_id")
    contract_id = data.get("contract_id")
    if not target or not contract_id:
        return
    await _notify(
        user_id=str(target),
        notification_type="info",
        title_key="notifications.contracts.signed.title",
        body_key="notifications.contracts.signed.body",
        body_context={
            "code": str(data.get("code") or ""),
            "value": str(data.get("contract_value") or ""),
            "currency": str(data.get("currency") or ""),
        },
        entity_type="contract",
        entity_id=str(contract_id),
        action_url=f"/contracts?highlight={contract_id}",
    )


async def _on_claim_submitted(event: Event) -> None:
    """``contracts.claim.submitted`` → contract reviewer / owner."""
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    target = data.get("reviewer_user_id") or data.get("owner_user_id")
    claim_id = data.get("claim_id")
    if not target or not claim_id:
        return
    await _notify(
        user_id=str(target),
        notification_type="action_required",
        title_key="notifications.contracts.claim_submitted.title",
        body_key="notifications.contracts.claim_submitted.body",
        body_context={"amount": str(data.get("amount") or ""), "currency": str(data.get("currency") or "")},
        entity_type="contract_claim",
        entity_id=str(claim_id),
        action_url="/contracts?tab=claims",
    )


async def _on_claim_paid(event: Event) -> None:
    """``contracts.claim.paid`` → claim submitter."""
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    target = data.get("submitted_by") or data.get("actor_id")
    claim_id = data.get("claim_id")
    if not target or not claim_id:
        return
    await _notify(
        user_id=str(target),
        notification_type="success",
        title_key="notifications.contracts.claim_paid.title",
        body_key="notifications.contracts.claim_paid.body",
        body_context={"amount": str(data.get("amount") or ""), "currency": str(data.get("currency") or "")},
        entity_type="contract_claim",
        entity_id=str(claim_id),
        action_url="/contracts?tab=claims",
    )


# ── CRM ───────────────────────────────────────────────────────────────


async def _on_lead_qualified(event: Event) -> None:
    """``crm.lead.qualified`` → assigned sales user."""
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    target = data.get("owner_user_id") or data.get("actor_id")
    lead_id = data.get("lead_id")
    if not target or not lead_id:
        return
    await _notify(
        user_id=str(target),
        notification_type="info",
        title_key="notifications.crm.lead_qualified.title",
        body_key="notifications.crm.lead_qualified.body",
        body_context={"name": str(data.get("name") or "")},
        entity_type="crm_lead",
        entity_id=str(lead_id),
        action_url="/crm",
    )


async def _on_opportunity_won(event: Event) -> None:
    """``crm.opportunity.won`` → owner."""
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    target = data.get("owner_user_id") or data.get("actor_id")
    opp_id = data.get("opportunity_id")
    if not target or not opp_id:
        return
    await _notify(
        user_id=str(target),
        notification_type="success",
        title_key="notifications.crm.opportunity_won.title",
        body_key="notifications.crm.opportunity_won.body",
        body_context={"name": str(data.get("name") or ""), "value": str(data.get("value") or "")},
        entity_type="crm_opportunity",
        entity_id=str(opp_id),
        action_url="/crm",
    )


# ── Resources ─────────────────────────────────────────────────────────


async def _on_assignment_proposed(event: Event) -> None:
    """``resources.assignment.proposed`` → proposed-to user (resource owner)."""
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    target = data.get("assignee_user_id") or data.get("resource_owner_id")
    aid = data.get("assignment_id")
    if not target or not aid:
        return
    await _notify(
        user_id=str(target),
        notification_type="action_required",
        title_key="notifications.resources.assignment_proposed.title",
        body_key="notifications.resources.assignment_proposed.body",
        body_context={
            "task": str(data.get("task_ref") or ""),
            "start": str(data.get("start_date") or ""),
        },
        entity_type="resource_assignment",
        entity_id=str(aid),
        action_url=(f"/resources?resourceId={data['resource_id']}" if data.get("resource_id") else "/resources"),
    )


async def _on_assignment_confirmed(event: Event) -> None:
    """``resources.assignment.confirmed`` → planner who proposed it."""
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    target = data.get("planner_user_id") or data.get("actor_id")
    aid = data.get("assignment_id")
    if not target or not aid:
        return
    await _notify(
        user_id=str(target),
        notification_type="success",
        title_key="notifications.resources.assignment_confirmed.title",
        body_key="notifications.resources.assignment_confirmed.body",
        body_context={"task": str(data.get("task_ref") or "")},
        entity_type="resource_assignment",
        entity_id=str(aid),
        action_url=(f"/resources?resourceId={data['resource_id']}" if data.get("resource_id") else "/resources"),
    )


# ── Property Development ──────────────────────────────────────────────


async def _on_buyer_contracted(event: Event) -> None:
    """``property_dev.buyer.contracted`` → sales owner."""
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    target = data.get("sales_owner_id") or data.get("actor_id")
    buyer_id = data.get("buyer_id")
    if not target or not buyer_id:
        return
    await _notify(
        user_id=str(target),
        notification_type="success",
        title_key="notifications.property_dev.buyer_contracted.title",
        body_key="notifications.property_dev.buyer_contracted.body",
        body_context={
            "buyer": str(data.get("buyer_name") or ""),
            "plot": str(data.get("plot_code") or ""),
        },
        entity_type="buyer",
        entity_id=str(buyer_id),
        action_url=f"/property-dev?buyerId={buyer_id}",
    )


async def _on_handover_completed(event: Event) -> None:
    """``property_dev.handover.completed`` → buyer + sales owner."""
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    handover_id = data.get("handover_id")
    if not handover_id:
        return
    for key in ("buyer_user_id", "sales_owner_id", "actor_id"):
        target = data.get(key)
        if not target:
            continue
        await _notify(
            user_id=str(target),
            notification_type="success",
            title_key="notifications.property_dev.handover_completed.title",
            body_key="notifications.property_dev.handover_completed.body",
            body_context={"plot": str(data.get("plot_code") or "")},
            entity_type="handover",
            entity_id=str(handover_id),
            action_url="/property-dev?tab=handovers",
        )


async def _on_warranty_raised(event: Event) -> None:
    """``property_dev.warranty.raised`` → service team / aftercare owner."""
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    target = data.get("aftercare_owner_id") or data.get("service_lead_id")
    claim_id = data.get("warranty_claim_id")
    if not target or not claim_id:
        return
    await _notify(
        user_id=str(target),
        notification_type="action_required",
        title_key="notifications.property_dev.warranty_raised.title",
        body_key="notifications.property_dev.warranty_raised.body",
        body_context={
            "category": str(data.get("category") or ""),
            "plot": str(data.get("plot_code") or ""),
        },
        entity_type="warranty_claim",
        entity_id=str(claim_id),
        action_url="/property-dev?tab=warranty",
    )


# ── Bid Management ────────────────────────────────────────────────────


async def _on_invitation_sent(event: Event) -> None:
    """``bid_management.invitation.sent`` → invited bidder (if known user)."""
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    target = data.get("bidder_user_id")
    invitation_id = data.get("invitation_id")
    if not target or not invitation_id:
        return
    await _notify(
        user_id=str(target),
        notification_type="action_required",
        title_key="notifications.bid_management.invitation_sent.title",
        body_key="notifications.bid_management.invitation_sent.body",
        body_context={
            "package": str(data.get("package_name") or ""),
            "due": str(data.get("submission_due") or ""),
        },
        entity_type="bid_invitation",
        entity_id=str(invitation_id),
        action_url=(f"/bid-management?highlight={data['package_id']}" if data.get("package_id") else "/bid-management"),
    )


async def _on_bid_awarded(event: Event) -> None:
    """``bid_management.package.awarded`` → buyer + whoever made the award.

    The winning bidder is NOT reached here, and ``winner_user_id`` below will
    never be present. A ``Bidder`` row is a snapshot of an external company -
    company name, contact name, contact email, contact phone - and carries no
    user id anywhere in the schema, so there is no value the publisher could
    put under that key. This handler was written against a data model that does
    not exist, which is a different defect from a payload missing a key, and it
    is not closed by publishing more keys.

    Reaching the winner means matching ``Bidder.contact_email`` to a
    ``portal.PortalUser`` and notifying through that module's own
    ``PortalNotification`` table, which joins two identity spaces on an email
    string. That is a decision about who our users are and is open, so the key
    is left in the loop rather than deleted: it names the recipient this
    handler is meant to reach, and removing it would erase the requirement
    along with the gap.
    """
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    pkg_id = data.get("package_id")
    if not pkg_id:
        return
    for key in ("winner_user_id", "buyer_user_id", "actor_id"):
        target = data.get(key)
        if not target:
            continue
        await _notify(
            user_id=str(target),
            notification_type="success",
            title_key="notifications.bid_management.awarded.title",
            body_key="notifications.bid_management.awarded.body",
            body_context={
                # ``awarded_amount`` is the published name. This read
                # ``award_amount`` and rendered an empty amount into the body of
                # every award notification. The reader moves, not the payload:
                # the key is on the wire and other subscribers already use it.
                "package": str(data.get("package_name") or ""),
                "amount": str(data.get("awarded_amount") or ""),
            },
            entity_type="bid_package",
            entity_id=str(pkg_id),
            action_url=(
                f"/projects/{data['project_id']}/bid-management?highlight={pkg_id}"
                if data.get("project_id")
                else f"/bid-management?highlight={pkg_id}"
            ),
        )


# ── Schedule Advanced ─────────────────────────────────────────────────


async def _on_constraint_cleared(event: Event) -> None:
    """``schedule_advanced.constraint.cleared`` → commitment owner."""
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    target = data.get("commitment_owner_id") or data.get("actor_id")
    constraint_id = data.get("constraint_id")
    if not target or not constraint_id:
        return
    await _notify(
        user_id=str(target),
        notification_type="info",
        title_key="notifications.schedule_advanced.constraint_cleared.title",
        body_key="notifications.schedule_advanced.constraint_cleared.body",
        body_context={"task": str(data.get("task_ref") or "")},
        entity_type="schedule_constraint",
        entity_id=str(constraint_id),
        action_url="/schedule-advanced",
    )


# ── Daily Diary ───────────────────────────────────────────────────────


async def _on_diary_signed(event: Event) -> None:
    """``daily_diary.signed`` → project owner / client rep."""
    if not await _can_open_isolated_session():
        return
    data = event.data or {}
    target = data.get("client_rep_user_id") or data.get("project_owner_id")
    diary_id = data.get("diary_id")
    if not target or not diary_id:
        return
    await _notify(
        user_id=str(target),
        notification_type="info",
        title_key="notifications.daily_diary.signed.title",
        body_key="notifications.daily_diary.signed.body",
        body_context={"date": str(data.get("diary_date") or "")},
        entity_type="daily_diary",
        entity_id=str(diary_id),
        action_url=(f"/projects/{data['project_id']}/daily-diary" if data.get("project_id") else "/daily-diary"),
    )


# ── Wave 2 + Wave 3 subscription list ─────────────────────────────────

_WAVE23_SUBSCRIPTIONS: list[tuple[str, Callable[[Event], object]]] = [
    ("contracts.contract.signed", _on_contract_signed),
    ("contracts.claim.submitted", _on_claim_submitted),
    ("contracts.claim.paid", _on_claim_paid),
    ("crm.lead.qualified", _on_lead_qualified),
    ("crm.opportunity.won", _on_opportunity_won),
    ("resources.assignment.proposed", _on_assignment_proposed),
    ("resources.assignment.confirmed", _on_assignment_confirmed),
    ("property_dev.buyer.contracted", _on_buyer_contracted),
    ("property_dev.handover.completed", _on_handover_completed),
    ("property_dev.warranty.raised", _on_warranty_raised),
    ("bid_management.invitation.sent", _on_invitation_sent),
    ("bid_management.package.awarded", _on_bid_awarded),
    ("schedule_advanced.constraint.cleared", _on_constraint_cleared),
    ("daily_diary.signed", _on_diary_signed),
]


def register_wave23_notification_subscribers() -> None:
    """Wire Wave 2 + Wave 3 high-value events onto the global event bus."""
    for event_name, handler in _WAVE23_SUBSCRIPTIONS:
        event_bus.subscribe_once(event_name, handler)
    logger.info(
        "Notifications: subscribed to %d Wave 2/3 event(s)",
        len(_WAVE23_SUBSCRIPTIONS),
    )


__all__ = ["register_wave23_notification_subscribers"]
