# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Bid day arithmetic, scope normalisation, suggestions, rules and snapshot immutability."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm.attributes import set_committed_value

from app.core.validation.engine import ValidationContext
from app.modules.bid_day import logic
from app.modules.bid_day.logic import Markups, QuoteData, RowData
from app.modules.bid_day.models import BidDaySnapshot, SnapshotImmutableError, _refuse_snapshot_update
from app.modules.bid_day.validators import (
    ChosenExclusionsResolved,
    MoreThanOneQuote,
    PackageHasQuote,
    QuoteNotStale,
    TotalNearEstimate,
)

D = Decimal


def _q(qid: str, amount: str, *, fx: str = "1", exclusions: list | None = None, vendor: str | None = None) -> QuoteData:
    return QuoteData(id=qid, vendor=vendor or qid, amount=D(amount), fx_rate=D(fx), exclusions=exclusions or [])


def test_adjusted_adds_only_plugged_exclusions_and_converts_currency() -> None:
    q = _q(
        "a",
        "1000",
        fx="1.10",
        exclusions=[
            {"text": "Crane", "status": "plugged", "plug_amount": "250.005"},
            {"text": "Scaffold", "status": "open", "plug_amount": "999"},
            {"text": "Waste", "status": "included", "plug_amount": "50"},
        ],
    )
    assert logic.as_quoted(q) == D("1100.00")
    assert logic.adjusted(q) == D("1350.01")
    assert logic.open_exclusions(q) == 1


def test_clean_exclusions_drops_plug_unless_plugged_and_fixes_status() -> None:
    out = logic.clean_exclusions(["No crane", {"text": "Pumps", "status": "weird", "plug_amount": "5"}, 7])
    assert [x["status"] for x in out] == ["open", "open"]
    assert all(x["plug_amount"] == "0.00" for x in out)
    assert out[0]["id"] == "x1"


def test_row_value_is_chosen_adjusted_else_plug() -> None:
    row = RowData(id="r", name="Concrete", plug=D("50000"), quotes=[_q("a", "48000"), _q("b", "47000")])
    assert logic.row_value(row) == D("50000.00")
    row.chosen_id = "a"
    assert logic.row_value(row) == D("48000.00")


def test_totals_markups_and_snapshot_delta() -> None:
    rows = [
        RowData(id="1", name="Concrete", plug=D("100000"), quotes=[_q("a", "90000")], chosen_id="a"),
        RowData(id="2", name="Steel", plug=D("50000")),
    ]
    t = logic.totals(rows, Markups(D("8"), D("2"), D("5")), last_snapshot_total=D("150000"))
    assert t["direct"] == "140000.00"
    assert t["overhead"] == "11200.00"
    assert t["risk"] == "2800.00"
    assert t["profit"] == "7700.00"  # 5% of 154000
    assert t["bid_total"] == "161700.00"
    assert t["estimate_direct"] == "150000.00"
    assert t["vs_estimate"] == "-10000.00"
    assert t["delta_vs_snapshot"] == "11700.00"


def test_totals_without_snapshot_have_no_delta() -> None:
    t = logic.totals([], Markups())
    assert t["bid_total"] == "0.00" and t["delta_vs_snapshot"] is None


def test_suggestion_picks_lowest_adjusted_not_lowest_quoted() -> None:
    cheap_with_gap = _q("a", "90000", exclusions=[{"status": "plugged", "plug_amount": "15000"}])
    row = RowData(id="r", name="Facade", plug=D("100000"), quotes=[cheap_with_gap, _q("b", "100000"), _q("c", "99000")])
    s = logic.suggest(row)
    assert s is not None
    assert s["quote_id"] == "c"
    assert "competitive" in s["reasons"]
    assert 0 < s["confidence"] <= 0.95


def test_suggestion_confidence_drops_for_single_quote_with_open_exclusions() -> None:
    row = RowData(id="r", name="Roof", plug=D("1"), quotes=[_q("a", "10", exclusions=[{"status": "open"}])])
    s = logic.suggest(row)
    assert s is not None
    assert {"single_quote", "open_exclusions"} <= set(s["reasons"])
    assert s["confidence"] < 0.3
    assert logic.suggest(RowData(id="e", name="Empty", plug=D("0"))) is None


def _ctx(data: dict) -> ValidationContext:
    return ValidationContext(data=data)


@pytest.mark.asyncio
async def test_rules_flag_each_bid_day_risk() -> None:
    now = datetime(2026, 10, 31, 14, 0, tzinfo=UTC)
    data = {
        "now": now,
        "stale_days": 30,
        "direct": "120000",
        "estimate": "100000",
        "deviation_pct_limit": "10",
        "rows": [
            {"id": "r1", "name": "Concrete", "chosen_id": "q1", "quotes": [
                {"id": "q1", "vendor": "A", "received_at": now - timedelta(days=40), "exclusions": [{"status": "open"}]},
            ]},
            {"id": "r2", "name": "Steel", "chosen_id": None, "quotes": []},
        ],
    }  # fmt: skip
    ctx = _ctx(data)
    failed = {}
    for rule in (
        PackageHasQuote(),
        ChosenExclusionsResolved(),
        QuoteNotStale(),
        MoreThanOneQuote(),
        TotalNearEstimate(),
    ):
        failed[rule.rule_id] = [r for r in await rule.validate(ctx) if not r.passed]
    assert [r.element_ref for r in failed["bid_day.package_has_quote"]] == ["r2"]
    assert len(failed["bid_day.chosen_exclusions_resolved"]) == 1
    assert failed["bid_day.quote_not_stale"][0].details["days"] == 40
    assert [r.element_ref for r in failed["bid_day.more_than_one_quote"]] == ["r1"]
    assert failed["bid_day.total_near_estimate"][0].details["pct"] == "20.0"


def _committed_snapshot() -> BidDaySnapshot:
    snap = BidDaySnapshot()
    for key, value in {
        "id": uuid.uuid4(), "board_id": uuid.uuid4(), "project_id": uuid.uuid4(), "tender_id": uuid.uuid4(),
        "bid_total": "100.00", "currency": "EUR", "content_sha256": "x" * 64, "payload": {"rows": []},
        "note": "", "submitted_by": None, "submitted_by_name": "", "pushed_at": None,
    }.items():  # fmt: skip
        set_committed_value(snap, key, value)
    return snap


def test_snapshot_refuses_any_change_but_the_push_mark() -> None:
    snap = _committed_snapshot()
    snap.pushed_at = datetime.now(UTC)
    _refuse_snapshot_update(None, None, snap)
    snap.bid_total = "90.00"
    with pytest.raises(SnapshotImmutableError):
        _refuse_snapshot_update(None, None, snap)
