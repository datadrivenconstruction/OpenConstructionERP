# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Bid day board against PostgreSQL: quotes read from tendering, edits, conflicts, freeze, push."""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.modules.bid_day.models import SnapshotImmutableError
from app.modules.bid_day.schemas import (
    ChoiceUpdate,
    ExclusionIn,
    MarkupUpdate,
    QuoteCreate,
    QuoteUpdate,
    RowCreate,
)
from app.modules.bid_day.service import BidDayService
from app.modules.bid_day.validators import register_bid_day_rules
from tests.pg.tender_award_fixtures import _bid, _bill, _package, _project

pytestmark = pytest.mark.asyncio


async def _board(pg_session):
    register_bid_day_rules()
    project = await _project(pg_session)
    boq, _pos = await _bill(pg_session, project, [("a", "01", "Walls", "m3", None)])
    tender = await _package(pg_session, project, boq)
    await _bid(pg_session, tender, "Alder", "48000", [])
    await _bid(pg_session, tender, "Birch", "51000", [])
    svc = BidDayService(pg_session)
    board = await svc.open_board(tender.id, None)
    return svc, board, tender


async def test_open_reads_existing_bids_once(pg_session) -> None:
    svc, board, tender = await _board(pg_session)
    assert len(board.rows) == 1
    assert sorted(q.vendor for q in board.rows[0].quotes) == ["Alder", "Birch"]
    again = await svc.open_board(tender.id, None)
    assert again.id == board.id and len(again.rows[0].quotes) == 2
    view = await svc.view(board)
    assert view["rows"][0]["suggestion"]["vendor"] == "Alder"
    assert view["currency"] == "EUR"


async def test_edits_recalculate_and_log_the_delta(pg_session) -> None:
    svc, board, _t = await _board(pg_session)
    row = board.rows[0]
    alder = next(q for q in row.quotes if q.vendor == "Alder")
    await svc.choose(board, row.id, ChoiceUpdate(quote_id=alder.id, rev=row.rev), None)
    await svc.set_markups(board, MarkupUpdate(overhead_pct="10", rev=board.markup_rev), None)
    assert svc.compute(board, None)["bid_total"] == "52800.00"

    await svc.update_quote(board, alder.id, QuoteUpdate(amount="40000", rev=alder.rev), None)
    view = await svc.view(board)
    assert view["totals"]["bid_total"] == "44000.00"
    assert view["events"][0].delta == "-8800.00"
    assert "cut by 8000.00" in view["events"][0].message

    await svc.add_quote(
        board, row.id,
        QuoteCreate(vendor="Cedar", amount="39000", channel="phone", exclusions=[ExclusionIn(text="No crane")]),
        None,
    )  # fmt: skip
    view = await svc.view(board)
    cedar = next(q for q in view["rows"][0]["quotes"] if q["vendor"] == "Cedar")
    assert cedar["open_exclusions"] == 1 and cedar["source"] == "late"


async def test_stale_revision_is_a_visible_conflict(pg_session) -> None:
    svc, board, _t = await _board(pg_session)
    q = board.rows[0].quotes[0]
    stale = q.rev
    await svc.update_quote(board, q.id, QuoteUpdate(amount="47000", rev=stale), None)
    with pytest.raises(HTTPException) as exc:
        await svc.update_quote(board, q.id, QuoteUpdate(amount="46000", rev=stale), None)
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "stale_revision"
    assert q.amount == "47000.00"


async def test_freeze_blocks_on_open_exclusions_then_stores_an_immutable_snapshot(pg_session) -> None:
    svc, board, _t = await _board(pg_session)
    row = board.rows[0]
    q = row.quotes[0]
    await svc.update_quote(board, q.id, QuoteUpdate(exclusions=[ExclusionIn(text="Pumping")], rev=q.rev), None)
    await svc.choose(board, row.id, ChoiceUpdate(quote_id=q.id), None)
    with pytest.raises(HTTPException) as exc:
        await svc.freeze(board, "", None)
    assert exc.value.detail["code"] == "validation_errors"

    await svc.update_quote(
        board, q.id, QuoteUpdate(exclusions=[ExclusionIn(text="Pumping", status="plugged", plug_amount="1500")]), None
    )
    snap = await svc.freeze(board, "Submitted by portal", None)
    assert board.status == "frozen"
    assert Decimal(snap.bid_total) == Decimal(q.amount) + Decimal("1500")
    assert snap.payload["rows"][0]["chosen"]["adjusted"] == snap.bid_total

    with pytest.raises(HTTPException) as frozen:
        await svc.add_row(board, RowCreate(name="Late scope"), None)
    assert frozen.value.detail["code"] == "board_frozen"

    snap.bid_total = "1.00"
    with pytest.raises(SnapshotImmutableError):
        await pg_session.flush()
    await pg_session.rollback()


async def test_push_spreads_the_chosen_quote_over_package_positions(pg_session) -> None:
    from app.modules.bid_management.models import BidPackage, BidPackageLineItem

    register_bid_day_rules()
    project = await _project(pg_session)
    boq, pos = await _bill(pg_session, project, [("a", "01", "Walls", "m3", None), ("b", "02", "Slabs", "m2", None)])
    tender = await _package(pg_session, project, boq)
    pkg = BidPackage(project_id=project.id, tender_id=tender.id, code=f"BP-{tender.id.hex[:6]}", title="Concrete",
                     currency="EUR", total_budget_estimate=Decimal("1000"))  # fmt: skip
    pg_session.add(pkg)
    await pg_session.flush()
    for p in pos.values():
        pg_session.add(BidPackageLineItem(package_id=pkg.id, description=p.description, boq_position_id=p.id))
    await pg_session.flush()

    svc = BidDayService(pg_session)
    board = await svc.open_board(tender.id, None)
    row = board.rows[0]
    assert row.plug_amount == "1000.00"
    await svc.add_quote(board, row.id, QuoteCreate(vendor="Oak", amount="1201", channel="email"), None)
    await svc.choose(board, row.id, ChoiceUpdate(quote_id=row.quotes[0].id), None)
    snap = await svc.freeze(board, "", None)

    plan = await svc.push_to_estimate(board, snap, dry_run=True)
    assert not plan["applied"]
    assert sum(Decimal(line["new_total"]) for line in plan["lines"]) == Decimal("1201.00")
    done = await svc.push_to_estimate(board, snap, dry_run=False)
    assert done["applied"] and snap.pushed_at is not None
    assert sorted(p.total for p in pos.values()) == ["600.50", "600.50"]
