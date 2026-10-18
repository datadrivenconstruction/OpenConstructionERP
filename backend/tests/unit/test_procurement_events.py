"""Reconciliation tests for procurement auto-PO event handlers (Lane C).

A project may run BOTH ``oe_tendering`` and ``oe_bid_management``. Each
publishes its own award event and procurement auto-creates a draft
Purchase Order from the winner. These tests pin the contract that the two
paths converge on a SINGLE purchase order for one logical award and that
re-firing an award is idempotent.

The handlers under test open their own ``async_session_factory()`` session
and read bid_management / tendering rows directly, so we drive them with a
DB-free fake session that serves seeded rows and records created POs. This
matches the stub-based style of ``backend/tests/unit/test_procurement.py``
and keeps the suite runnable without booting PostgreSQL.

The tests are written as files only; per the parallel-run rules they are
not executed here.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.events import Event
from app.modules.bid_management.models import (
    Bidder,
    BidPackage,
    BidPackageLineItem,
    BidSubmission,
    BidSubmissionLine,
)
from app.modules.procurement import events as proc_events
from app.modules.procurement.models import ProcurementProjectSettings, PurchaseOrder, PurchaseOrderItem
from app.modules.tendering.models import TenderBid, TenderPackage

# ── Fake session / repositories ────────────────────────────────────────────


class _Result:
    """Minimal mimic of a SQLAlchemy ``Result`` over an in-memory list.

    Two ways this differs from the real thing, both of which matter when a
    query can return more than one row:

    ``scalar_one_or_none`` here returns the first row where SQLAlchemy raises
    ``MultipleResultsFound``. A handler that reads an unbounded query this way
    therefore looks correct under these tests and fails in production.

    ``order_by`` and ``limit`` are not modelled at all - the fake session hands
    back rows in the order they were seeded. Anything that depends on which row
    a query picks has to be tested against a real database; these tests can only
    show that a single-row case still works.
    """

    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _Result:
        return self

    def all(self) -> list[Any]:
        return list(self._rows)

    def first(self) -> Any | None:
        return self._rows[0] if self._rows else None

    def scalar_one_or_none(self) -> Any | None:
        return self._rows[0] if self._rows else None


class _FakeStore:
    """Shared in-memory store seeded per test and queried by the fake session."""

    def __init__(self) -> None:
        self.bid_packages: list[BidPackage] = []
        self.bidders: list[Bidder] = []
        self.bid_submissions: list[BidSubmission] = []
        self.bid_submission_lines: list[BidSubmissionLine] = []
        self.bid_package_lines: list[BidPackageLineItem] = []
        self.tender_packages: list[TenderPackage] = []
        self.tender_bids: list[TenderBid] = []
        self.purchase_orders: list[PurchaseOrder] = []
        self.po_items: list[PurchaseOrderItem] = []
        self.settings: list[ProcurementProjectSettings] = []


def _entity_of(stmt: Any) -> Any:
    """Return the primary mapped entity a ``select`` targets."""
    desc = stmt.column_descriptions[0]
    return desc.get("entity") or desc.get("type")


def _projected_column(stmt: Any) -> str | None:
    """Return the attribute key when *stmt* selects a single column, else None.

    ``select(BidPackage)`` and ``select(BidPackage.id)`` both report
    ``entity == BidPackage`` in ``column_descriptions``; the distinguishing
    factor is whether the selected ``expr`` is the mapped class itself (full
    entity) or an instrumented attribute (a single projected column).
    """
    desc = stmt.column_descriptions[0]
    expr = desc.get("expr")
    if expr is None or isinstance(expr, type):
        return None
    return getattr(expr, "key", None)


def _criteria(stmt: Any) -> list[Any]:
    """Flatten a statement's WHERE clause into a list of binary criteria."""
    where = stmt.whereclause
    if where is None:
        return []
    if hasattr(where, "clauses"):
        return list(where.clauses)
    return [where]


def _filter_eq(rows: list[Any], stmt: Any) -> list[Any]:
    """Apply the simple ``col == value`` criteria carried by *stmt*.

    Only the equality predicates the handlers actually use are honoured
    (id / project_id / tender_id / bidder_id / submission_id / package_id),
    which is enough to disambiguate the seeded rows without a real engine.
    """
    out = rows
    for crit in _criteria(stmt):
        col = getattr(crit.left, "key", None)
        val = getattr(crit.right, "value", None)
        if col is None:
            continue
        out = [r for r in out if getattr(r, col, None) == val]
    return out


class _FakeSession:
    """Async-context-manager session backed by a :class:`_FakeStore`."""

    def __init__(self, store: _FakeStore) -> None:
        self.store = store
        self.committed = False

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def execute(self, stmt: Any) -> _Result:
        entity = _entity_of(stmt)
        mapping = {
            BidPackage: self.store.bid_packages,
            Bidder: self.store.bidders,
            BidSubmission: self.store.bid_submissions,
            BidSubmissionLine: self.store.bid_submission_lines,
            BidPackageLineItem: self.store.bid_package_lines,
            TenderPackage: self.store.tender_packages,
            TenderBid: self.store.tender_bids,
            PurchaseOrder: self.store.purchase_orders,
            ProcurementProjectSettings: self.store.settings,
        }
        rows = mapping.get(entity, [])
        matched = _filter_eq(rows, stmt)
        # ``select(BidPackage.id)`` projects a single column → return ids.
        projected = _projected_column(stmt)
        if projected is not None:
            return _Result([getattr(r, projected, None) for r in matched])
        return _Result(matched)

    def add(self, obj: Any) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        if isinstance(obj, PurchaseOrder):
            self.store.purchase_orders.append(obj)
        elif isinstance(obj, PurchaseOrderItem):
            self.store.po_items.append(obj)

    async def flush(self) -> None:
        return None

    async def refresh(self, _obj: Any) -> None:
        return None

    async def commit(self) -> None:
        self.committed = True

    def expire_all(self) -> None:
        return None


class _StubPORepo:
    """Replacement for ``PurchaseOrderRepository`` over the fake store."""

    def __init__(self, session: _FakeSession) -> None:
        self.session = session
        self.store = session.store

    async def next_po_number(self, _project_id: uuid.UUID) -> str:
        return f"PO-{len(self.store.purchase_orders) + 1:03d}"

    async def create(self, po: PurchaseOrder) -> PurchaseOrder:
        self.session.add(po)
        return po


class _StubPOItemRepo:
    """Replacement for ``POItemRepository`` over the fake store."""

    def __init__(self, session: _FakeSession) -> None:
        self.session = session

    async def create(self, item: PurchaseOrderItem) -> PurchaseOrderItem:
        self.session.add(item)
        return item


# ── Seed helpers ───────────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(UTC)


def _seed_bid_award(
    store: _FakeStore,
    *,
    project_id: uuid.UUID,
    tender_id: uuid.UUID | None = None,
) -> tuple[BidPackage, Bidder]:
    """Seed a closed bid package with one valid winning submission."""
    package = BidPackage(
        id=uuid.uuid4(),
        project_id=project_id,
        tender_id=tender_id,
        code="BP-001",
        title="Concrete works",
        currency="EUR",
        status="awarded",
    )
    store.bid_packages.append(package)

    line = BidPackageLineItem(
        id=uuid.uuid4(),
        package_id=package.id,
        code="C.01",
        description="C30/37 slab",
        unit="m3",
        quantity="100",
    )
    store.bid_package_lines.append(line)

    bidder = Bidder(
        id=uuid.uuid4(),
        package_id=package.id,
        company_name="ACME Bau GmbH",
        contact_email="bids@acme.example",
        status="active",
    )
    store.bidders.append(bidder)

    submission = BidSubmission(
        id=uuid.uuid4(),
        invitation_id=uuid.uuid4(),
        bidder_id=bidder.id,
        total_amount="95000.00",
        currency="EUR",
        is_valid=True,
    )
    submission.created_at = _now()
    store.bid_submissions.append(submission)

    store.bid_submission_lines.append(
        BidSubmissionLine(
            id=uuid.uuid4(),
            submission_id=submission.id,
            line_item_id=line.id,
            unit_price="950",
            quantity_priced="100",
            total_price="95000.00",
        )
    )
    return package, bidder


def _bid_award_event(package: BidPackage, bidder: Bidder) -> Event:
    return Event(
        name="bid_management.package.awarded",
        data={
            "package_id": str(package.id),
            "project_id": str(package.project_id),
            "awarded_bidder_id": str(bidder.id),
            "awarded_amount": "95000.00",
            "currency": "EUR",
        },
        source_module="bid_management",
    )


@pytest.fixture
def patched(monkeypatch: pytest.MonkeyPatch) -> _FakeStore:
    """Wire the procurement handlers to a fresh in-memory store."""
    store = _FakeStore()

    monkeypatch.setattr(proc_events, "async_session_factory", lambda: _FakeSession(store))
    monkeypatch.setattr(proc_events, "PurchaseOrderRepository", _StubPORepo)
    monkeypatch.setattr(proc_events, "POItemRepository", _StubPOItemRepo)
    return store


# ── Tests ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bid_award_creates_single_po(patched: _FakeStore) -> None:
    project_id = uuid.uuid4()
    package, bidder = _seed_bid_award(patched, project_id=project_id)

    await proc_events._create_po_from_bid_award(_bid_award_event(package, bidder))

    assert len(patched.purchase_orders) == 1
    po = patched.purchase_orders[0]
    assert po.project_id == project_id
    assert po.metadata_["bid_package_id"] == str(package.id)
    assert po.metadata_["origin"] == "bid_management_award"
    assert po.metadata_["supplier_name"] == "ACME Bau GmbH"
    assert po.currency_code == "EUR"
    assert po.amount_total == "95000.00"
    # One PO item mapped from the single submission line.
    assert len(patched.po_items) == 1
    assert patched.po_items[0].description == "C30/37 slab"


@pytest.mark.asyncio
async def test_bid_award_replay_is_idempotent(patched: _FakeStore) -> None:
    project_id = uuid.uuid4()
    package, bidder = _seed_bid_award(patched, project_id=project_id)
    event = _bid_award_event(package, bidder)

    await proc_events._create_po_from_bid_award(event)
    await proc_events._create_po_from_bid_award(event)

    assert len(patched.purchase_orders) == 1


@pytest.mark.asyncio
async def test_tender_then_bid_does_not_double_create(patched: _FakeStore) -> None:
    """Tender award fires first; the linked bid award must skip creation."""
    project_id = uuid.uuid4()
    tender_pkg = TenderPackage(
        id=uuid.uuid4(),
        project_id=project_id,
        name="Concrete works",
    )
    patched.tender_packages.append(tender_pkg)
    tender_bid = TenderBid(
        id=uuid.uuid4(),
        package_id=tender_pkg.id,
        company_name="ACME Bau GmbH",
        contact_email="bids@acme.example",
        total_amount="95000.00",
        currency="EUR",
        line_items=[],
    )
    patched.tender_bids.append(tender_bid)

    # Bid package linked to the tendering package by tender_id.
    package, bidder = _seed_bid_award(patched, project_id=project_id, tender_id=tender_pkg.id)

    tender_event = Event(
        name="tendering.package.awarded",
        data={"package_id": str(tender_pkg.id), "bid_id": str(tender_bid.id)},
        source_module="oe_tendering",
    )
    await proc_events._create_po_from_award(tender_event)
    assert len(patched.purchase_orders) == 1
    # Shared reconciliation key stamped by the tender path.
    assert patched.purchase_orders[0].metadata_["tender_package_id"] == str(tender_pkg.id)

    # Bid award for the same logical package must reconcile to the existing PO.
    await proc_events._create_po_from_bid_award(_bid_award_event(package, bidder))
    assert len(patched.purchase_orders) == 1


@pytest.mark.asyncio
async def test_bid_then_tender_does_not_double_create(patched: _FakeStore) -> None:
    """Bid award fires first; the linked tender award must skip creation."""
    project_id = uuid.uuid4()
    tender_pkg = TenderPackage(
        id=uuid.uuid4(),
        project_id=project_id,
        name="Concrete works",
    )
    patched.tender_packages.append(tender_pkg)
    tender_bid = TenderBid(
        id=uuid.uuid4(),
        package_id=tender_pkg.id,
        company_name="ACME Bau GmbH",
        contact_email="bids@acme.example",
        total_amount="95000.00",
        currency="EUR",
        line_items=[],
    )
    patched.tender_bids.append(tender_bid)
    package, bidder = _seed_bid_award(patched, project_id=project_id, tender_id=tender_pkg.id)

    await proc_events._create_po_from_bid_award(_bid_award_event(package, bidder))
    assert len(patched.purchase_orders) == 1
    assert patched.purchase_orders[0].metadata_["tender_package_id"] == str(tender_pkg.id)

    tender_event = Event(
        name="tendering.package.awarded",
        data={"package_id": str(tender_pkg.id), "bid_id": str(tender_bid.id)},
        source_module="oe_tendering",
    )
    await proc_events._create_po_from_award(tender_event)
    assert len(patched.purchase_orders) == 1


@pytest.mark.asyncio
async def test_missing_package_or_bidder_is_noop(patched: _FakeStore) -> None:
    event = Event(
        name="bid_management.package.awarded",
        data={
            "package_id": str(uuid.uuid4()),
            "awarded_bidder_id": str(uuid.uuid4()),
            "awarded_amount": "1.00",
            "currency": "EUR",
        },
        source_module="bid_management",
    )
    await proc_events._create_po_from_bid_award(event)
    assert patched.purchase_orders == []


@pytest.mark.asyncio
async def test_handler_dispatches_detached(monkeypatch: pytest.MonkeyPatch) -> None:
    """``_on_bid_management_awarded`` schedules the worker via _log_failures."""
    calls: list[str] = []

    def _fake_log_failures(coro: Any, *, name: str) -> SimpleNamespace:
        calls.append(name)
        coro.close()  # avoid 'never awaited' warning for the stubbed coroutine
        return SimpleNamespace()

    monkeypatch.setattr(proc_events, "_log_failures", _fake_log_failures)
    await proc_events._on_bid_management_awarded(
        Event(name="bid_management.package.awarded", data={}, source_module="bid_management")
    )
    assert calls == ["procurement.auto_po_from_bid_award"]


# ── Order owner (issue #516) ───────────────────────────────────────────────


def _tender_award(store: _FakeStore, project_id: uuid.UUID) -> Event:
    tender_pkg = TenderPackage(id=uuid.uuid4(), project_id=project_id, name="Concrete works")
    store.tender_packages.append(tender_pkg)
    tender_bid = TenderBid(
        id=uuid.uuid4(),
        package_id=tender_pkg.id,
        company_name="ACME Bau GmbH",
        contact_email="bids@acme.example",
        total_amount="95000.00",
        currency="EUR",
        line_items=[],
    )
    store.tender_bids.append(tender_bid)
    return Event(
        name="tendering.package.awarded",
        data={"package_id": str(tender_pkg.id), "bid_id": str(tender_bid.id)},
        source_module="oe_tendering",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("owner, drafted", [("external", 0), ("ocerp", 1)])
async def test_an_award_drafts_no_order_when_an_external_system_places_the_orders(
    patched: _FakeStore, owner: str, drafted: int
) -> None:
    """The external system raises the order for the award; a local draft would be a second one."""
    project_id = uuid.uuid4()
    patched.settings.append(ProcurementProjectSettings(id=uuid.uuid4(), project_id=project_id, order_owner=owner))
    package, bidder = _seed_bid_award(patched, project_id=project_id)

    await proc_events._create_po_from_bid_award(_bid_award_event(package, bidder))
    assert len(patched.purchase_orders) == drafted

    other_project = uuid.uuid4()
    patched.settings.append(ProcurementProjectSettings(id=uuid.uuid4(), project_id=other_project, order_owner=owner))
    await proc_events._create_po_from_award(_tender_award(patched, other_project))
    assert len(patched.purchase_orders) == 2 * drafted


@pytest.mark.asyncio
async def test_a_project_without_settings_keeps_drafting_award_orders(patched: _FakeStore) -> None:
    """No settings row is the behaviour every project had before the setting existed."""
    project_id = uuid.uuid4()
    await proc_events._create_po_from_award(_tender_award(patched, project_id))
    assert len(patched.purchase_orders) == 1
