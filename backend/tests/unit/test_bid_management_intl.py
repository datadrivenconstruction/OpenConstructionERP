"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠International robustness tests for Bid Management comparison helpers.

Covers the additive, database-free helpers that make bid comparison safe and
clear for a worldwide audience:

    * compute_price_spread - min / median / max spread in one currency.
    * normalize_bids_for_comparison - index every bid against the lowest.
    * flag_abnormally_low_bids - abnormally-low-tender screen vs the average.
    * compute_bid_coverage - which scope lines a bid priced, and the gap.
    * explain_award_recommendation - numbers-first award rationale.
    * explain_bid_concept - one-line plain-language concept definitions.

The focus is edge cases (empty, single bid, zero base, negative amounts,
mixed currencies) and currency safety (never blend different currency codes).
These helpers are pure, so no database or event bus is needed.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.bid_management.service import (
    compute_bid_coverage,
    compute_price_spread,
    explain_award_recommendation,
    explain_bid_concept,
    flag_abnormally_low_bids,
    normalize_bids_for_comparison,
)


def _sub(total: str, currency: str = "EUR", bidder_id: Any = None, sid: Any = None) -> Any:
    return SimpleNamespace(
        id=sid or uuid.uuid4(),
        bidder_id=bidder_id or uuid.uuid4(),
        total_amount=Decimal(total),
        currency=currency,
    )


def _pkg_line(line_id: uuid.UUID, code: str = "01", mandatory: bool = True) -> Any:
    return SimpleNamespace(id=line_id, code=code, is_mandatory=mandatory)


def _sub_line(line_item_id: uuid.UUID, unit_price: str, qty: str = "1") -> Any:
    return SimpleNamespace(
        line_item_id=line_item_id,
        unit_price=Decimal(unit_price),
        quantity_priced=Decimal(qty),
        total_price=Decimal(unit_price) * Decimal(qty),
    )


# ── compute_price_spread ──────────────────────────────────────────────────


def test_price_spread_basic_odd_count() -> None:
    subs = [_sub("100"), _sub("200"), _sub("150")]
    out = compute_price_spread(subs)
    assert out["currency"] == "EUR"
    assert out["count"] == 3
    assert out["min"] == Decimal("100.00")
    assert out["median"] == Decimal("150.00")
    assert out["max"] == Decimal("200.00")
    assert out["spread"] == Decimal("100.00")
    assert out["spread_pct"] == Decimal("100.00")
    assert out["mixed_currency"] is False


def test_price_spread_even_count_median_is_midpoint() -> None:
    subs = [_sub("100"), _sub("200"), _sub("300"), _sub("400")]
    out = compute_price_spread(subs)
    # median of 100,200,300,400 = (200+300)/2 = 250
    assert out["median"] == Decimal("250.00")


def test_price_spread_empty_returns_none_fields() -> None:
    out = compute_price_spread([])
    assert out["count"] == 0
    assert out["min"] is None
    assert out["median"] is None
    assert out["max"] is None
    assert out["spread"] is None
    assert out["spread_pct"] is None


def test_price_spread_single_bid_zero_spread() -> None:
    out = compute_price_spread([_sub("500")])
    assert out["count"] == 1
    assert out["min"] == out["max"] == out["median"] == Decimal("500.00")
    assert out["spread"] == Decimal("0.00")
    assert out["spread_pct"] == Decimal("0.00")


def test_price_spread_never_blends_currencies() -> None:
    # Three EUR, one JPY - JPY is excluded from the maths, counted separately.
    subs = [_sub("100", "EUR"), _sub("200", "EUR"), _sub("150", "EUR"), _sub("99999", "JPY")]
    out = compute_price_spread(subs)
    assert out["currency"] == "EUR"
    assert out["count"] == 3
    assert out["max"] == Decimal("200.00")  # the JPY 99999 never leaks in
    assert out["excluded_off_currency"] == 1
    assert out["mixed_currency"] is True


def test_price_spread_skips_zero_totals() -> None:
    subs = [_sub("100"), _sub("0"), _sub("300")]
    out = compute_price_spread(subs)
    assert out["count"] == 2
    assert out["min"] == Decimal("100.00")
    assert out["max"] == Decimal("300.00")


def test_price_spread_rejects_negative_total() -> None:
    with pytest.raises(ValueError, match="negative"):
        compute_price_spread([_sub("100"), _sub("-50")])


# ── normalize_bids_for_comparison ─────────────────────────────────────────


def test_normalize_indexes_against_lowest() -> None:
    subs = [_sub("100"), _sub("150"), _sub("200")]
    out = normalize_bids_for_comparison(subs)
    assert out["lowest"] == Decimal("100.00")
    assert out["count"] == 3
    # Sorted cheapest first.
    first = out["rows"][0]
    assert first["total_amount"] == Decimal("100.00")
    assert first["index_vs_lowest"] == Decimal("100.00")
    assert first["pct_above_lowest"] == Decimal("0.00")
    last = out["rows"][-1]
    assert last["total_amount"] == Decimal("200.00")
    assert last["index_vs_lowest"] == Decimal("200.00")
    assert last["pct_above_lowest"] == Decimal("100.00")


def test_normalize_empty_returns_no_rows() -> None:
    out = normalize_bids_for_comparison([])
    assert out["count"] == 0
    assert out["lowest"] is None
    assert out["rows"] == []


def test_normalize_excludes_off_currency() -> None:
    subs = [_sub("100", "USD"), _sub("120", "USD"), _sub("5", "GBP")]
    out = normalize_bids_for_comparison(subs)
    assert out["currency"] == "USD"
    assert out["count"] == 2
    assert out["excluded_off_currency"] == 1
    assert out["mixed_currency"] is True


def test_normalize_single_bid_index_100() -> None:
    out = normalize_bids_for_comparison([_sub("777")])
    assert out["count"] == 1
    assert out["rows"][0]["index_vs_lowest"] == Decimal("100.00")
    assert out["rows"][0]["amount_above_lowest"] == Decimal("0.00")


# ── flag_abnormally_low_bids ──────────────────────────────────────────────


def test_abnormally_low_flags_clear_lowballer() -> None:
    # Average of 100,110,105,108,40 = 92.6; 15% below = 78.71. Only 40 qualifies.
    lowballer = uuid.uuid4()
    subs = [
        _sub("100"),
        _sub("110"),
        _sub("105"),
        _sub("108"),
        _sub("40", bidder_id=lowballer),
    ]
    out = flag_abnormally_low_bids(subs, threshold_pct=Decimal("15"))
    flagged_ids = {row["bidder_id"] for row in out["flagged"]}
    assert lowballer in flagged_ids
    assert len(out["flagged"]) == 1
    assert out["average"] is not None
    assert out["threshold_amount"] is not None
    # pct_below_average is a positive shortfall figure.
    assert out["flagged"][0]["pct_below_average"] > Decimal("0")


def test_abnormally_low_none_when_field_is_tight() -> None:
    subs = [_sub("100"), _sub("102"), _sub("98"), _sub("101")]
    out = flag_abnormally_low_bids(subs, threshold_pct=Decimal("15"))
    assert out["flagged"] == []


def test_abnormally_low_single_bid_no_field() -> None:
    out = flag_abnormally_low_bids([_sub("100")])
    assert out["count"] == 1
    assert out["flagged"] == []
    assert out["average"] is None


def test_abnormally_low_empty() -> None:
    out = flag_abnormally_low_bids([])
    assert out["count"] == 0
    assert out["flagged"] == []


def test_abnormally_low_rejects_negative_threshold() -> None:
    with pytest.raises(ValueError, match="threshold_pct"):
        flag_abnormally_low_bids([_sub("100"), _sub("200")], threshold_pct=Decimal("-5"))


def test_abnormally_low_rejects_negative_total() -> None:
    with pytest.raises(ValueError, match="negative"):
        flag_abnormally_low_bids([_sub("100"), _sub("-1")])


def test_abnormally_low_currency_isolated() -> None:
    # The tiny GBP bid must not drag the EUR average down; it is excluded.
    subs = [_sub("100", "EUR"), _sub("110", "EUR"), _sub("1", "GBP")]
    out = flag_abnormally_low_bids(subs, threshold_pct=Decimal("15"))
    assert out["currency"] == "EUR"
    assert out["excluded_off_currency"] == 1
    assert out["flagged"] == []  # 100 and 110 are close, nothing abnormal


# ── compute_bid_coverage ──────────────────────────────────────────────────


def test_coverage_full() -> None:
    l1, l2 = uuid.uuid4(), uuid.uuid4()
    pkg = [_pkg_line(l1, "A"), _pkg_line(l2, "B")]
    sub = [_sub_line(l1, "10"), _sub_line(l2, "20")]
    out = compute_bid_coverage(pkg, sub)
    assert out["total_lines"] == 2
    assert out["priced_lines"] == 2
    assert out["coverage_pct"] == Decimal("100.00")
    assert out["missing_line_codes"] == []
    assert out["mandatory_gap"] is False


def test_coverage_partial_reports_gap() -> None:
    l1, l2, l3, l4 = (uuid.uuid4() for _ in range(4))
    pkg = [_pkg_line(l1, "A"), _pkg_line(l2, "B"), _pkg_line(l3, "C"), _pkg_line(l4, "D")]
    sub = [_sub_line(l1, "10"), _sub_line(l3, "30")]  # priced 2 of 4
    out = compute_bid_coverage(pkg, sub)
    assert out["priced_lines"] == 2
    assert out["coverage_pct"] == Decimal("50.00")
    assert set(out["missing_line_codes"]) == {"B", "D"}
    assert out["mandatory_gap"] is True  # B and D are mandatory by default


def test_coverage_optional_gap_not_mandatory() -> None:
    l1, l2 = uuid.uuid4(), uuid.uuid4()
    pkg = [_pkg_line(l1, "A", mandatory=True), _pkg_line(l2, "B", mandatory=False)]
    sub = [_sub_line(l1, "10")]  # B (optional) left blank
    out = compute_bid_coverage(pkg, sub)
    assert out["coverage_pct"] == Decimal("50.00")
    assert out["missing_line_codes"] == ["B"]
    assert out["mandatory_gap"] is False


def test_coverage_zero_priced_lines_ignored() -> None:
    l1, l2 = uuid.uuid4(), uuid.uuid4()
    pkg = [_pkg_line(l1, "A"), _pkg_line(l2, "B")]
    # l2 present but priced at zero -> counts as not priced.
    sub = [_sub_line(l1, "10"), _sub_line(l2, "0")]
    out = compute_bid_coverage(pkg, sub)
    assert out["priced_lines"] == 1
    assert out["missing_line_codes"] == ["B"]


def test_coverage_empty_package_is_full() -> None:
    out = compute_bid_coverage([], [])
    assert out["total_lines"] == 0
    assert out["coverage_pct"] == Decimal("100.00")
    assert out["missing_line_codes"] == []
    assert out["mandatory_gap"] is False


# ── explain_award_recommendation ──────────────────────────────────────────


def _lev(bidder_id: uuid.UUID, score: str, normalized: str, rank: int) -> Any:
    return SimpleNamespace(
        bidder_id=bidder_id,
        total_score=Decimal(score),
        normalized_total=Decimal(normalized),
        rank=rank,
    )


def test_explain_award_numbers_and_gap() -> None:
    b1, b2 = uuid.uuid4(), uuid.uuid4()
    winner = SimpleNamespace(id=b1, company_name="Alpha")
    levelings = [
        _lev(b1, "95", "1000", 1),
        _lev(b2, "80", "1200", 2),
    ]
    bidders = [winner, SimpleNamespace(id=b2, company_name="Beta")]
    out = explain_award_recommendation(winner, levelings, bidders, currency="eur")
    assert out["bidder_id"] == b1
    assert out["company_name"] == "Alpha"
    assert out["rank"] == 1
    assert out["field_size"] == 2
    assert out["normalized_total"] == Decimal("1000.00")
    assert out["gap_to_next"] == Decimal("200.00")  # 1200 - 1000
    assert out["currency"] == "EUR"
    assert "Alpha" in out["summary"]
    assert "rank 1 of 2" in out["summary"]


def test_explain_award_no_bidder() -> None:
    out = explain_award_recommendation(None, [], [])
    assert out["bidder_id"] is None
    assert out["rank"] is None
    assert "No bid" in out["summary"]


def test_explain_award_single_bid_no_next() -> None:
    b1 = uuid.uuid4()
    winner = SimpleNamespace(id=b1, company_name="Solo")
    levelings = [_lev(b1, "90", "500", 1)]
    out = explain_award_recommendation(winner, levelings, [winner])
    assert out["gap_to_next"] is None
    assert out["pct_ahead_of_next"] is None
    assert out["rank"] == 1


# ── explain_bid_concept ───────────────────────────────────────────────────


def test_explain_concept_known() -> None:
    text = explain_bid_concept("price_spread")
    assert isinstance(text, str)
    assert len(text) > 0
    assert "spread" in text.lower()


def test_explain_concept_case_insensitive() -> None:
    assert explain_bid_concept("Bid_Leveling") == explain_bid_concept("bid_leveling")


@pytest.mark.parametrize(
    "concept",
    [
        "bid_leveling",
        "coverage",
        "coverage_gap",
        "price_spread",
        "abnormally_low",
        "outlier",
        "normalized_comparison",
    ],
)
def test_explain_concept_all_known(concept: str) -> None:
    assert len(explain_bid_concept(concept)) > 0


def test_explain_concept_unknown_raises() -> None:
    with pytest.raises(ValueError, match="unknown bid concept"):
        explain_bid_concept("does_not_exist")


def test_explain_concept_no_em_dash_or_smart_quotes() -> None:
    # World-facing text must stay plain ASCII punctuation.
    banned = ["—", "–", "‘", "’", "“", "”"]
    for concept in (
        "bid_leveling",
        "coverage",
        "coverage_gap",
        "price_spread",
        "abnormally_low",
        "outlier",
        "normalized_comparison",
    ):
        text = explain_bid_concept(concept)
        for ch in banned:
            assert ch not in text
