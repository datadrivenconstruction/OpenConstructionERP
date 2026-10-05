# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Trainer event handlers: ERP changes mark a learner's course stale (design §6).

Each tracked ERP event resolves to a project, every active enrolment working
in that project is stamped ``stale_since``, and a recheck of the learner's
open task is scheduled, debounced per enrolment (design §4.5). The recheck is
best effort (risk R9): it records a ``trigger="event"`` attempt, graded with
the probes in ``read`` mode, and clears ``stale_since``; it never passes a
task, unlocks, reveals a hint or computes a levelling table. "Check my
work" stays the only way forward.

Every handler:

1. returns at its first line when the academy flag is off;
2. returns for events a running seed published (:func:`seeding_enrolment`);
3. resolves the project from the payload: ``project_id``, else ``boq_id``,
   ``package_id``, ``contract_id``, ``claim_id`` or ``position_id``;
4. never raises: it logs and swallows.

Only names some module publishes are tracked; ``tests/unit/test_event_name_wiring.py``
holds every subscription to that.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from app.core.events import Event, event_bus
from app.modules.trainer.seeder import seeding_enrolment

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

#: ERP events that may change a value a task grades.
TRACKED_EVENTS: tuple[str, ...] = (
    # Bills of quantities: positions, markups, the bill itself.
    "boq.position.created",
    "boq.position.updated",
    "boq.position.deleted",
    "boq.positions.bulk_created",
    "boq.markup.created",
    "boq.markup.updated",
    "boq.markup.deleted",
    "boq.markups.defaults_applied",
    "boq.boq.updated",
    # Tendering.
    "bid_management.package.published",
    "bid_management.invitations.dispatched",
    "bid_management.bids.opened",
    "bid_management.package.awarded",
    "bid_management.submission.received",
    "bid_management.bidder.disqualified",
    "bid_management.bidder.rejected",
    "bid_management.award.deleted",
    "bid_management.package.rejected",
    # Contracts and progress claims.
    "contracts.contract.signed",
    "contracts.contract.amended",
    "contracts.claim.populated",
    "contracts.claim.submitted",
    "contracts.claim.approved",
    "contracts.claim.certified",
    "contracts.claim.paid",
    "contracts.lien_waiver.attached",
)

#: Event-name prefixes tracked whole, through the bus wildcard (design §6:
#: "variations.*, all"). The variations service names most of its status
#: events through a lookup table (``variations.request.approved``,
#: ``variations.vo.voided`` and the rest), so a list of literal names would
#: either miss some or name events a static scan cannot see published.
TRACKED_PREFIXES: tuple[str, ...] = ("variations.",)

#: Seconds a recheck waits for the burst of events one learner action makes.
RECHECK_DEBOUNCE_SECONDS: float = 2.0

_PENDING: dict[uuid.UUID, asyncio.Task[None]] = {}


def _uuid(value: Any) -> uuid.UUID | None:
    if isinstance(value, uuid.UUID):
        return value
    if isinstance(value, str) and value:
        try:
            return uuid.UUID(value)
        except ValueError:
            return None
    return None


def _session_factory() -> Any:
    from app.database import async_session_factory

    return async_session_factory


async def resolve_project_id(session: AsyncSession, data: Mapping[str, Any]) -> uuid.UUID | None:
    """The project an ERP event happened in, or None when the payload names none."""
    project_id = _uuid(data.get("project_id"))
    if project_id is not None:
        return project_id

    from app.modules.bid_management.models import BidPackage
    from app.modules.boq.models import BOQ, Position
    from app.modules.contracts.models import Contract, ProgressClaim

    boq_id = _uuid(data.get("boq_id"))
    if boq_id is not None:
        return await session.scalar(select(BOQ.project_id).where(BOQ.id == boq_id))
    package_id = _uuid(data.get("package_id"))
    if package_id is not None:
        return await session.scalar(select(BidPackage.project_id).where(BidPackage.id == package_id))
    contract_id = _uuid(data.get("contract_id"))
    if contract_id is not None:
        return await session.scalar(select(Contract.project_id).where(Contract.id == contract_id))
    claim_id = _uuid(data.get("claim_id"))
    if claim_id is not None:
        return await session.scalar(
            select(Contract.project_id)
            .join(ProgressClaim, ProgressClaim.contract_id == Contract.id)
            .where(ProgressClaim.id == claim_id)
        )
    position_id = _uuid(data.get("position_id"))
    if position_id is not None:
        return await session.scalar(
            select(BOQ.project_id).join(Position, Position.boq_id == BOQ.id).where(Position.id == position_id)
        )
    return None


async def mark_stale_for_event(data: Mapping[str, Any]) -> list[uuid.UUID]:
    """Stamp ``stale_since`` on the active enrolments of the event's project. Commits.

    Returns:
        The enrolments that were found (and are due a recheck).
    """
    from app.modules.trainer.repository import TrainerRepository

    async with _session_factory()() as session:
        project_id = await resolve_project_id(session, data)
        if project_id is None:
            return []
        repo = TrainerRepository(session)
        enrolment_ids = await repo.running_enrolment_ids_for_project(project_id)
        if enrolment_ids:
            await repo.mark_stale(enrolment_ids, datetime.now(UTC))
            await session.commit()
        return enrolment_ids


async def on_erp_event(event: Event) -> None:
    """Handler for every name in :data:`TRACKED_EVENTS`. Never raises."""
    from app.config import get_settings

    if not get_settings().academy_mode:
        return
    await _handle(event)


async def on_prefixed_event(event: Event) -> None:
    """Wildcard handler: every event under :data:`TRACKED_PREFIXES`. Never raises."""
    from app.config import get_settings

    if not get_settings().academy_mode:
        return
    if not event.name.startswith(TRACKED_PREFIXES):
        return
    await _handle(event)


async def _handle(event: Event) -> None:
    if seeding_enrolment() is not None:
        return  # the seed's own writes are not learner activity (design §5.1)
    try:
        enrolment_ids = await mark_stale_for_event(event.data or {})
    except Exception:
        logger.exception("Trainer could not resolve ERP event %s", event.name)
        return
    for enrolment_id in enrolment_ids:
        schedule_recheck(enrolment_id)


# ── Debounced rechecks ───────────────────────────────────────────────────────


async def _recheck_later(enrolment_id: uuid.UUID, delay: float) -> None:
    await asyncio.sleep(delay)
    from app.modules.trainer.service import TrainerService

    try:
        async with _session_factory()() as session:
            await TrainerService(session).recheck_open_task(enrolment_id)
    except Exception:
        logger.exception("Trainer recheck failed for enrolment %s", enrolment_id)


def schedule_recheck(enrolment_id: uuid.UUID, delay: float | None = None) -> asyncio.Task[None] | None:
    """Schedule one recheck of the enrolment, replacing a pending one (the debounce)."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None
    previous = _PENDING.pop(enrolment_id, None)
    if previous is not None and not previous.done():
        previous.cancel()
    task = loop.create_task(_recheck_later(enrolment_id, RECHECK_DEBOUNCE_SECONDS if delay is None else delay))
    _PENDING[enrolment_id] = task

    def _forget(done: asyncio.Task[None], key: uuid.UUID = enrolment_id) -> None:
        if _PENDING.get(key) is done:
            _PENDING.pop(key, None)

    task.add_done_callback(_forget)
    return task


def pending_rechecks() -> dict[uuid.UUID, asyncio.Task[None]]:
    """The rechecks still waiting, by enrolment (a copy)."""
    return dict(_PENDING)


def cancel_pending_rechecks() -> int:
    """Cancel every waiting recheck. Returns how many were cancelled."""
    cancelled = 0
    for task in list(_PENDING.values()):
        if not task.done():
            task.cancel()
            cancelled += 1
    _PENDING.clear()
    return cancelled


async def drain_pending_rechecks() -> None:
    """Wait for every scheduled recheck to finish (tests and shutdown)."""
    while _PENDING:
        tasks = list(_PENDING.values())
        await asyncio.gather(*tasks, return_exceptions=True)
        for key, task in list(_PENDING.items()):
            if task.done():
                _PENDING.pop(key, None)


# ── Registration ─────────────────────────────────────────────────────────────


def register_trainer_subscribers() -> int:
    """Subscribe :func:`on_erp_event` to every tracked name. Idempotent.

    Returns:
        How many subscriptions were added by this call.
    """
    added = 0
    for name in TRACKED_EVENTS:
        if event_bus.subscribe_once(name, on_erp_event):
            added += 1
    if event_bus.subscribe_once("*", on_prefixed_event):
        added += 1
    return added


def unregister_trainer_subscribers() -> None:
    """Remove the subscriptions (tests)."""
    for name in TRACKED_EVENTS:
        try:
            event_bus.unsubscribe(name, on_erp_event)
        except ValueError:
            continue
    try:
        event_bus.unsubscribe("*", on_prefixed_event)
    except ValueError:
        pass


__all__ = [
    "RECHECK_DEBOUNCE_SECONDS",
    "TRACKED_EVENTS",
    "TRACKED_PREFIXES",
    "cancel_pending_rechecks",
    "drain_pending_rechecks",
    "mark_stale_for_event",
    "on_erp_event",
    "on_prefixed_event",
    "pending_rechecks",
    "register_trainer_subscribers",
    "resolve_project_id",
    "schedule_recheck",
    "unregister_trainer_subscribers",
]
