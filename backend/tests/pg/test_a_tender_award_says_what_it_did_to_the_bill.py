# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: an award says what it did to the bill.

The award wrote the winning rates into the bill even when the bill was locked,
so an approved baseline changed behind its approval. It now leaves a locked
bill alone and says so; a bid priced as a lump sum, which has no line rates,
is reported the same way instead of reading as a write-back.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.tendering.service import TenderingService
from tests.pg.tender_award_fixtures import _bid, _bill, _package, _project

pytestmark = pytest.mark.asyncio


async def test_an_award_writes_line_rates_into_an_open_bill(pg_session) -> None:
    project = await _project(pg_session)
    boq, pos = await _bill(pg_session, project, [("wall", "01", "Wall", "m3", None)])
    package = await _package(pg_session, project, boq)
    bid = await _bid(
        pg_session, package, "Rheinbeton", "700", [{"position_id": str(pos["wall"].id), "unit_rate": "70"}]
    )

    result = await TenderingService(pg_session).apply_winner(package.id, bid.id)

    assert result["positions_updated"] == 1
    assert result["rates_skipped_reason"] is None
    await pg_session.refresh(pos["wall"])
    assert Decimal(pos["wall"].unit_rate) == Decimal("70")


async def test_an_award_leaves_a_locked_bill_as_approved(pg_session) -> None:
    project = await _project(pg_session)
    boq, pos = await _bill(pg_session, project, [("wall", "01", "Wall", "m3", None)], locked=True)
    package = await _package(pg_session, project, boq)
    bid = await _bid(
        pg_session, package, "Rheinbeton", "700", [{"position_id": str(pos["wall"].id), "unit_rate": "70"}]
    )

    result = await TenderingService(pg_session).apply_winner(package.id, bid.id)

    assert result["positions_updated"] == 0
    assert result["rates_skipped_reason"] == "boq_locked"
    await pg_session.refresh(pos["wall"])
    assert Decimal(pos["wall"].unit_rate) == Decimal("50"), "a locked bill was rewritten by an award"
    await pg_session.refresh(package)
    assert package.status == "awarded", "the award itself still stands"


async def test_a_lump_sum_award_says_it_had_no_rates_to_write(pg_session) -> None:
    project = await _project(pg_session)
    boq, _pos = await _bill(pg_session, project, [("wall", "01", "Wall", "m3", None)])
    package = await _package(pg_session, project, boq)
    bid = await _bid(pg_session, package, "Rheinbeton", "700", [])

    result = await TenderingService(pg_session).apply_winner(package.id, bid.id)

    assert result["positions_updated"] == 0
    assert result["rates_skipped_reason"] == "no_line_rates"
