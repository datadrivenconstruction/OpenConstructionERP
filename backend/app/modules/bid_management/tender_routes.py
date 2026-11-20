# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The main contract tender and supplier RFQ routes, under the canonical tenders API.

Mounted on the bid management router, so they answer at

* ``/api/v1/bid-management/tenders/main-contract/...`` (was ``/api/v1/tendering/...``)
* ``/api/v1/bid-management/tenders/rfq/...`` (was ``/api/v1/rfq-bidding/...``)

with the same handlers, permissions and project checks. A path id may be the
canonical package id or the old id (``legacy_adapter``). The old mounts stay as
deprecated adapters until the sunset; the bidder portal keeps its old address
only, because its links already sit in bidders' mailboxes.
"""

from __future__ import annotations

from fastapi import APIRouter

MAIN_CONTRACT_PREFIX = "/main-contract"
RFQ_PREFIX = "/rfq"


def _without_portal(source: APIRouter) -> APIRouter:
    staged = APIRouter()
    staged.include_router(source)
    staged.routes[:] = [r for r in staged.routes if "/bid-portal/" not in getattr(r, "path", "")]
    return staged


def build_canonical_router() -> APIRouter:
    """A router carrying the old tendering and RFQ handlers under canonical paths."""
    from app.modules.rfq_bidding.router import router as rfq_router  # noqa: PLC0415
    from app.modules.tendering.router import router as tendering_router  # noqa: PLC0415

    router = APIRouter()
    router.include_router(_without_portal(tendering_router), prefix=MAIN_CONTRACT_PREFIX, tags=["tenders"])
    router.include_router(_without_portal(rfq_router), prefix=RFQ_PREFIX, tags=["tenders"])
    return router
