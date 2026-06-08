"""Unit tests for integrated 5D estimating suite style bid leveling + addendum tracking.

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

SKIP STATUS (v4.3): This whole test file targets an integrated 5D estimating
suite style addendum + bid-leveling feature that DOES NOT YET EXIST in
``app.modules.tendering``. The current module ships ``PackageCreate``,
``BidCreate``, ``BidLineItem`` etc. but no ``Addendum`` model, no
``AddendumCreate`` schema, no ``create_addendum`` / ``publish_addendum``
/ ``acknowledge_addendum`` / ``level_bids`` service methods, and no
``revision_no`` / ``acknowledged_by`` / ``leveled_amount`` /
``leveling_notes`` fields on the existing ORM models.

The test was written test-first against the spec; the implementation
is in the v4.3 tendering backlog. Re-enable when:
    1. ``app.modules.tendering.models.Addendum`` + columns
       ``revision_no, published_at, acknowledged_by`` ship,
    2. ``TenderingService.create_addendum/publish_addendum/
       acknowledge_addendum/level_bids`` are implemented,
    3. ``AddendumCreate`` is exported from
       ``app.modules.tendering.schemas``,
    4. ``TenderBid.leveled_amount`` + ``leveling_notes`` columns ship.

Tracked in v4.3 backlog ("addendum + bid leveling").
"""

from __future__ import annotations

import json  # noqa: F401  -- referenced by skipped test bodies below
import uuid
from datetime import UTC, datetime  # noqa: F401
from decimal import Decimal  # noqa: F401
from types import SimpleNamespace  # noqa: F401
from typing import Any  # noqa: F401

import pytest

# SKIP: addendum + leveling feature not implemented (see module docstring).
# Re-enable when the v4.3 tendering backlog items above are done.
pytestmark = pytest.mark.skip(
    reason=(
        "addendum + bid leveling not yet implemented in "
        "app.modules.tendering (AddendumCreate / create_addendum / "
        "level_bids missing). Tracked in v4.3 backlog."
    ),
)

# The imports below intentionally reference symbols that don't exist
# yet — they are kept verbatim so this file becomes valid the moment
# the feature ships. Wrapped in ``try`` so collection doesn't crash.
try:  # pragma: no cover - feature-gated import
    from app.modules.tendering.schemas import (  # type: ignore[attr-defined]
        AddendumCreate,
        BidCreate,
        BidLineItem,
        PackageCreate,
    )
    from app.modules.tendering.service import TenderingService
except ImportError:  # pragma: no cover - expected on current main
    AddendumCreate = BidCreate = BidLineItem = PackageCreate = None  # type: ignore[assignment,misc]
    TenderingService = None  # type: ignore[assignment,misc]


PROJECT_ID = uuid.uuid4()


# ── Stub repository + helpers ─────────────────────────────────────────────


class _StubRepo:
    """In-memory stand-in for ``TenderingRepository``.

    Models the minimal contract the service needs: packages, bids, and
    addenda — including the per-package ``revision_no`` max query so the
    auto-increment path is exercised end-to-end.
    """

    def __init__(self) -> None:
        self.packages: dict[uuid.UUID, Any] = {}
        self.bids: dict[uuid.UUID, Any] = {}
        self.addenda: dict[uuid.UUID, Any] = {}

    # ── Packages ─────────────────────────────────────────────────────
    async def create_package(self, package: Any) -> Any:
        if getattr(package, "id", None) is None:
            package.id = uuid.uuid4()
        now = datetime.now(UTC)
        package.created_at = now
        package.updated_at = now
        if not hasattr(package, "bids"):
            package.bids = []
        if not hasattr(package, "addenda"):
            package.addenda = []
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
        if not hasattr(bid, "leveled_amount"):
            bid.leveled_amount = None
        if not hasattr(bid, "leveling_notes"):
            bid.leveling_notes = None
        self.bids[bid.id] = bid
        return bid

    async def get_bid_by_id(self, bid_id: uuid.UUID) -> Any:
        return self.bids.get(bid_id)

    async def list_bids_for_package(
        self,
        package_id: uuid.UUID,
    ) -> list[Any]:
        return [b for b in self.bids.values() if b.package_id == package_id]

    async def update_bid_fields(
        self,
        bid_id: uuid.UUID,
        **fields: Any,
    ) -> None:
        b = self.bids.get(bid_id)
        if b:
            for k, v in fields.items():
                setattr(b, k, v)

    # ── Addenda ──────────────────────────────────────────────────────
    async def get_addendum_by_id(self, addendum_id: uuid.UUID) -> Any:
        return self.addenda.get(addendum_id)

    async def list_addenda_for_package(
        self,
        package_id: uuid.UUID,
    ) -> list[Any]:
        return sorted(
            (a for a in self.addenda.values() if a.package_id == package_id),
            key=lambda a: a.revision_no,
        )

    async def get_max_revision_no(self, package_id: uuid.UUID) -> int:
        rows = [a.revision_no for a in self.addenda.values() if a.package_id == package_id]
        return max(rows) if rows else 0

    async def create_addendum(self, addendum: Any) -> Any:
        if getattr(addendum, "id", None) is None:
            addendum.id = uuid.uuid4()
        now = datetime.now(UTC)
        addendum.created_at = now
        addendum.updated_at = now
        self.addenda[addendum.id] = addendum
        return addendum

    async def update_addendum_fields(
        self,
        addendum_id: uuid.UUID,
        **fields: Any,
    ) -> None:
        a = self.addenda.get(addendum_id)
        if a:
            for k, v in fields.items():
                setattr(a, k, v)


def _make_service() -> TenderingService:
    """Construct a TenderingService bypassing the DB layer."""
    svc = TenderingService.__new__(TenderingService)
    svc.session = SimpleNamespace()
    svc.repo = _StubRepo()
    return svc


async def _make_package_with_boq(
    svc: TenderingService,
    reference_lines: list[dict],
) -> Any:
    """Create a package and stub ``_load_reference_lines`` to return the
    supplied lines — bypasses the real BOQ service so leveling is testable
    in isolation.
    """
    pkg = await svc.create_package(
        PackageCreate(
            project_id=PROJECT_ID,
            boq_id=uuid.uuid4(),
            name="Concrete works",
        )
    )

    async def _stub_lines(package: Any) -> list[dict]:  # noqa: ARG001
        return reference_lines

    svc._load_reference_lines = _stub_lines  # type: ignore[assignment]
    return pkg


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

    # Publish — published_at gets stamped.
    published = await svc.publish_addendum(addendum.id, user_id=str(uuid.uuid4()))
    assert published.published_at is not None

    bidder_id = uuid.uuid4()
    # First ack lands.
    after_first = await svc.acknowledge_addendum(
        addendum.id,
        bidder_id,
        user_id=str(uuid.uuid4()),
    )
    assert len(after_first.acknowledged_by) == 1
    entry = after_first.acknowledged_by[0]
    assert str(entry["bidder_id"]) == str(bidder_id)
    assert "acknowledged_at" in entry

    # Second ack from the same bidder is a no-op — no duplicate appended.
    after_second = await svc.acknowledge_addendum(
        addendum.id,
        bidder_id,
        user_id=str(uuid.uuid4()),
    )
    assert len(after_second.acknowledged_by) == 1


# ── Bid leveling tests ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_level_bids_imputes_omitted_line_with_mean_rate_penalty() -> None:
    """Two bids, three reference lines.

    * Bid A quotes all three lines → leveled total == raw total.
    * Bid B omits line 3 → the line is imputed at Bid B's mean unit-rate
      × line 3's reference quantity. The leveled total must exceed the
      raw total by exactly that penalty.
    """
    svc = _make_service()
    reference_lines: list[dict] = [
        {
            "position_id": "p1",
            "line_code": "01.01",
            "description": "Concrete C30/37",
            "unit": "m3",
            "quantity": Decimal("100"),
            "unit_rate": Decimal("120"),
            "total": Decimal("12000"),
        },
        {
            "position_id": "p2",
            "line_code": "01.02",
            "description": "Rebar B500B",
            "unit": "kg",
            "quantity": Decimal("8000"),
            "unit_rate": Decimal("1.2"),
            "total": Decimal("9600"),
        },
        {
            "position_id": "p3",
            "line_code": "01.03",
            "description": "Formwork",
            "unit": "m2",
            "quantity": Decimal("500"),
            "unit_rate": Decimal("18"),
            "total": Decimal("9000"),
        },
    ]
    pkg = await _make_package_with_boq(svc, reference_lines)

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
    assert result["package_id"] == str(pkg.id)
    assert result["bid_count"] == 2
    assert result["reference_line_count"] == 3

    summaries = {s["bid_id"]: s for s in result["bid_summaries"]}

    # Bid A — all three lines matched. Leveled == raw.
    a_sum = summaries[str(bid_a.id)]
    assert a_sum["matched_lines"] == 3
    assert a_sum["imputed_lines"] == 0
    assert a_sum["scaled_lines"] == 0
    assert a_sum["leveled_amount"] == a_sum["raw_amount"]

    # Bid B — two matched, one imputed.
    b_sum = summaries[str(bid_b.id)]
    assert b_sum["matched_lines"] == 2
    assert b_sum["imputed_lines"] == 1
    assert b_sum["scaled_lines"] == 0

    # Expected imputed penalty:
    # mean_rate = (130 + 1.3) / 2 = 65.65
    # line 3 qty = 500 → imputed_total = 65.65 * 500 = 32825.0
    # raw_total = 13000 + 10400 = 23400
    # leveled_total = 23400 + 32825 = 56225
    expected_penalty = Decimal("65.65") * Decimal("500")
    expected_leveled = Decimal("23400") + expected_penalty
    assert abs(Decimal(str(b_sum["leveled_amount"])) - expected_leveled) < Decimal("0.5")
    # And — the load-bearing assertion — leveling makes Bid B more
    # expensive than its raw quote, so a short-quoting bidder cannot
    # silently undercut a complete quote.
    assert b_sum["leveled_amount"] > b_sum["raw_amount"]

    # Persistence: leveled_amount + leveling_notes are written to each bid.
    refreshed_b = await svc.repo.get_bid_by_id(bid_b.id)
    assert refreshed_b.leveled_amount is not None
    assert refreshed_b.leveling_notes is not None
    notes = json.loads(refreshed_b.leveling_notes)
    statuses = [entry["status"] for entry in notes]
    assert statuses.count("matched") == 2
    assert statuses.count("imputed") == 1
