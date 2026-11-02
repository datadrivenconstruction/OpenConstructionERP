# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""One award, one commitment: which record an award turns into.

Three modules award work, each with its own role:

* ``tendering``: the main contract tender, priced from the bill. Its award
  drafts the contract (``bid_management/events.py``) and nothing else.
* ``bid_management``: subcontract and supply packages. A ``subcontract``
  package drafts the contract twin and the subcontract agreement that carries
  the commitment; a ``supply`` package drafts the purchase order only.
* ``rfq_bidding``: supplier quotes; its award drafts a purchase order
  (``procurement/rfq_award.py``).

Every award subscriber asks this module before writing, so one award never
yields both a purchase order and a contract, and a tender package that a bid
package is linked to (``BidPackage.tender_id``) defers to that bid package:
the award event of the bid package is the single path for that work.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

SUBCONTRACT = "subcontract"
SUPPLY = "supply"
#: Route of a tender award: the main contract.
CONTRACT = "contract"
#: Route of a tender award whose work is awarded through a linked bid package.
DEFERRED = "deferred"


def bid_package_route(package: Any) -> str:
    """``supply`` for a supply package, ``subcontract`` for everything else."""
    return SUPPLY if (getattr(package, "package_type", None) or SUBCONTRACT) == SUPPLY else SUBCONTRACT


async def tender_award_route(session: Any, tender_package: Any) -> str:
    """Route of a ``tendering.package.awarded`` event for this tender package.

    ``deferred`` when a bid package is linked to it, ``supply`` when the tender
    package says so in ``metadata.package_type``, ``contract`` otherwise.
    """
    from app.modules.bid_management.models import BidPackage  # noqa: PLC0415

    package_id = getattr(tender_package, "id", None)
    if isinstance(package_id, uuid.UUID):
        linked = (
            await session.execute(select(BidPackage.id).where(BidPackage.tender_id == package_id).limit(1))
        ).scalar_one_or_none()
        if linked is not None:
            return DEFERRED
    metadata = getattr(tender_package, "metadata_", None)
    if isinstance(metadata, dict) and metadata.get("package_type") == SUPPLY:
        return SUPPLY
    return CONTRACT
