# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A bid's figures stop changing once its tender package is awarded or closed.

``apply_winner`` copies the winning bid's unit rates into the BOQ and records
the award against that bid. ``PATCH /bids/{id}`` could still rewrite the bid's
total, currency and line items afterwards, so the award record and the bill no
longer matched the bid they came from, and a losing bid could be repriced after
the decision. Now a change to any of those three fields is refused with a 409
once the package is awarded or closed, before anything is written.

Every refusal has a control: the same edit on a package still in evaluation
goes through, an echo of the stored figures is not a change, and fields that
carry no money (notes) stay editable. The checks read the stored bid from the
repository's own rows.

Run:
    cd backend
    python -m pytest tests/modules/tendering/test_an_awarded_bid_keeps_its_figures.py -v
"""

from __future__ import annotations

import copy
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from app.modules.tendering.schemas import BidCreate, BidLineItem, BidUpdate, PackageCreate
from app.modules.tendering.service import TenderingService

PROJECT_ID = uuid.uuid4()


class _StubRepo:
    """In-memory rows for the repository calls ``create_bid``/``update_bid`` make."""

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

    async def update_package_fields(self, package_id: uuid.UUID, **fields: Any) -> None:
        for key, value in fields.items():
            setattr(self.packages[package_id], key, value)

    async def create_bid(self, bid: Any) -> Any:
        bid.id = uuid.uuid4()
        bid.created_at = bid.updated_at = datetime.now(UTC)
        self.bids[bid.id] = bid
        return bid

    async def get_bid_by_id(self, bid_id: uuid.UUID) -> Any:
        return self.bids.get(bid_id)

    async def update_bid_fields(self, bid_id: uuid.UUID, **fields: Any) -> None:
        for key, value in fields.items():
            setattr(self.bids[bid_id], key, value)


def _service() -> TenderingService:
    svc = TenderingService.__new__(TenderingService)
    svc.session = SimpleNamespace()
    svc.repo = _StubRepo()
    return svc


_LINE = BidLineItem(position_id=str(uuid.uuid4()), unit="m3", quantity=10.0, unit_rate=Decimal("150"), total=1500.0)


async def _bid_on(svc: TenderingService, package_status: str) -> Any:
    """A priced bid on a package that then moves to ``package_status``."""
    package = await svc.create_package(PackageCreate(project_id=PROJECT_ID, name="Concrete works"))
    package.status = "collecting"
    bid = await svc.create_bid(
        package.id,
        BidCreate(company_name="ACME Bau GmbH", total_amount="1500", currency="EUR", line_items=[_LINE]),
    )
    package.status = package_status
    return bid


def _figures(svc: TenderingService, bid_id: uuid.UUID) -> tuple[Any, ...]:
    """(total_amount, currency, line_items, notes) as the repository holds them."""
    row = svc.repo.bids[bid_id]
    return row.total_amount, row.currency, copy.deepcopy(row.line_items), row.notes


_CHANGES = {
    "total_amount": BidUpdate(total_amount="1350"),
    "currency": BidUpdate(currency="USD"),
    "line_items": BidUpdate(line_items=[_LINE.model_copy(update={"unit_rate": Decimal("135"), "total": 1350.0})]),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("package_status", ["awarded", "closed"])
@pytest.mark.parametrize("field", sorted(_CHANGES))
async def test_a_decided_package_refuses_a_change_to_the_bid_figures(package_status: str, field: str) -> None:
    svc = _service()
    bid = await _bid_on(svc, package_status)
    before = _figures(svc, bid.id)

    with pytest.raises(HTTPException) as exc:
        await svc.update_bid(bid.id, _CHANGES[field])

    assert exc.value.status_code == 409
    assert exc.value.detail == (
        f"Bid is locked - package is '{package_status}'. "
        "Its total, currency and line items cannot change after the award or close."
    )
    assert _figures(svc, bid.id) == before


@pytest.mark.asyncio
async def test_a_refused_change_writes_nothing_of_the_rest_of_the_patch() -> None:
    svc = _service()
    bid = await _bid_on(svc, "awarded")
    before = _figures(svc, bid.id)

    with pytest.raises(HTTPException):
        await svc.update_bid(bid.id, BidUpdate(total_amount="1350", notes="revised after award"))

    assert _figures(svc, bid.id) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("field", sorted(_CHANGES))
async def test_a_package_under_evaluation_still_takes_the_change(field: str) -> None:
    """The control: before the decision the bid can still be corrected."""
    svc = _service()
    bid = await _bid_on(svc, "evaluating")
    before = _figures(svc, bid.id)

    await svc.update_bid(bid.id, _CHANGES[field])

    assert _figures(svc, bid.id) != before


@pytest.mark.asyncio
async def test_an_echo_of_the_stored_figures_is_not_a_change() -> None:
    """A client that sends the bid back unchanged is not refused."""
    svc = _service()
    bid = await _bid_on(svc, "awarded")
    before = _figures(svc, bid.id)

    await svc.update_bid(bid.id, BidUpdate(total_amount="1500", currency="EUR", line_items=[_LINE], notes="filed"))

    total, currency, lines, notes = _figures(svc, bid.id)
    assert (total, currency, lines) == before[:3]
    assert notes == "filed"


@pytest.mark.asyncio
async def test_a_note_on_an_awarded_bid_still_changes() -> None:
    """Fields without money stay editable after the award."""
    svc = _service()
    bid = await _bid_on(svc, "awarded")
    before = _figures(svc, bid.id)

    await svc.update_bid(bid.id, BidUpdate(notes="contract signed 3 March"))

    assert _figures(svc, bid.id) == (*before[:3], "contract signed 3 March")
