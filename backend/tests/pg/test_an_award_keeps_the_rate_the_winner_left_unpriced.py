# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: an award keeps the bill's rate on a line the winner did not price.

The award wrote every winning line that carried a ``unit_rate`` key into the
bill, and a key holding null was written as 0: the estimate for that line was
replaced by nothing at all. A line the bid left out entirely was skipped, but
nobody was told it kept the old rate. Now an unpriced line (no key, null or
empty) keeps the bill's rate, a rate of 0 the bidder actually sent is still
written, and the answer counts the package's lines that kept their rate.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.tendering.service import TenderingService
from tests.pg.tender_award_fixtures import _bid, _bill, _package, _project

pytestmark = pytest.mark.asyncio

ROWS = [
    ("shell", "01", "Shell", "", None),
    ("wall", "01.010", "Wall", "m3", "shell"),
    ("slab", "01.020", "Slab", "m3", "shell"),
    ("roof", "01.030", "Roof", "m2", "shell"),
    ("bonus", "01.040", "Included item", "pcs", "shell"),
]


def _lines(pos) -> list[dict]:
    return [
        {"position_id": str(pos["wall"].id), "unit_rate": "70"},
        # Sent with no price: the portal and the bid form never do this, an
        # import can.
        {"position_id": str(pos["slab"].id), "unit_rate": None},
        # The roof is not in the bid at all.
        # A price of 0 is a price: the bidder includes it at no charge.
        {"position_id": str(pos["bonus"].id), "unit_rate": "0"},
    ]


async def test_an_unpriced_line_keeps_the_bill_rate_and_is_counted(pg_session) -> None:
    project = await _project(pg_session)
    boq, pos = await _bill(pg_session, project, ROWS)
    package = await _package(pg_session, project, boq)
    bid = await _bid(pg_session, package, "Rheinbeton", "700", _lines(pos))

    result = await TenderingService(pg_session).apply_winner(package.id, bid.id)

    assert result["positions_updated"] == 2, "the wall and the priced zero"
    assert result["positions_unpriced"] == 2, "the slab sent without a price and the roof left out"
    for key, expected in (("wall", "70"), ("slab", "50"), ("roof", "50"), ("bonus", "0")):
        await pg_session.refresh(pos[key])
        assert Decimal(pos[key].unit_rate) == Decimal(expected), key


async def test_the_count_is_the_package_scope_not_the_whole_bill(pg_session) -> None:
    project = await _project(pg_session)
    boq, pos = await _bill(pg_session, project, ROWS)
    # The package covers the wall, the slab and the included item, not the roof.
    package = await _package(
        pg_session,
        project,
        boq,
        metadata={"scope_position_ids": [str(pos[k].id) for k in ("wall", "slab", "bonus")]},
    )
    bid = await _bid(pg_session, package, "Rheinbeton", "700", _lines(pos))

    result = await TenderingService(pg_session).apply_winner(package.id, bid.id)

    assert result["positions_unpriced"] == 1, "only the slab: the roof was never asked for"


async def test_a_locked_bill_reports_no_unpriced_lines(pg_session) -> None:
    project = await _project(pg_session)
    boq, pos = await _bill(pg_session, project, ROWS, locked=True)
    package = await _package(pg_session, project, boq)
    bid = await _bid(pg_session, package, "Rheinbeton", "700", _lines(pos))

    result = await TenderingService(pg_session).apply_winner(package.id, bid.id)

    assert result["rates_skipped_reason"] == "boq_locked"
    assert result["positions_unpriced"] == 0, "a locked bill keeps every rate for its own reason"


async def test_a_blank_placeholder_row_is_not_counted_as_unpriced(pg_session) -> None:
    """The bidders were never sent the empty row "Add Position" leaves, so it is no unpriced line."""
    from app.modules.boq.models import Position

    project = await _project(pg_session)
    boq, pos = await _bill(pg_session, project, ROWS)
    blank = Position(
        boq_id=boq.id,
        parent_id=pos["shell"].id,
        ordinal="01.050",
        description="",
        unit="m2",
        quantity="0",
        unit_rate="0",
        total="0",
    )
    pg_session.add(blank)
    await pg_session.flush()
    package = await _package(pg_session, project, boq)
    lines = [{"position_id": str(pos[k].id), "unit_rate": "60"} for k in ("wall", "slab", "roof", "bonus")]
    bid = await _bid(pg_session, package, "Rheinbeton", "2400", lines)

    comparison = await TenderingService(pg_session).compare_bids(package.id)
    coverage = comparison.bid_totals[0]
    assert (coverage["matched_lines"], coverage["total_lines"]) == (4, 4), "the grid says the bid is complete"

    result = await TenderingService(pg_session).apply_winner(package.id, bid.id)

    assert result["positions_updated"] == 4
    assert result["positions_unpriced"] == 0, "the blank row was not in the bill the bidder priced"
