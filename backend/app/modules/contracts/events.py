# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Contracts module domain events.

Most contract lifecycle events are published inline from the service via
``event_bus.publish_detached`` (signed / amended / claim.submitted / etc.).
This module centralises the event-name constants that the Gap I progress
bridge introduces so subscribers and tests reference one canonical string
instead of a magic literal.

Event reference
───────────────
``contracts.claim.populated``
    Emitted after a draft progress claim has its line breakdown
    rebuilt from the latest progress observations and committed
    (``commit_preview_to_claim``). Payload::

        {
            "claim_id": str,
            "contract_id": str,
            "claim_number": str,
            "line_count": int,        # number of claim lines written
            "gross": str,             # Decimal-as-string, claim currency
            "retention": str,
            "net_due": str,
            "currency": str,
            "actor": str | None,
        }

    Finance / dashboard subscribers use it to refresh a claim's billed-to-date
    once it has been auto-populated from the field, without re-querying the
    whole contract. The event is informational only: it does NOT post to the
    cost spine (the certified-claim → actual posting is owned by Gap B/E and
    fires on ``contracts.claim.certified``).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from app.core.events import Event, event_bus

#: Emitted when a claim's lines are (re)built from progress observations.
CLAIM_POPULATED = "contracts.claim.populated"

#: Emitted when an extension-of-time claim is submitted for review. Payload::
#:
#:     {
#:         "eot_id": str,
#:         "contract_id": str,
#:         "eot_number": str,
#:         "days_claimed": int,
#:         "actor": str | None,
#:     }
EOT_SUBMITTED = "contracts.eot.submitted"

#: Emitted when an extension-of-time claim is decided (granted /
#: partially_granted / rejected). Payload::
#:
#:     {
#:         "eot_id": str,
#:         "contract_id": str,
#:         "eot_number": str,
#:         "status": str,                  # the decision status
#:         "days_claimed": int,
#:         "days_granted": int,
#:         "revised_completion_date": str | None,
#:         "actor": str | None,
#:     }
#:
#: Scheduling / dashboards subscribe to refresh the contract completion date
#: when time is granted. Informational only; it posts nothing to the ledger.
EOT_DECIDED = "contracts.eot.decided"

#: The schedule reports a milestone activity reached, or taken back. Payload::
#:
#:     {
#:         "project_id": str,
#:         "schedule_id": str,
#:         "activity_id": str,
#:         "activity_name": str,
#:         "reached_at": str,              # ISO timestamp
#:         "actor_id": str | None,
#:     }
#:
#: Instalments of an active contract that follow the activity become reached
#: (and back to pending when reopened, unless a claim already bills them).
#: Nothing is claimed or invoiced from here.
SCHEDULE_MILESTONE_REACHED = "schedule.milestone.reached"
SCHEDULE_MILESTONE_REOPENED = "schedule.milestone.reopened"

#: Schedule events that move or remove the activities instalments follow.
#: ``schedule.cpm.calculated`` is left out on purpose: it writes float and
#: criticality, not dates.
SCHEDULE_RESCHEDULED = "schedule.rescheduled"
SCHEDULE_ACTIVITY_UPDATED = "schedule.activity.updated"
SCHEDULE_ACTIVITY_DELETED = "schedule.activity.deleted"
SCHEDULE_ACTIVITIES_CLEARED = "schedule.activities.cleared"

__all__ = [
    "CLAIM_POPULATED",
    "EOT_DECIDED",
    "EOT_SUBMITTED",
    "SCHEDULE_ACTIVITIES_CLEARED",
    "SCHEDULE_ACTIVITY_DELETED",
    "SCHEDULE_ACTIVITY_UPDATED",
    "SCHEDULE_MILESTONE_REACHED",
    "SCHEDULE_MILESTONE_REOPENED",
    "SCHEDULE_RESCHEDULED",
]

logger = logging.getLogger(__name__)


def _uuid_or_none(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value)) if value else None
    except (TypeError, ValueError):
        return None


async def _with_contracts_service(work: Callable[[Any], Awaitable[int]]) -> int:
    """Run ``work`` on a ContractsService in a session of its own, and commit.

    The event bus carries no session, and the publisher's may still be open.
    """
    from app.database import async_session_factory  # noqa: PLC0415
    from app.modules.contracts.service import ContractsService  # noqa: PLC0415

    async with async_session_factory() as session:
        try:
            result = await work(ContractsService(session))
            await session.commit()
            return result
        except Exception:
            await session.rollback()
            raise


async def _on_schedule_milestone_reached(event: Event) -> dict[str, Any]:
    """``schedule.milestone.reached`` -> the instalments that follow it become claimable."""
    data = event.data or {}
    activity_id = _uuid_or_none(data.get("activity_id"))
    if activity_id is None:
        return {"status": "ignored", "reason": "no activity_id"}
    try:
        moved = await _with_contracts_service(
            lambda svc: svc.mark_milestones_reached(
                activity_id,
                project_id=_uuid_or_none(data.get("project_id")),
                reached_at=data.get("reached_at"),
                actor_id=str(data["actor_id"]) if data.get("actor_id") else None,
            )
        )
    except Exception:  # noqa: BLE001 - a subscriber never breaks the publisher
        logger.exception("contracts: schedule.milestone.reached failed for activity %s", activity_id)
        return {"status": "error"}
    return {"status": "ok", "moved": moved}


async def _on_schedule_milestone_reopened(event: Event) -> dict[str, Any]:
    """``schedule.milestone.reopened`` -> unclaimed instalments go back to pending."""
    data = event.data or {}
    activity_id = _uuid_or_none(data.get("activity_id"))
    if activity_id is None:
        return {"status": "ignored", "reason": "no activity_id"}
    try:
        moved = await _with_contracts_service(
            lambda svc: svc.reopen_milestones(activity_id, project_id=_uuid_or_none(data.get("project_id")))
        )
    except Exception:  # noqa: BLE001 - a subscriber never breaks the publisher
        logger.exception("contracts: schedule.milestone.reopened failed for activity %s", activity_id)
        return {"status": "error"}
    return {"status": "ok", "moved": moved}


async def _on_schedule_dates_moved(event: Event) -> dict[str, Any]:
    """A reschedule, an activity edit or a delete -> refresh the forecasts that follow it.

    An activity edit that touched no date is ignored. The schedule service
    sends these after its commit; the live-editing path still sends
    ``schedule.activity.updated`` before its own, so a forecast refreshed
    from that one can be a change behind. The payment plan view works its
    forecasts out live and does not depend on this copy being current.
    """
    data = event.data or {}
    activity_id = _uuid_or_none(data.get("activity_id"))
    schedule_id = _uuid_or_none(data.get("schedule_id"))
    fields = data.get("fields")
    if event.name == SCHEDULE_ACTIVITY_UPDATED and isinstance(fields, list) and "end_date" not in fields:
        return {"status": "ignored", "reason": "no date moved"}
    if event.name in (SCHEDULE_ACTIVITY_UPDATED, SCHEDULE_ACTIVITY_DELETED):
        if activity_id is None:
            return {"status": "ignored", "reason": "no activity_id"}
        schedule_id = None
    elif schedule_id is None:
        return {"status": "ignored", "reason": "no schedule_id"}
    try:
        refreshed = await _with_contracts_service(
            lambda svc: svc.refresh_linked_forecasts(activity_id=activity_id, schedule_id=schedule_id)
        )
    except Exception:  # noqa: BLE001 - a subscriber never breaks the publisher
        logger.exception("contracts: forecast refresh failed for %s", event.name)
        return {"status": "error"}
    return {"status": "ok", "refreshed": refreshed}


def register_payment_plan_subscribers() -> None:
    """Follow the schedule. Idempotent: ``subscribe_once`` skips a handler already bound."""
    event_bus.subscribe_once(SCHEDULE_MILESTONE_REACHED, _on_schedule_milestone_reached)
    event_bus.subscribe_once(SCHEDULE_MILESTONE_REOPENED, _on_schedule_milestone_reopened)
    # One call per name, spelled out: the event-name wiring gate reads the
    # name off each subscribe call and cannot follow a loop variable.
    event_bus.subscribe_once(SCHEDULE_RESCHEDULED, _on_schedule_dates_moved)
    event_bus.subscribe_once(SCHEDULE_ACTIVITY_UPDATED, _on_schedule_dates_moved)
    event_bus.subscribe_once(SCHEDULE_ACTIVITY_DELETED, _on_schedule_dates_moved)
    event_bus.subscribe_once(SCHEDULE_ACTIVITIES_CLEARED, _on_schedule_dates_moved)


# The module loader imports this file at startup; subscribing here keeps the
# registration with the handlers, as cde/events.py does.
register_payment_plan_subscribers()

# The completed-variation rollup into ``Contract.total_value`` is owned by one
# subscriber, ``_on_variation_completed`` in
# ``app.modules.notifications._wave5_cross_module_subscribers``. It carries the
# redelivery key, the project, currency and closed-contract guards and the
# mirrored change order dedupe. Do not add a second writer for
# ``variations.contract_sum.updated`` here: any second writer that works posts
# the same variation to the contract twice.
