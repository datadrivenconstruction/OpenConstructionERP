# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""An awarded or closed tender package takes no new bids.

``POST /packages/{id}/bids`` only checked that the package existed, so a bid
could be added after the award. It then sat in the bid comparison and the
award record next to the bids the decision was made on, priced after the fact.
Now ``create_bid`` refuses with a 409 once the package is awarded or closed,
and no row is written.

The control: every state before the decision still takes a bid, draft
included (entering bids received on paper before the package is issued is a
normal way to work). The checks read the repository's own rows.

Run:
    cd backend
    python -m pytest tests/modules/tendering/test_a_decided_package_takes_no_new_bids.py -v
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from app.modules.tendering.schemas import BidCreate, PackageCreate
from app.modules.tendering.service import TenderingService

PROJECT_ID = uuid.uuid4()


class _StubRepo:
    """In-memory rows for the repository calls ``create_bid`` makes."""

    def __init__(self) -> None:
        self.packages: dict[uuid.UUID, Any] = {}
        self.bids: dict[uuid.UUID, Any] = {}

    async def create_package(self, package: Any) -> Any:
        package.id = uuid.uuid4()
        package.created_at = package.updated_at = datetime.now(UTC)
        package.bids = []
        self.packages[package.id] = package
        return package

    async def get_package_by_id(self, package_id: uuid.UUID) -> Any:
        return self.packages.get(package_id)

    async def create_bid(self, bid: Any) -> Any:
        bid.id = uuid.uuid4()
        bid.created_at = bid.updated_at = datetime.now(UTC)
        self.bids[bid.id] = bid
        return bid


def _service() -> TenderingService:
    svc = TenderingService.__new__(TenderingService)
    svc.session = SimpleNamespace()
    svc.repo = _StubRepo()
    return svc


async def _package_in(svc: TenderingService, package_status: str) -> Any:
    package = await svc.create_package(PackageCreate(project_id=PROJECT_ID, name="Concrete works"))
    package.status = package_status
    return package


_LATE_BID = BidCreate(company_name="Late Bau GmbH", total_amount="990", currency="EUR")


@pytest.mark.asyncio
@pytest.mark.parametrize("package_status", ["awarded", "closed"])
async def test_a_decided_package_refuses_a_new_bid(package_status: str) -> None:
    svc = _service()
    package = await _package_in(svc, package_status)

    with pytest.raises(HTTPException) as exc:
        await svc.create_bid(package.id, _LATE_BID)

    assert exc.value.status_code == 409
    assert exc.value.detail == f"Package is '{package_status}' and accepts no new bids"
    assert svc.repo.bids == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("package_status", ["draft", "issued", "collecting", "evaluating"])
async def test_a_package_before_the_decision_takes_the_bid(package_status: str) -> None:
    """The control: the same bid lands while the tender is still open."""
    svc = _service()
    package = await _package_in(svc, package_status)

    bid = await svc.create_bid(package.id, _LATE_BID)

    stored = svc.repo.bids[bid.id]
    assert (stored.package_id, stored.company_name, stored.total_amount) == (package.id, "Late Bau GmbH", "990")


@pytest.mark.asyncio
async def test_a_bid_for_a_missing_package_is_still_a_404() -> None:
    svc = _service()

    with pytest.raises(HTTPException) as exc:
        await svc.create_bid(uuid.uuid4(), _LATE_BID)

    assert exc.value.status_code == 404
    assert svc.repo.bids == {}
