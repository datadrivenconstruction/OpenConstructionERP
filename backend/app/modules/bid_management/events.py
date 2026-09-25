# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Bid management event handlers - a contract draft from a tender award.

The platform has two award paths. ``bid_management.package.awarded`` drafts a
contract (``notifications/_wave5_cross_module_subscribers.py``) and a purchase
order (``procurement/events.py``). ``tendering.package.awarded`` drafted only
the purchase order, so an award made in the tendering module left the
contracts register empty and the progress claims with nothing to bill against.

:func:`_on_tender_awarded` closes that gap. It drafts the contract from the
winning :class:`TenderBid`, copying each bid line onto a schedule-of-values
line and keeping the bill position it was priced against under
``ContractLine.metadata_["boq_position_id"]``, the key the contracts progress
bridge reads.

What it does not do, on purpose:

* It creates no purchase order and publishes nothing procurement listens to.
  The purchase order for this award is procurement's, from the same event.
* It sets no ``ContractLine.cost_line_id``. The purchase order lines already
  carry the cost line for this award, and a second link on the contract lines
  would commit the same money twice in the cost model.

Idempotency: ``metadata.tender_package_id`` is the key, shared with the
bid_management path whenever a bid package is linked to this tender package
(``BidPackage.tender_id``), so a project that runs both modules for one award
gets one contract whichever path fires first.

Module is auto-imported by the module loader when ``oe_bid_management`` is
loaded (``module_loader._load_module`` imports ``events.py``).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select

from app.core.events import Event, _log_failures, event_bus
from app.database import async_session_factory
from app.modules.bid_management.award_contract import (
    add_award_party,
    find_award_contract,
    free_contract_code,
    resolve_award_counterparty,
)

logger = logging.getLogger(__name__)

#: Pauses before re-reading an award that is not visible yet. The tendering
#: publisher emits before its request commits, so the first read can land
#: before the award does. Reading ``awarded`` / ``accepted`` is what keeps a
#: rolled-back award from producing a contract, and the short wait is what
#: keeps a committed one from being missed. About four seconds in all.
_VISIBILITY_WAITS: tuple[float, ...] = (0.25, 0.5, 1.0, 2.0)


def _to_decimal(value: object) -> Decimal:
    """Coerce a JSON-loaded number or string to Decimal, defaulting to 0."""
    if value is None or value == "":
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _parse_uuid(value: object) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def _recipient_subcontractor(package_metadata: Any, contact_email: str) -> uuid.UUID | None:
    """The directory subcontractor the winning bidder was invited as, if any.

    Distribution records each recipient under ``metadata.recipients`` with its
    email and, when picked from the directory, its ``subcontractor_id``. A bid
    carries only a free-text company and an email, so the email is the one
    thing that ties the two together.
    """
    email = (contact_email or "").strip().lower()
    if not email or not isinstance(package_metadata, dict):
        return None
    for recipient in package_metadata.get("recipients") or []:
        if not isinstance(recipient, dict):
            continue
        if (str(recipient.get("email") or "")).strip().lower() == email:
            sub_id = _parse_uuid(recipient.get("subcontractor_id"))
            if sub_id is not None:
                return sub_id
    return None


async def _on_tender_awarded(event: Event) -> None:
    """Schedule the contract draft for a tender award as a detached task.

    Detached for the reason procurement's handler is: the publisher still
    holds its request transaction, and a second session opened synchronously
    here would contend with it.
    """
    _log_failures(
        _draft_contract_from_tender_award(event),
        name="bid_management.contract_from_tender_award",
    )


async def _draft_contract_from_tender_award(event: Event) -> None:
    """Draft a contract from a winning tender bid. See the module docstring."""
    data = event.data or {}
    package_id = _parse_uuid(data.get("package_id"))
    bid_id = _parse_uuid(data.get("bid_id"))
    if package_id is None or bid_id is None:
        return

    for wait in (0.0, *_VISIBILITY_WAITS):
        if wait:
            await asyncio.sleep(wait)
        outcome = await _try_draft(package_id, bid_id, awarded_by=data.get("awarded_by"))
        if outcome != "not_visible":
            return
    logger.warning(
        "tender.awarded: package %s is not awarded to bid %s after waiting; no contract drafted",
        package_id,
        bid_id,
    )


async def _try_draft(package_id: uuid.UUID, bid_id: uuid.UUID, *, awarded_by: object) -> str:
    """One attempt. Returns ``not_visible`` when the award is not committed yet."""
    from app.modules.bid_management.models import BidPackage  # noqa: PLC0415
    from app.modules.boq.models import Position  # noqa: PLC0415
    from app.modules.contracts.models import Contract, ContractLine  # noqa: PLC0415
    from app.modules.tendering.models import TenderBid, TenderPackage  # noqa: PLC0415

    async with async_session_factory() as session:
        package = await session.get(TenderPackage, package_id)
        bid = await session.get(TenderBid, bid_id)
        if package is None or bid is None:
            return "not_visible"
        if package.status != "awarded" or bid.status != "accepted" or bid.package_id != package.id:
            return "not_visible"

        linked_bid_packages = (
            (await session.execute(select(BidPackage.id).where(BidPackage.tender_id == package_id))).scalars().all()
        )
        for key in [{"tender_package_id": str(package_id)}] + [
            {"bid_package_id": str(bp_id)} for bp_id in linked_bid_packages
        ]:
            existing = await find_award_contract(session, package.project_id, keys=key)
            if existing is not None:
                logger.info(
                    "tender.awarded: contract %s already drafted for tender package %s (idempotent skip)",
                    existing.code,
                    package_id,
                )
                return "done"

        counterparty = await resolve_award_counterparty(
            session,
            subcontractor_id=_recipient_subcontractor(package.metadata_, bid.contact_email),
            contact_id=None,
            company_name=bid.company_name,
        )

        # Only a position of this package's own bill is kept as a link. Bid
        # lines are free JSON, and apply_winner guards its rate writes the
        # same way, so a stray id cannot bill another estimate's progress.
        raw_lines = [line for line in (bid.line_items or []) if isinstance(line, dict)]
        wanted_positions = {pid for pid in (_parse_uuid(line.get("position_id")) for line in raw_lines) if pid}
        positions: dict[uuid.UUID, Position] = {}
        if wanted_positions and package.boq_id is not None:
            rows = (
                (
                    await session.execute(
                        select(Position).where(Position.id.in_(wanted_positions), Position.boq_id == package.boq_id)
                    )
                )
                .scalars()
                .all()
            )
            positions = {p.id: p for p in rows}

        running_total = Decimal("0")
        line_specs: list[dict[str, Any]] = []
        for idx, line in enumerate(raw_lines):
            qty = _to_decimal(line.get("quantity"))
            rate = _to_decimal(line.get("unit_rate"))
            total = qty * rate
            running_total += total
            position = positions.get(_parse_uuid(line.get("position_id")) or uuid.UUID(int=0))
            line_specs.append(
                {
                    "code": (position.ordinal if position is not None else f"{idx + 1:03d}")[:80],
                    "description": str(line.get("description") or (position.description if position else "")),
                    "unit": (str(line.get("unit") or "")[:20]) or None,
                    "quantity": qty,
                    "unit_rate": rate,
                    "total_value": total,
                    "order_index": idx,
                    "position_id": position.id if position is not None else None,
                }
            )

        # The same figure the purchase order for this award takes: the lines
        # when they are priced, else the bid total (a lump sum above the lines).
        bid_total = _to_decimal(bid.total_amount)
        total_value = running_total if running_total > 0 else bid_total

        code = await free_contract_code(session, f"CONTRACT-TND-{package_id.hex[:8].upper()}")
        contract = Contract(
            code=code,
            title=(package.name or code)[:500],
            contract_type="lump_sum",
            counterparty_type="subcontractor",
            counterparty_id=counterparty.counterparty_id,
            project_id=package.project_id,
            total_value=total_value,
            currency=(bid.currency or "")[:3],
            status="draft",
            terms={},
            created_by=str(awarded_by)[:36] if awarded_by else None,
        )
        contract.metadata_ = {
            "source": "tendering.package.awarded",
            "tender_package_id": str(package_id),
            "tender_bid_id": str(bid_id),
            "tender_package_name": package.name,
            "awarded_bidder_name": bid.company_name,
            "boq_id": str(package.boq_id) if package.boq_id else None,
        }
        if counterparty.contact_id is not None:
            contract.metadata_["counterparty_contact_id"] = str(counterparty.contact_id)
        session.add(contract)
        await session.flush()
        add_award_party(session, contract.id, counterparty)

        for spec in line_specs:
            cl = ContractLine(
                contract_id=contract.id,
                code=spec["code"],
                description=spec["description"],
                scope_section=None,
                line_type="work",
                unit=spec["unit"],
                quantity=spec["quantity"],
                unit_rate=spec["unit_rate"],
                total_value=spec["total_value"],
                order_index=spec["order_index"],
            )
            cl.metadata_ = {"tender_bid_line_index": spec["order_index"]}
            if spec["position_id"] is not None:
                # contracts.service.BOQ_POSITION_META_KEY
                cl.metadata_["boq_position_id"] = str(spec["position_id"])
            session.add(cl)

        await session.commit()

        event_bus.publish_detached(
            "contracts.contract.drafted_from_bid_award",
            {
                "contract_id": str(contract.id),
                "contract_code": contract.code,
                "tender_package_id": str(package_id),
                "tender_bid_id": str(bid_id),
                "total_value": str(contract.total_value),
                "project_id": str(package.project_id),
            },
            source_module="contracts",
        )
        logger.info("Auto-created contract draft %s from tender award (package=%s)", contract.code, package_id)
        return "done"


# Register at module import - module_loader imports this file when
# ``oe_bid_management`` is loaded.
event_bus.subscribe_once("tendering.package.awarded", _on_tender_awarded)
