"""Event-emission tests for the Tendering service (slice E).

The tendering service had previously commented-out ``_safe_publish`` calls;
slice E re-enables them and adds a missing ``tendering.package.created``
event.  This test guards the new wiring.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.events import Event, event_bus
from app.modules.tendering.schemas import (
    BidCreate,
    BidUpdate,
    PackageCreate,
    PackageUpdate,
)
from app.modules.tendering.service import TenderingService

PROJECT_ID = uuid.uuid4()


# ── Stub repository ───────────────────────────────────────────────────────


class _StubRepo:
    def __init__(self) -> None:
        self.packages: dict[uuid.UUID, Any] = {}
        self.bids: dict[uuid.UUID, Any] = {}

    async def create_package(self, package: Any) -> Any:
        if getattr(package, "id", None) is None:
            package.id = uuid.uuid4()
        now = datetime.now(UTC)
        package.created_at = now
        package.updated_at = now
        if not hasattr(package, "bids"):
            package.bids = []
        self.packages[package.id] = package
        return package

    async def get_package_by_id(self, package_id: uuid.UUID) -> Any:
        return self.packages.get(package_id)

    async def update_package_fields(self, package_id: uuid.UUID, **fields: Any) -> None:
        p = self.packages.get(package_id)
        if p:
            for k, v in fields.items():
                setattr(p, k, v)

    async def create_bid(self, bid: Any) -> Any:
        if getattr(bid, "id", None) is None:
            bid.id = uuid.uuid4()
        now = datetime.now(UTC)
        bid.created_at = now
        bid.updated_at = now
        self.bids[bid.id] = bid
        return bid

    async def get_bid_by_id(self, bid_id: uuid.UUID) -> Any:
        return self.bids.get(bid_id)

    async def update_bid_fields(self, bid_id: uuid.UUID, **fields: Any) -> None:
        b = self.bids.get(bid_id)
        if b:
            for k, v in fields.items():
                setattr(b, k, v)


def _make_service() -> TenderingService:
    svc = TenderingService.__new__(TenderingService)
    svc.session = SimpleNamespace()
    svc.repo = _StubRepo()
    return svc


@pytest.fixture
def captured_events():
    captured: list[Event] = []

    async def _capture(event: Event) -> None:
        captured.append(event)

    event_bus.subscribe("*", _capture)
    try:
        yield captured
    finally:
        event_bus.unsubscribe("*", _capture)


# ── Tests ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_package_emits_event(captured_events: list[Event]) -> None:
    svc = _make_service()

    pkg = await svc.create_package(
        PackageCreate(project_id=PROJECT_ID, name="Concrete works")
    )

    matches = [e for e in captured_events if e.name == "tendering.package.created"]
    assert len(matches) == 1
    payload = matches[0].data
    assert payload["package_id"] == str(pkg.id)
    assert payload["project_id"] == str(PROJECT_ID)
    assert payload["name"] == "Concrete works"
    assert matches[0].source_module == "oe_tendering"


@pytest.mark.asyncio
async def test_update_package_emits_event(captured_events: list[Event]) -> None:
    svc = _make_service()
    pkg = await svc.create_package(
        PackageCreate(project_id=PROJECT_ID, name="Concrete works")
    )
    captured_events.clear()

    await svc.update_package(pkg.id, PackageUpdate(name="Concrete works v2"))

    matches = [e for e in captured_events if e.name == "tendering.package.updated"]
    assert len(matches) == 1
    payload = matches[0].data
    assert payload["package_id"] == str(pkg.id)
    assert "name" in payload["updated_fields"]


@pytest.mark.asyncio
async def test_create_bid_emits_event(captured_events: list[Event]) -> None:
    svc = _make_service()
    pkg = await svc.create_package(
        PackageCreate(project_id=PROJECT_ID, name="Concrete works")
    )
    captured_events.clear()

    bid = await svc.create_bid(
        pkg.id, BidCreate(company_name="ACME GmbH", total_amount="100000")
    )

    matches = [e for e in captured_events if e.name == "tendering.bid.created"]
    assert len(matches) == 1
    payload = matches[0].data
    assert payload["bid_id"] == str(bid.id)
    assert payload["package_id"] == str(pkg.id)
    assert payload["company_name"] == "ACME GmbH"
    assert payload["total_amount"] == "100000"


@pytest.mark.asyncio
async def test_update_bid_emits_event(captured_events: list[Event]) -> None:
    svc = _make_service()
    pkg = await svc.create_package(
        PackageCreate(project_id=PROJECT_ID, name="Concrete works")
    )
    bid = await svc.create_bid(
        pkg.id, BidCreate(company_name="ACME GmbH", total_amount="100000")
    )
    captured_events.clear()

    await svc.update_bid(bid.id, BidUpdate(notes="revised"))

    matches = [e for e in captured_events if e.name == "tendering.bid.updated"]
    assert len(matches) == 1
    payload = matches[0].data
    assert payload["bid_id"] == str(bid.id)
    assert "notes" in payload["updated_fields"]
