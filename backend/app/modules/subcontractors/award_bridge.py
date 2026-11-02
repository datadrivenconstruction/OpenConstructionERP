# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A subcontract package award becomes a subcontract agreement.

``bid_management`` awards a subcontract package, the contract subscriber drafts
the contract twin and publishes ``contracts.contract.drafted_from_bid_award``
after its commit. This handler then writes the :class:`SubcontractAgreement`
linked to that contract (``contract_id``), so the agreement carries the
commitment and the contract does not, with one work package per priced
schedule-of-values line. The scope the subcontractor left out is kept on the
agreement as ``metadata.excluded_scope`` with the leveling plug for each line,
because the main contractor still has to buy it elsewhere.

Idempotent on ``contract_id``: a replayed event finds the agreement it wrote.
A bidder typed in by hand has no directory subcontractor, so the award then
stays a contract only.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.core.events import Event
from app.database import async_session_factory
from app.modules.subcontractors.models import SubcontractAgreement, WorkPackage

logger = logging.getLogger(__name__)

AWARD_SOURCE = "bid_management.package.awarded"


def _uuid(value: object) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


async def _excluded_scope(session: Any, package_id: uuid.UUID, bidder_id: uuid.UUID) -> list[dict[str, str]]:
    from app.modules.bid_management.models import BidComparison, BidLevelingPlug  # noqa: PLC0415

    rows = (
        (
            await session.execute(
                select(BidLevelingPlug)
                .join(BidComparison, BidComparison.id == BidLevelingPlug.comparison_id)
                .where(BidComparison.package_id == package_id, BidLevelingPlug.bidder_id == bidder_id)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "line_item_id": str(p.line_item_id),
            "plug_amount": str(p.amount),
            "plug_source": p.source,
            "reason": p.reason,
        }
        for p in rows
    ]


async def agreement_from_award(
    session: Any, *, contract_id: uuid.UUID, package_id: uuid.UUID, bidder_id: uuid.UUID
) -> SubcontractAgreement | None:
    """Write (or find) the agreement for one subcontract award; ``None`` when it cannot have one."""
    from app.modules.bid_management.award_route import SUPPLY, bid_package_route  # noqa: PLC0415
    from app.modules.bid_management.models import Bidder, BidPackage  # noqa: PLC0415
    from app.modules.contracts.models import Contract, ContractLine  # noqa: PLC0415

    existing = (
        await session.execute(select(SubcontractAgreement).where(SubcontractAgreement.contract_id == contract_id))
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    contract = await session.get(Contract, contract_id)
    package = await session.get(BidPackage, package_id)
    bidder = await session.get(Bidder, bidder_id)
    if contract is None or package is None or bidder is None or bid_package_route(package) == SUPPLY:
        return None
    if bidder.subcontractor_id is None:
        logger.info("award %s: bidder %s is not in the directory; contract only", package.code, bidder.company_name)
        return None
    lines = (
        (
            await session.execute(
                select(ContractLine).where(ContractLine.contract_id == contract_id).order_by(ContractLine.order_index)
            )
        )
        .scalars()
        .all()
    )
    agreement = SubcontractAgreement(
        subcontractor_id=bidder.subcontractor_id,
        project_id=package.project_id,
        title=(contract.title or package.title or package.code)[:500],
        total_value=Decimal(str(contract.total_value or 0)),
        currency=((contract.currency or package.currency or "")[:3]).upper(),
        status="draft",
        contract_id=contract.id,
        created_by=package.created_by,
        metadata_={
            "source": AWARD_SOURCE,
            "bid_package_id": str(package.id),
            "bid_package_code": package.code,
            "awarded_bidder_id": str(bidder.id),
            "excluded_scope": await _excluded_scope(session, package.id, bidder.id),
        },
    )
    session.add(agreement)
    await session.flush()
    for line in lines:
        value = Decimal(str(line.total_value or 0))
        if value <= 0:
            continue
        session.add(
            WorkPackage(
                agreement_id=agreement.id,
                name=(f"{line.code} {line.description}".strip() or line.code or "Scope")[:500],
                scope=line.description or None,
                planned_value=value,
                status="planned",
            )
        )
    await session.flush()
    from app.modules.finance.service import FinanceService  # noqa: PLC0415

    await FinanceService(session).sync_project_budget(package.project_id)
    return agreement


async def on_contract_drafted_from_bid_award(event: Event) -> None:
    """``contracts.contract.drafted_from_bid_award`` -> the subcontract agreement."""
    data = event.data or {}
    contract_id = _uuid(data.get("contract_id"))
    package_id = _uuid(data.get("bid_package_id"))
    bidder_id = _uuid(data.get("awarded_bidder_id"))
    if contract_id is None or package_id is None or bidder_id is None:
        return
    async with async_session_factory() as session:
        agreement = await agreement_from_award(
            session, contract_id=contract_id, package_id=package_id, bidder_id=bidder_id
        )
        if agreement is not None:
            await session.commit()
