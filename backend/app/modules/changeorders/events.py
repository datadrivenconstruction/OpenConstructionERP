# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Change order event subscribers.

``variation.flagged`` -> a DRAFT change order linked back to its source.

The flag is raised by ``app.core.event_handlers`` in two situations, both
already committed by the time it arrives:

* an RFI flagged with a cost impact receives its answer
  (``rfi.response.design_change``), and
* an NCR with a cost impact is closed (``ncr.closed_with_cost_impact``).

Each becomes one change order in ``draft`` with the source's amount and
schedule days, so the change is in the register and cannot fall through the
gap between a site record and the commercial team. Nothing is applied: a draft
moves no budget and no contract value until a person submits and approves it,
and they may equally reject it.

The result is the same record the RFI's and the NCR's own "create variation"
action produces, with the same metadata keys (``source``, ``rfi_id`` /
``ncr_id``) and the same back link (``change_order_id`` on the source row).
That is what makes the pair idempotent in both directions: the event arriving
twice yields one change order, and a person pressing the button after the
draft exists is handed the draft rather than a second order, and the other way
round.

The source row is always re-read in this subscriber's own session. The payload
names the record; it is not trusted for amounts, for the project, or for the
record still qualifying.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import TYPE_CHECKING, Any

from app.core.events import Event, event_bus

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.changeorders.models import ChangeOrder
    from app.modules.changeorders.schemas import ChangeOrderCreate

logger = logging.getLogger(__name__)

VARIATION_FLAGGED = "variation.flagged"

#: Value of ``ChangeOrder.metadata_["auto_drafted"]`` on orders this subscriber
#: created. The change order page reads it to say where the draft came from.
AUTO_DRAFTED_KEY = "auto_drafted"

#: Set on a change order raised from an NCR whose written cost could not be read
#: as one amount. The value is why: ``"ambiguous"`` (``"12.500"`` in a currency
#: with three decimals) or ``"unreadable"`` (``"approx. 5000"``). The order then
#: carries 0 and ``ncr_cost_impact_raw`` keeps what was written, so a person
#: enters the amount instead of approving a guess.
AMOUNT_NEEDS_REVIEW_KEY = "amount_needs_review"

_SOURCE_TYPES = ("rfi", "ncr")
_RFI_ANSWERED_STATES = ("answered", "closed")
_TITLE_MAX = 255
_DESCRIPTION_MAX = 5000

# One drafter per source record inside this process, keyed by loop as well
# because an asyncio.Lock binds to the loop that first waits on it.
_source_locks: dict[tuple[int, str], asyncio.Lock] = {}


def _source_lock(key: str) -> asyncio.Lock:
    lock_key = (id(asyncio.get_running_loop()), key)
    lock = _source_locks.get(lock_key)
    if lock is None:
        lock = asyncio.Lock()
        _source_locks[lock_key] = lock
    return lock


def _coerce_uuid(value: object) -> uuid.UUID | None:
    if value is None or value == "":
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


async def _existing_order(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    source_type: str,
    source_id: uuid.UUID,
    linked_id: str | None,
) -> ChangeOrder | None:
    """The change order already raised from this source, if any.

    The back link is checked first, then the metadata of every order in the
    project, which also catches an order whose back link was lost.
    """
    from sqlalchemy import select

    from app.modules.changeorders.models import ChangeOrder

    linked_uuid = _coerce_uuid(linked_id)
    if linked_uuid is not None:
        order = await session.get(ChangeOrder, linked_uuid)
        if order is not None and order.project_id == project_id:
            return order

    id_key = f"{source_type}_id"
    rows = (
        await session.execute(
            select(ChangeOrder.id, ChangeOrder.metadata_).where(ChangeOrder.project_id == project_id),
        )
    ).all()
    for order_id, metadata in rows:
        if (
            isinstance(metadata, dict)
            and metadata.get("source") == source_type
            and str(metadata.get(id_key) or "") == str(source_id)
        ):
            return await session.get(ChangeOrder, order_id)
    return None


def _rfi_order(rfi: Any) -> ChangeOrderCreate | None:
    from app.modules.changeorders.schemas import ChangeOrderCreate

    if not rfi.cost_impact or rfi.status not in _RFI_ANSWERED_STATES:
        return None
    parts = [f"Variation from RFI {rfi.rfi_number}: {rfi.subject}", "", "Question:", rfi.question or ""]
    if rfi.official_response:
        parts.extend(["", "Response:", rfi.official_response])
    return ChangeOrderCreate(
        project_id=rfi.project_id,
        title=_clip(f"Variation: {rfi.subject}", _TITLE_MAX),
        description=_clip("\n".join(parts), _DESCRIPTION_MAX),
        # The same reason the RFI's own "create variation" action records, so
        # the change order reads the same whichever of the two raised it.
        reason_category="client_request",
        schedule_impact_days=max(int(rfi.schedule_impact_days or 0), 0),
        cost_impact=rfi.cost_impact_value or "0",
        metadata={
            "source": "rfi",
            "rfi_id": str(rfi.id),
            "rfi_number": rfi.rfi_number,
            AUTO_DRAFTED_KEY: True,
            "drafted_from": "rfi.response.design_change",
        },
    )


def _ncr_order(ncr: Any, *, project_currency: str | None = None) -> ChangeOrderCreate | None:
    """The draft for a closed NCR, or ``None`` when it states no cost.

    The cost is free text, read in the convention it was written in
    (``"BRL 12.000,00"`` is twelve thousand). Text with no digit, and a zero
    or negative amount, state no cost. Text with digits that do not make one
    clear amount still drafts, at 0 and marked :data:`AMOUNT_NEEDS_REVIEW_KEY`:
    a plausible wrong number is worse than an obvious blank, and dropping the
    draft would lose the cost the NCR records.
    """
    from app.core.money import read_written_amount
    from app.modules.changeorders.schemas import ChangeOrderCreate

    if not ncr.cost_impact or ncr.status != "closed":
        return None
    written = read_written_amount(ncr.cost_impact, currency_hint=project_currency)
    if written.status == "blank":
        return None
    needs_review: str | None = None
    if written.amount is None:
        amount, needs_review = "0", written.status
    elif written.amount <= 0:
        return None
    else:
        amount = str(written.amount)
    currency = written.currency
    parts = [f"Variation from NCR {ncr.ncr_number}: {ncr.title}", "", "Description:", ncr.description or ""]
    if ncr.corrective_action:
        parts.extend(["", "Corrective Action:", ncr.corrective_action])
    if ncr.root_cause:
        parts.extend(["", "Root Cause:", ncr.root_cause])
    return ChangeOrderCreate(
        project_id=ncr.project_id,
        title=_clip(f"Variation: {ncr.title}", _TITLE_MAX),
        description=_clip("\n".join(parts), _DESCRIPTION_MAX),
        reason_category="non_conformance",
        schedule_impact_days=max(int(ncr.schedule_impact_days or 0), 0),
        currency=currency or "",
        cost_impact=amount,
        metadata={
            "source": "ncr",
            "ncr_id": str(ncr.id),
            "ncr_number": ncr.ncr_number,
            "ncr_cost_impact_raw": ncr.cost_impact,
            AUTO_DRAFTED_KEY: True,
            "drafted_from": "ncr.closed_with_cost_impact",
            **({AMOUNT_NEEDS_REVIEW_KEY: needs_review} if needs_review else {}),
        },
    )


async def draft_change_order_from_source(
    source_type: str,
    source_id: uuid.UUID,
    project_id: uuid.UUID,
) -> ChangeOrder | None:
    """Create the draft change order for one RFI or NCR, unless one exists.

    Returns the new order, or ``None`` when nothing was created: the source is
    missing, belongs to another project, no longer qualifies, or already has
    its change order.
    """
    from pydantic import ValidationError

    from app.database import async_session_factory
    from app.modules.changeorders.service import ChangeOrderService

    if source_type == "rfi":
        from app.modules.rfi.models import RFI as source_model
    else:
        from app.modules.ncr.models import NCR as source_model

    async with async_session_factory() as session:
        # Row lock shared with the RFI's and the NCR's own "create variation"
        # action: whichever takes it second reads the first one's link.
        source = await session.get(source_model, source_id, with_for_update=True)
        if source is None or source.project_id != project_id:
            logger.debug("variation.flagged: %s %s not found in project %s", source_type, source_id, project_id)
            return None

        existing = await _existing_order(
            session,
            project_id=project_id,
            source_type=source_type,
            source_id=source_id,
            linked_id=source.change_order_id,
        )
        if existing is not None:
            if source.change_order_id != str(existing.id):
                source.change_order_id = str(existing.id)
                await session.commit()
            logger.debug("variation.flagged: %s %s already has change order %s", source_type, source_id, existing.code)
            return None

        try:
            if source_type == "rfi":
                data = _rfi_order(source)
            else:
                from sqlalchemy import select

                from app.modules.projects.models import Project

                project_currency = await session.scalar(select(Project.currency).where(Project.id == project_id))
                data = _ncr_order(source, project_currency=project_currency)
        except ValidationError:
            logger.warning(
                "variation.flagged: %s %s carries an amount a change order cannot hold, no draft created",
                source_type,
                source_id,
            )
            return None
        if data is None:
            logger.debug("variation.flagged: %s %s no longer qualifies, no draft created", source_type, source_id)
            return None

        order = await ChangeOrderService(session).create_order(data)
        if source_type == "rfi":
            order.linked_rfi_ids = [str(source_id)]
        source.change_order_id = str(order.id)
        await session.commit()

    logger.info(
        "variation.flagged: drafted change order %s from %s %s (project %s)",
        order.code,
        source_type,
        source_id,
        project_id,
    )
    return order


async def _on_variation_flagged(event: Event) -> None:
    """``variation.flagged`` -> draft change order. Fail-soft, never raises."""
    try:
        data = event.data or {}
        source_type = str(data.get("source_type") or "").strip().lower()
        source_id = _coerce_uuid(data.get("source_id"))
        project_id = _coerce_uuid(data.get("project_id"))
        if source_type not in _SOURCE_TYPES or source_id is None or project_id is None:
            logger.debug("variation.flagged: unusable payload %r, skipping", data)
            return
        async with _source_lock(f"{source_type}:{source_id}"):
            await draft_change_order_from_source(source_type, source_id, project_id)
    except Exception:
        logger.exception("variation.flagged: drafting a change order failed")


def register_changeorder_event_subscribers() -> None:
    """Wire the change order subscribers. Idempotent."""
    event_bus.subscribe_once(VARIATION_FLAGGED, _on_variation_flagged)


__all__ = [
    "AMOUNT_NEEDS_REVIEW_KEY",
    "AUTO_DRAFTED_KEY",
    "VARIATION_FLAGGED",
    "draft_change_order_from_source",
    "register_changeorder_event_subscribers",
]
