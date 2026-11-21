# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Boot-path data repairs owned by the bid management module.

Imported by :func:`app.core.data_repairs.discover_data_repairs`, which is what
makes the registration below take effect. Nothing else imports this file.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.data_repairs import DataRepair, NeverDelivered, register_data_repair

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


async def _run_tender_legacy_copy(session: AsyncSession) -> int:
    """Copy tender packages and RFQs that have no canonical mirror yet."""
    from app.modules.bid_management.legacy_copy import copy_all

    def _copy(sync_session) -> int:  # noqa: ANN001 - sync Session from run_sync
        report = copy_all(sync_session.connection(), apply=True, only_unmapped=True)
        return report.rows_changed

    return await session.run_sync(_copy)


#: Nature ``never_delivered``: the canonical mirror of a tendering package or
#: RFQ is missing on every database that predates tmm01, because the boot heal
#: builds the tables and copies nothing. Insert-only: a package already in
#: ``oe_tender_legacy_map`` is skipped, and the map row is what records delivery.
TENDER_LEGACY_COPY = register_data_repair(
    DataRepair(
        repair_id="tender_legacy_copy",
        revision="tmm01_tender_canonical_model",
        summary="Copy tendering packages and RFQs that have no canonical tender package yet",
        run=_run_tender_legacy_copy,
        nature="never_delivered",
        never_delivered=NeverDelivered(table="oe_tender_legacy_map", identified_by=("source_table", "source_id")),
    )
)


async def _run_rfq_mirror_refresh(session: AsyncSession) -> int:
    """Refresh RFQ mirrors copied without the bidder's firm, email or levelled range."""
    from app.modules.bid_management.legacy_copy import refresh_stale_rfq_mirrors

    return await session.run_sync(lambda sync_session: refresh_stale_rfq_mirrors(sync_session.connection()))


#: Nature ``always_wrong``: earlier copies took the bidder's firm only from bid metadata,
#: which the RFQ module leaves empty, and never filled the comparison header, so every
#: such mirror read blank bidders and a 0.00 range. Only mirrors that still show it are
#: re-copied; a refreshed mirror no longer matches, so a second pass changes nothing.
TENDER_RFQ_MIRROR_REFRESH = register_data_repair(
    DataRepair(
        repair_id="tender_rfq_mirror_refresh",
        revision="",
        summary="Re-copy RFQ tender mirrors that lack the bidder's firm and email or the levelled bid range",
        run=_run_rfq_mirror_refresh,
        nature="always_wrong",
    )
)
