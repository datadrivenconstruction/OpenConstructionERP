# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Boot-path data repairs owned by the bid management module.

Imported by :func:`app.core.data_repairs.discover_data_repairs`, which is what
makes the registration below take effect. Nothing else imports this file.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.data_repairs import DataRepair, register_data_repair

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def _run_award_counterparty(session: AsyncSession) -> int:
    """Imported inside the function so registering costs only the registration."""
    from app.modules.bid_management.award_contract import repair_bidder_counterparties

    return await repair_bidder_counterparties(session)


#: Nature ``always_wrong``: a contract whose counterparty is the bid_management
#: bidder row never named a firm anybody can resolve, so pointing it at the
#: bidder's directory entry, or at nothing, corrects a value that was never
#: right. No alembic revision sits behind this; the defect was in the award
#: subscriber, and v47_bid_award_links only adds the columns it reads.
BID_AWARD_CONTRACT_COUNTERPARTY = register_data_repair(
    DataRepair(
        repair_id="bid_award_contract_counterparty",
        revision="",
        summary="Point award contracts that name the bidder row at the bidder's firm, or at no counterparty",
        run=_run_award_counterparty,
        nature="always_wrong",
    )
)
