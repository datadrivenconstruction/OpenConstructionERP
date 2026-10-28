"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for tender addenda and bid leveling.

Covers:
- ``revision_no`` auto-increments per package (1, 2, ...) across
  consecutive ``create_addendum`` calls.
- ``publish_addendum`` stamps ``published_at`` and the ack pipeline
  appends a bidder entry on first call but is idempotent on the second.
- ``level_bids`` produces:
    * matched lines for bids that quoted all of the reference BOQ,
    * an inflated ``leveled_amount`` for bids that *omitted* a line
      (the omitted line is imputed at the bid's mean unit-rate × reference
      quantity → leveled total > raw total by exactly that penalty).

The service is exercised without a database: the repository is a stub, the
project lookup answers from ``session.get``, and the reference bill is stood
up by replacing ``BOQService`` on its own module (``_build_leveling`` imports
it inside the function body and reads only ``.positions`` off the result).

Two shape notes, because this file was originally written against a spec
rather than against the code, and the shipped module answers the same
questions from a different place:

* Addenda are not their own table. They live in the package ``metadata_``
  JSON store as an append-only revision log, so ``publish_addendum`` and
  ``acknowledge_addendum`` take the package that holds the addendum rather
  than an addendum row id, and they answer with ``AddendumResponse`` models
  rather than ORM instances.
* Leveling is pure computation over the BOQ positions and the bids'
  ``line_items``; it writes nothing back. The per-line classification a
  persisted ``leveling_notes`` column was once imagined to carry is read off
  ``get_leveling_matrix``, which is where the shipped module publishes it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.tendering.schemas import (
    AddendumCreate,
    BidCreate,
    BidLineItem,
    PackageCreate,
)
from app.modules.tendering.service import TenderingService

PROJECT_ID = uuid.uuid4()
PROJECT_CURRENCY = "EUR"


# ── Stub repository + helpers ─────────────────────────────────────────────


class _StubRepo:
    """In-memory stand-in for ``TenderingRepository``.

    Models the minimal contract the service needs for these tests: package
    creation and field updates (which is where addenda are stored) plus bid
    creation and listing.
    """

    def __init__(self) -> None:
        self.packages: dict[uuid.UUID, Any] = {}
        self.bids: dict[uuid.UUID, Any] = {}

    # ── Packages ─────────────────────────────────────────────────────
    async def create_package(self, package: Any) -> Any:
        if getattr(package, "id", None) is None:
            package.id = uuid.uuid4()
        now = datetime.now(UTC)
        package.created_at = now
        package.updated_at = now
        self.packages[package.id] = package
        return package

    async def get_package_by_id(self, package_id: uuid.UUID) -> Any:
        return self.packages.get(package_id)

    async def update_package_fields(
        self,
        package_id: uuid.UUID,
        **fields: Any,
    ) -> None:
        p = self.packages.get(package_id)
        if p:
            for k, v in fields.items():
                setattr(p, k, v)

    # ── Bids ─────────────────────────────────────────────────────────
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

    async def list_bids_for_package(
        self,
        package_id: uuid.UUID,
    ) -> list[Any]:
        return [b for b in self.bids.values() if b.package_id == package_id]


async def _get_project(_model: Any, _project_id: Any) -> Any:
    """Answer ``AsyncSession.get(Project, id)`` with a project of known currency.

    ``_build_leveling`` derives the package's reporting currency from its
    project; giving it a real currency keeps the cross-currency guard on the
    same path it takes in production instead of the "currency unknown" fallback.
    """
    return SimpleNamespace(id=PROJECT_ID, name="Demo project", currency=PROJECT_CURRENCY)


def _make_service() -> TenderingService:
    """Construct a TenderingService bypassing the DB layer."""
    svc = TenderingService.__new__(TenderingService)
    svc.session = SimpleNamespace(get=_get_project)
    svc.repo = _StubRepo()
    return svc


def _reference_position(
    *,
    position_id: str,
    ordinal: str,
    description: str,
    unit: str,
    quantity: Decimal,
    unit_rate: Decimal,
    total: Decimal,
) -> SimpleNamespace:
    """One BOQ position as ``_build_leveling`` reads it."""
    return SimpleNamespace(
        id=position_id,
        ordinal=ordinal,
        description=description,
        unit=unit,
        quantity=quantity,
        unit_rate=unit_rate,
        total=total,
    )


def _install_reference_bill(
    monkeypatch: pytest.MonkeyPatch,
    positions: list[SimpleNamespace],
) -> None:
    """Stand the given positions behind every BOQ read the service makes."""

    class _StubBOQService:
        def __init__(self, session: Any) -> None:
            self.session = session

        async def get_boq_with_positions(self, boq_id: uuid.UUID) -> Any:
            return SimpleNamespace(
                id=boq_id,
                name="Reference bill",
                project_id=PROJECT_ID,
                positions=list(positions),
            )

    monkeypatch.setattr("app.modules.boq.service.BOQService", _StubBOQService)


async def _make_package_with_boq(
    svc: TenderingService,
    monkeypatch: pytest.MonkeyPatch,
    reference_positions: list[SimpleNamespace],
) -> Any:
    """Create a package whose BOQ resolves to the supplied reference lines."""
    _install_reference_bill(monkeypatch, reference_positions)
    return await svc.create_package(
        PackageCreate(
            project_id=PROJECT_ID,
            boq_id=uuid.uuid4(),
            name="Concrete works",
        )
    )


# ── Addendum tests ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_addendum_auto_increment_revision() -> None:
    """Two consecutive create_addendum calls produce revisions 1 and 2."""
    svc = _make_service()
    pkg = await svc.create_package(PackageCreate(project_id=PROJECT_ID, name="Concrete works"))

    first = await svc.create_addendum(
        pkg.id,
        AddendumCreate(title="Clarification 1", body="Updated specs"),
    )
    second = await svc.create_addendum(
        pkg.id,
        AddendumCreate(title="Clarification 2", body="Extra detail"),
    )

    assert first.revision_no == 1
    assert second.revision_no == 2
    assert first.published_at is None  # draft until publish
    assert list(first.acknowledged_by) == []


@pytest.mark.asyncio
async def test_addendum_publish_and_acknowledge_idempotent() -> None:
    """Publish stamps the timestamp; ack appends once and re-ack is a no-op."""
    svc = _make_service()
    pkg = await svc.create_package(PackageCreate(project_id=PROJECT_ID, name="Concrete works"))
    addendum = await svc.create_addendum(
        pkg.id,
        AddendumCreate(title="Spec change", body="Updated rebar grade"),
    )

    # Publish — published_at gets stamped. The package is re-read before each
    # call, mirroring the router, which resolves the package once per request.
    published = await svc.publish_addendum(
        await svc.get_package(pkg.id),
        addendum.id,
        user_id=str(uuid.uuid4()),
    )
    assert published.published_at is not None

    bidder_id = str(uuid.uuid4())
    # First ack lands.
    after_first = await svc.acknowledge_addendum(
        await svc.get_package(pkg.id),
        addendum.id,
        bidder_id,
        user_id=str(uuid.uuid4()),
    )
    assert len(after_first.acknowledged_by) == 1
    entry = after_first.acknowledged_by[0]
    assert entry.bidder_id == bidder_id
    assert entry.acknowledged_at

    # Second ack from the same bidder is a no-op — no duplicate appended.
    after_second = await svc.acknowledge_addendum(
        await svc.get_package(pkg.id),
        addendum.id,
        bidder_id,
        user_id=str(uuid.uuid4()),
    )
    assert len(after_second.acknowledged_by) == 1
    assert after_second.acknowledged_by[0].acknowledged_at == entry.acknowledged_at


# ── Bid leveling tests ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_level_bids_imputes_omitted_line_with_mean_rate_penalty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two bids, three reference lines.

    * Bid A quotes all three lines → leveled total == raw total.
    * Bid B omits line 3 → the line is imputed at Bid B's mean unit-rate
      × line 3's reference quantity. The leveled total must exceed the
      raw total by exactly that penalty.
    """
    svc = _make_service()
    reference_positions = [
        _reference_position(
            position_id="p1",
            ordinal="01.01",
            description="Concrete C30/37",
            unit="m3",
            quantity=Decimal("100"),
            unit_rate=Decimal("120"),
            total=Decimal("12000"),
        ),
        _reference_position(
            position_id="p2",
            ordinal="01.02",
            description="Rebar B500B",
            unit="kg",
            quantity=Decimal("8000"),
            unit_rate=Decimal("1.2"),
            total=Decimal("9600"),
        ),
        _reference_position(
            position_id="p3",
            ordinal="01.03",
            description="Formwork",
            unit="m2",
            quantity=Decimal("500"),
            unit_rate=Decimal("18"),
            total=Decimal("9000"),
        ),
    ]
    pkg = await _make_package_with_boq(svc, monkeypatch, reference_positions)

    # Bid A — quotes every reference line at the reference quantity.
    bid_a = await svc.create_bid(
        pkg.id,
        BidCreate(
            company_name="ACME GmbH",
            total_amount="29800",
            currency="EUR",
            status="submitted",
            line_items=[
                BidLineItem(
                    position_id="p1",
                    description="Concrete C30/37",
                    unit="m3",
                    quantity=100.0,
                    unit_rate=115.0,
                    total=11500.0,
                ),
                BidLineItem(
                    position_id="p2",
                    description="Rebar B500B",
                    unit="kg",
                    quantity=8000.0,
                    unit_rate=1.1,
                    total=8800.0,
                ),
                BidLineItem(
                    position_id="p3",
                    description="Formwork",
                    unit="m2",
                    quantity=500.0,
                    unit_rate=19.0,
                    total=9500.0,
                ),
            ],
        ),
    )

    # Bid B — *omits* line 3 (Formwork). Its mean unit-rate over the two
    # quoted lines is (130 + 1.3) / 2 = 65.65.
    bid_b = await svc.create_bid(
        pkg.id,
        BidCreate(
            company_name="Beta Bau AG",
            total_amount="23400",
            currency="EUR",
            status="submitted",
            line_items=[
                BidLineItem(
                    position_id="p1",
                    description="Concrete C30/37",
                    unit="m3",
                    quantity=100.0,
                    unit_rate=130.0,
                    total=13000.0,
                ),
                BidLineItem(
                    position_id="p2",
                    description="Rebar B500B",
                    unit="kg",
                    quantity=8000.0,
                    unit_rate=1.3,
                    total=10400.0,
                ),
            ],
        ),
    )

    result = await svc.level_bids(pkg.id)
    assert result.package_id == pkg.id
    assert result.bid_count == 2
    assert result.reference_line_count == 3
    # Both bids are quoted in the project currency, so neither is held back
    # from the comparison by the cross-currency guard.
    assert result.currency == PROJECT_CURRENCY
    assert result.excluded_off_currency == 0

    summaries = {s.bid_id: s for s in result.bid_summaries}

    # Bid A — all three lines matched. Leveled == raw.
    a_sum = summaries[str(bid_a.id)]
    assert a_sum.matched_lines == 3
    assert a_sum.imputed_lines == 0
    assert a_sum.scaled_lines == 0
    assert a_sum.leveled_amount == a_sum.raw_amount

    # Bid B — two matched, one imputed.
    b_sum = summaries[str(bid_b.id)]
    assert b_sum.matched_lines == 2
    assert b_sum.imputed_lines == 1
    assert b_sum.scaled_lines == 0

    # Expected imputed penalty:
    # mean_rate = (130 + 1.3) / 2 = 65.65
    # line 3 qty = 500 → imputed_total = 65.65 * 500 = 32825.0
    # raw_total = 13000 + 10400 = 23400
    # leveled_total = 23400 + 32825 = 56225
    expected_penalty = Decimal("65.65") * Decimal("500")
    expected_leveled = Decimal("23400") + expected_penalty
    assert abs(b_sum.leveled_amount - expected_leveled) < Decimal("0.5")
    # And — the load-bearing assertion — leveling makes Bid B more
    # expensive than its raw quote, so a short-quoting bidder cannot
    # silently undercut a complete quote.
    assert b_sum.leveled_amount > b_sum.raw_amount

    # The per-line classification behind those totals is readable on the
    # matrix: two lines Bid B quoted, one the levelling supplied for it, at
    # the bidder's own mean rate against the reference quantity.
    matrix = await svc.get_leveling_matrix(pkg.id)
    cells = [cell for row in matrix.rows for cell in row.cells if cell.bid_id == str(bid_b.id)]
    statuses = [cell.status for cell in cells]
    assert statuses.count("matched") == 2
    assert statuses.count("imputed") == 1

    imputed_cell = next(cell for cell in cells if cell.status == "imputed")
    assert imputed_cell.unit_rate == Decimal("65.65")
    assert imputed_cell.raw_total == 0.0
    assert imputed_cell.leveled_total == float(expected_penalty)
