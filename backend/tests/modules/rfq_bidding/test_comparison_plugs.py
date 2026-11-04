# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Plugs for scope a quote left out, applied by the RFQ comparison.

A quote that omits a line looks cheapest. When the RFQ allows partial quotes the
comparison prices the gap with the shared bid-leveling plug rule, ranks on the
plugged total, and keeps the raw total beside it. Pure payloads, no database.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from app.core.validation.engine import ValidationContext
from app.modules.rfq_bidding import comparison as cmp
from app.modules.rfq_bidding import validators as checks


def _lines(*amounts: str) -> list[dict[str, Any]]:
    return [
        {
            "id": f"line-{i}",
            "line_no": i,
            "code": f"A{i}",
            "description": f"Item {i}",
            "unit": "m2",
            "quantity": "10",
            "is_optional": False,
        }
        for i, _ in enumerate(amounts, start=1)
    ]


def _bid(bid_id: str, prices: dict[int, str | None], **extra: Any) -> dict[str, Any]:
    """A quote with one priced row per entry; ``None`` marks an excluded row."""
    rows = []
    total = Decimal("0")
    for n, amount in prices.items():
        rows.append(
            {
                "id": f"{bid_id}-{n}",
                "rfq_line_id": f"line-{n}",
                "unit": "m2",
                "amount": amount or "0",
                "is_excluded": amount is None,
            }
        )
        total += Decimal(amount or "0")
    base: dict[str, Any] = {
        "id": bid_id,
        "bidder_contact_id": bid_id,
        "bid_amount": str(total),
        "currency_code": "EUR",
        "status": "received",
        "lines": rows,
        "adjustments": [],
    }
    base.update(extra)
    return base


def _rfq(bids: list[dict[str, Any]], *, n_lines: int = 3, full: bool = False, **extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "currency_code": "EUR",
        "evaluation_method": "lowest_price",
        "technical_weight": "0",
        "require_full_scope": full,
        "as_of": "2026-07-10",
        "lines": _lines(*["x"] * n_lines),
        "bids": bids,
    }
    base.update(extra)
    return base


def test_omitted_line_changes_the_plugged_rank() -> None:
    """The quote that skipped line 3 is cheapest raw, but not once plugged."""
    bids = [
        _bid("a", {1: "100", 2: "100"}),  # skips line 3 -> raw 200
        _bid("b", {1: "100", 2: "100", 3: "100"}),  # 300
        _bid("c", {1: "110", 2: "110", 3: "130"}),  # 350
    ]
    result = cmp.compare(_rfq(bids))
    a = result.get("a")
    assert a is not None
    assert a.raw_total == Decimal("200")
    assert a.plug_total == Decimal("115.00")  # median of 100 and 130 is their mean
    assert a.plugged_total == Decimal("315.00")
    assert a.plugs_applied is True
    assert a.plug_sources[0]["source"] == cmp.SOURCE_MEDIAN_OF_2
    assert cmp.NOTE_PLUGGED in a.notes
    assert [q.bid_id for q in result.ranked] == ["b", "a", "c"]
    assert result.recommended_bid_id == "b"


def test_three_other_quotes_give_a_plain_median() -> None:
    bids = [
        _bid("a", {1: "100"}),
        _bid("b", {1: "100", 2: "10"}),
        _bid("c", {1: "100", 2: "20"}),
        _bid("d", {1: "100", 2: "90"}),
    ]
    result = cmp.compare(_rfq(bids, n_lines=2))
    plug = result.get("a").plug_sources[0]  # type: ignore[union-attr]
    assert plug["source"] == "median"
    assert plug["amount"] == "20.00"


def test_full_scope_rfq_still_excludes_and_does_not_rank_on_plugs() -> None:
    bids = [_bid("a", {1: "100", 2: "100"}), _bid("b", {1: "100", 2: "100", 3: "100"})]
    result = cmp.compare(_rfq(bids, full=True))
    a = result.get("a")
    assert a is not None
    assert cmp.REASON_SCOPE_NOT_COVERED in a.reasons
    assert a.plugs_applied is False
    # Informational only: the plug is shown, the ranked amount is not touched.
    assert a.plug_total == Decimal("100.00")
    assert a.normalised_amount is None


def test_estimate_rate_stands_in_when_fewer_than_two_others_priced_the_line() -> None:
    rfq = _rfq([_bid("a", {1: "100"}), _bid("b", {1: "100", 2: "50"})], n_lines=2)
    rfq["lines"][1]["estimate_rate"] = "7"
    plug = cmp.compare(rfq).get("a").plug_sources[0]  # type: ignore[union-attr]
    assert plug["source"] == "estimate"
    assert plug["amount"] == "70.00"  # 7 x quantity 10


def test_single_other_quote_is_labelled_single_bid() -> None:
    plug = (
        cmp.compare(_rfq([_bid("a", {1: "100"}), _bid("b", {1: "100", 2: "50"})], n_lines=2)).get("a").plug_sources[0]
    )  # type: ignore[union-attr]
    assert plug["source"] == "single_bid"
    assert plug["amount"] == "50.00"


def test_nothing_to_plug_from_is_flagged_not_hidden() -> None:
    result = cmp.compare(_rfq([_bid("a", {1: "100"})], n_lines=2))
    a = result.get("a")
    assert a is not None
    assert a.plug_sources[0]["source"] == "none"
    assert a.plug_total == Decimal("0")
    assert cmp.NOTE_GAP_NOT_PLUGGABLE in a.notes


def test_line_priced_at_zero_on_purpose_is_not_plugged() -> None:
    bids = [
        _bid("a", {1: "100", 2: "0"}),  # line 2 deliberately free
        _bid("b", {1: "100", 2: "40"}),
        _bid("c", {1: "100", 2: "60"}),
    ]
    a = cmp.compare(_rfq(bids, n_lines=2)).get("a")
    assert a is not None
    assert a.plug_sources == ()
    assert a.plug_total == Decimal("0")


def test_credit_line_is_not_plugged() -> None:
    bids = [
        _bid("a", {1: "100", 2: "-20"}),
        _bid("b", {1: "100", 2: "40"}),
        _bid("c", {1: "100", 2: "60"}),
    ]
    a = cmp.compare(_rfq(bids, n_lines=2)).get("a")
    assert a is not None
    assert a.plug_sources == ()


def test_excluded_line_is_plugged_with_reason_excluded() -> None:
    bids = [_bid("a", {1: "100", 2: None}), _bid("b", {1: "100", 2: "40"}), _bid("c", {1: "100", 2: "60"})]
    plug = cmp.compare(_rfq(bids, n_lines=2)).get("a").plug_sources[0]  # type: ignore[union-attr]
    assert plug["reason"] == "excluded"
    assert plug["amount"] == "50.00"


def test_headline_only_quote_is_not_plugged() -> None:
    """No line detail means the lump sum is for everything; plugging would count it twice."""
    lump = {"id": "a", "bidder_contact_id": "a", "bid_amount": "300", "currency_code": "EUR", "lines": []}
    a = cmp.compare(_rfq([lump, _bid("b", {1: "100", 2: "100", 3: "100"})])).get("a")
    assert a is not None
    assert a.plug_total == Decimal("0")


def test_plugs_are_in_basis_currency() -> None:
    bids = [
        _bid("a", {1: "100"}),
        _bid("b", {1: "100", 2: "200"}, currency_code="USD", exchange_rate="0.5"),
        _bid("c", {1: "100", 2: "120"}),
    ]
    plug = cmp.compare(_rfq(bids, n_lines=2)).get("a").plug_sources[0]  # type: ignore[union-attr]
    assert plug["amount"] == "110.00"  # mean of 200 USD x 0.5 = 100 EUR and 120 EUR


def test_withdrawn_quote_does_not_set_the_market() -> None:
    bids = [
        _bid("a", {1: "100"}),
        _bid("b", {1: "100", 2: "10"}, status="withdrawn"),
        _bid("c", {1: "100", 2: "60"}),
    ]
    plug = cmp.compare(_rfq(bids, n_lines=2)).get("a").plug_sources[0]  # type: ignore[union-attr]
    assert plug["source"] == "single_bid"
    assert plug["amount"] == "60.00"


def test_as_dict_carries_raw_plug_and_plugged_totals() -> None:
    bids = [_bid("a", {1: "100"}), _bid("b", {1: "100", 2: "50"})]
    row = cmp.compare(_rfq(bids, n_lines=2)).get("a").as_dict()  # type: ignore[union-attr]
    assert (row["raw_total"], row["plug_total"], row["plugged_total"]) == ("100.00", "50.00", "150.00")
    assert row["plug_sources"][0]["line"].startswith("2-A2")


async def _run(rule: Any, rfq: dict[str, Any]) -> list[Any]:
    rfq = {**rfq, "comparison": cmp.compare(rfq).as_dict()}
    return await rule.validate(ValidationContext(data=rfq, metadata={}))


@pytest.mark.asyncio
async def test_rule_plug_has_source_fails_on_unpluggable_gap() -> None:
    results = await _run(checks.RFQPlugHasSource(), _rfq([_bid("a", {1: "100"})], n_lines=2))
    assert [r.passed for r in results] == [False]


@pytest.mark.asyncio
async def test_rule_plug_has_source_passes_when_every_gap_has_a_source() -> None:
    bids = [_bid("a", {1: "100"}), _bid("b", {1: "100", 2: "50"})]
    results = await _run(checks.RFQPlugHasSource(), _rfq(bids, n_lines=2))
    assert [r.passed for r in results] == [True]


@pytest.mark.asyncio
async def test_rule_plugged_quote_disclosed_warns_and_flags_thin_market() -> None:
    bids = [_bid("a", {1: "100"}), _bid("b", {1: "100", 2: "50"})]
    results = await _run(checks.RFQPlugDisclosed(), _rfq(bids, n_lines=2))
    assert len(results) == 1 and results[0].passed is False
    assert "one or two other quotes" in results[0].message


@pytest.mark.asyncio
async def test_rule_plugged_quote_disclosed_passes_without_plugs() -> None:
    bids = [_bid("a", {1: "100", 2: "10"}), _bid("b", {1: "100", 2: "50"})]
    results = await _run(checks.RFQPlugDisclosed(), _rfq(bids, n_lines=2))
    assert [r.passed for r in results] == [True]


def test_lump_sum_above_its_lines_is_not_plugged_but_needs_clarification() -> None:
    """A headline above the sum of its lines may already cover the unlisted item."""
    bids = [
        _bid("a", {1: "100", 2: "100"}, bid_amount="300"),  # lines 200, lump sum 300
        _bid("b", {1: "100", 2: "100", 3: "100"}),
        _bid("c", {1: "110", 2: "110", 3: "130"}),
    ]
    result = cmp.compare(_rfq(bids))
    a = result.get("a")
    assert a is not None
    assert cmp.REASON_LUMP_SUM_NEEDS_CLARIFICATION in a.reasons
    assert a.plugs_applied is False
    assert a.plug_total == Decimal("0")
    assert a.normalised_amount is None
    assert "a" not in [q.bid_id for q in result.ranked]


def test_lump_sum_matching_its_lines_is_still_plugged() -> None:
    bids = [_bid("a", {1: "100", 2: "100"}), _bid("b", {1: "100", 2: "100", 3: "100"})]
    a = cmp.compare(_rfq(bids)).get("a")
    assert a is not None
    assert a.plugs_applied is True
    assert cmp.REASON_LUMP_SUM_NEEDS_CLARIFICATION not in a.reasons


def test_lump_sum_only_quote_with_partial_scope_is_not_ranked_until_confirmed() -> None:
    lump = {"id": "l", "bidder_contact_id": "l", "bid_amount": "50", "currency_code": "EUR", "status": "received"}
    full = _bid("b", {1: "100", 2: "100", 3: "100"})
    result = cmp.compare(_rfq([dict(lump), full]))
    quote = result.get("l")
    assert quote is not None
    assert cmp.REASON_SCOPE_UNCONFIRMED in quote.reasons
    assert [q.bid_id for q in result.ranked] == ["b"]

    confirmed = cmp.compare(_rfq([dict(lump, scope_confirmed=True), full]))
    assert [q.bid_id for q in confirmed.ranked] == ["l", "b"]
    assert cmp.REASON_SCOPE_UNCONFIRMED not in confirmed.get("l").reasons  # type: ignore[union-attr]


def test_estimate_rate_in_another_currency_is_not_used_as_a_plug() -> None:
    rfq = _rfq([_bid("a", {1: "100"}), _bid("b", {1: "100", 2: "50"})], n_lines=2)
    rfq["lines"][1]["estimate_rate"] = "7"
    rfq["lines"][1]["estimate_currency"] = "USD"
    plug = cmp.compare(rfq).get("a").plug_sources[0]  # type: ignore[union-attr]
    assert plug["source"] != "estimate"


def test_estimate_rate_in_the_basis_currency_is_used() -> None:
    rfq = _rfq([_bid("a", {1: "100"}), _bid("b", {1: "100", 2: "50"})], n_lines=2)
    rfq["lines"][1]["estimate_rate"] = "7"
    rfq["lines"][1]["estimate_currency"] = "eur"
    assert cmp.compare(rfq).get("a").plug_sources[0]["source"] == "estimate"  # type: ignore[union-attr]
