# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The purchase order from a bid award names the bidder's contact as its vendor.

The order was always written with ``vendor_contact_id=None``, because a bidder
was only a free-text company. A bidder invited from the directory now carries
its contact, and the order takes it. A bidder typed in by hand still has none.
"""

from __future__ import annotations

import uuid

import pytest

from app.modules.procurement import events as proc_events
from tests.unit.test_procurement_events import (
    _bid_award_event,
    _FakeSession,
    _FakeStore,
    _seed_bid_award,
    _StubPOItemRepo,
    _StubPORepo,
)


@pytest.fixture
def patched(monkeypatch: pytest.MonkeyPatch) -> _FakeStore:
    store = _FakeStore()
    monkeypatch.setattr(proc_events, "async_session_factory", lambda: _FakeSession(store))
    monkeypatch.setattr(proc_events, "PurchaseOrderRepository", _StubPORepo)
    monkeypatch.setattr(proc_events, "POItemRepository", _StubPOItemRepo)
    return store


@pytest.mark.asyncio
async def test_the_po_vendor_is_the_bidders_contact(patched: _FakeStore) -> None:
    package, bidder = _seed_bid_award(patched, project_id=uuid.uuid4())
    contact_id = uuid.uuid4()
    bidder.contact_id = contact_id

    await proc_events._create_po_from_bid_award(_bid_award_event(package, bidder))

    [po] = patched.purchase_orders
    assert po.vendor_contact_id == str(contact_id)


@pytest.mark.asyncio
async def test_a_hand_typed_bidder_leaves_the_vendor_empty(patched: _FakeStore) -> None:
    package, bidder = _seed_bid_award(patched, project_id=uuid.uuid4())

    await proc_events._create_po_from_bid_award(_bid_award_event(package, bidder))

    [po] = patched.purchase_orders
    assert po.vendor_contact_id is None
