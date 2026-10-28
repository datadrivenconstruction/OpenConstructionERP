# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Putting quotes on one basis before ranking them.

No database and no clock: the comparison takes dictionaries and a supplied
``as_of``, so every case here is the arithmetic itself rather than a fixture of
one. The cases are the ones that decide real awards - a quote in another
currency, a quote that excluded delivery, a quote for eight of the ten lines, a
quote that arrived on Monday for a Friday deadline - and in each of them the
naive answer (sort the headline numbers) is a different answer from the right
one.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from app.modules.rfq_bidding import comparison as cmp

TODAY = "2026-07-10"


def _line(**overrides: Any) -> dict[str, Any]:
    """One scope line of the RFQ."""
    base: dict[str, Any] = {
        "id": "line-1",
        "line_no": 1,
        "code": "A1",
        "description": "Ductwork",
        "unit": "m2",
        "quantity": "100",
        "is_optional": False,
    }
    base.update(overrides)
    return base


def _quote_line(**overrides: Any) -> dict[str, Any]:
    """One priced line inside a quote."""
    base: dict[str, Any] = {
        "id": "quoted-1",
        "rfq_line_id": "line-1",
        "description": "Ductwork",
        "unit": "m2",
        "quantity": "100",
        "unit_rate": "10",
        "amount": "1000",
        "unit_conversion_factor": None,
        "is_excluded": False,
    }
    base.update(overrides)
    return base


def _adjustment(**overrides: Any) -> dict[str, Any]:
    """One inclusion or exclusion recorded against a quote."""
    base: dict[str, Any] = {
        "id": "adj-1",
        "kind": "freight",
        "description": "Delivery to site",
        "amount": "200",
        "currency_code": "EUR",
        "included_in_bid": False,
        "source": "bidder",
    }
    base.update(overrides)
    return base


def _quote(**overrides: Any) -> dict[str, Any]:
    """One quote returned against the RFQ."""
    base: dict[str, Any] = {
        "id": "bid-a",
        "bidder_contact_id": "alpha",
        "bid_amount": "1000",
        "currency_code": "EUR",
        "status": "received",
        "is_late": False,
        "admitted_at": None,
        "submitted_at": "2026-07-01",
        "validity_days": 60,
        "technical_score": None,
        "exchange_rate": None,
        "lines": [],
        "adjustments": [],
    }
    base.update(overrides)
    return base


def _rfq(**overrides: Any) -> dict[str, Any]:
    """An RFQ payload of the shape the service builds."""
    base: dict[str, Any] = {
        "id": "rfq-1",
        "rfq_number": "RFQ-014",
        "currency_code": "EUR",
        "evaluation_method": "lowest_price",
        "technical_weight": "0",
        "require_full_scope": True,
        "as_of": TODAY,
        "lines": [],
        "bids": [],
    }
    base.update(overrides)
    return base


def _ranked_ids(result: cmp.ComparisonResult) -> list[str]:
    return [quote.bid_id for quote in result.ranked]


def _excluded_ids(result: cmp.ComparisonResult) -> list[str]:
    return [quote.bid_id for quote in result.excluded]


# ── Ranking the straightforward case ────────────────────────────────────────


class TestPlainRanking:
    def test_quotes_in_one_currency_rank_by_amount(self) -> None:
        result = cmp.compare(
            _rfq(
                bids=[
                    _quote(id="bid-a", bidder_contact_id="alpha", bid_amount="1200"),
                    _quote(id="bid-b", bidder_contact_id="beta", bid_amount="900"),
                    _quote(id="bid-c", bidder_contact_id="gamma", bid_amount="1000"),
                ]
            )
        )
        assert _ranked_ids(result) == ["bid-b", "bid-c", "bid-a"]
        assert [quote.rank for quote in result.ranked] == [1, 2, 3]
        assert result.recommended_bid_id == "bid-b"
        assert result.excluded == ()

    def test_a_tie_is_broken_the_same_way_every_time(self) -> None:
        """Two identical prices must not shuffle between two reads of the table."""
        first = cmp.compare(
            _rfq(
                bids=[
                    _quote(id="bid-b", bidder_contact_id="beta", bid_amount="1000"),
                    _quote(id="bid-a", bidder_contact_id="alpha", bid_amount="1000"),
                ]
            )
        )
        second = cmp.compare(
            _rfq(
                bids=[
                    _quote(id="bid-a", bidder_contact_id="alpha", bid_amount="1000"),
                    _quote(id="bid-b", bidder_contact_id="beta", bid_amount="1000"),
                ]
            )
        )
        assert _ranked_ids(first) == _ranked_ids(second) == ["bid-a", "bid-b"]

    def test_an_unreadable_amount_never_ranks(self) -> None:
        result = cmp.compare(_rfq(bids=[_quote(bid_amount="on request")]))
        assert _ranked_ids(result) == []
        assert result.excluded[0].reasons == (cmp.REASON_AMOUNT_UNREADABLE,)
        assert result.recommended_bid_id is None


# ── Currency ────────────────────────────────────────────────────────────────


class TestCurrency:
    def test_a_foreign_quote_without_a_rate_is_not_ranked(self) -> None:
        """The cheapest number on screen is not an offer until it is the same money."""
        result = cmp.compare(
            _rfq(
                bids=[
                    _quote(id="bid-a", bidder_contact_id="alpha", bid_amount="1200"),
                    _quote(id="bid-b", bidder_contact_id="beta", bid_amount="900", currency_code="USD"),
                ]
            )
        )
        assert _ranked_ids(result) == ["bid-a"]
        assert cmp.REASON_CURRENCY_NOT_CONVERTED in result.excluded[0].reasons
        assert result.excluded[0].normalised_amount is None

    def test_a_recorded_rate_converts_the_quote(self) -> None:
        result = cmp.compare(
            _rfq(
                bids=[
                    _quote(id="bid-a", bidder_contact_id="alpha", bid_amount="1100"),
                    _quote(
                        id="bid-b",
                        bidder_contact_id="beta",
                        bid_amount="1000",
                        currency_code="GBP",
                        exchange_rate="1.15",
                    ),
                ]
            )
        )
        # 1000 GBP at 1.15 is 1150 EUR, which is dearer than 1100 EUR even
        # though its headline number is smaller.
        assert _ranked_ids(result) == ["bid-a", "bid-b"]
        converted = result.ranked[1]
        assert converted.converted_amount == Decimal("1150.00")
        assert cmp.NOTE_CONVERTED in converted.notes

    def test_case_is_not_a_currency_mismatch(self) -> None:
        result = cmp.compare(_rfq(bids=[_quote(currency_code="eur")]))
        assert _ranked_ids(result) == ["bid-a"]

    def test_the_basis_falls_back_to_the_one_currency_the_quotes_agree_on(self) -> None:
        """An RFQ saved without a currency is a fault, not a reason to refuse."""
        result = cmp.compare(
            _rfq(
                currency_code="",
                bids=[
                    _quote(id="bid-a", currency_code="CHF", bid_amount="1000"),
                    _quote(id="bid-b", bidder_contact_id="beta", currency_code="CHF", bid_amount="900"),
                ],
            )
        )
        assert result.basis_currency == "CHF"
        assert _ranked_ids(result) == ["bid-b", "bid-a"]

    def test_without_a_basis_mixed_currencies_are_not_ranked(self) -> None:
        result = cmp.compare(
            _rfq(
                currency_code="",
                bids=[
                    _quote(id="bid-a", currency_code="CHF", bid_amount="1000"),
                    _quote(id="bid-b", bidder_contact_id="beta", currency_code="USD", bid_amount="900"),
                ],
            )
        )
        assert _ranked_ids(result) == []
        assert all(cmp.REASON_CURRENCY_NOT_CONVERTED in quote.reasons for quote in result.excluded)


# ── Inclusions and exclusions ───────────────────────────────────────────────


class TestAdjustments:
    def test_an_excluded_item_is_added_to_the_quote_that_excluded_it(self) -> None:
        """The failure this whole module exists for.

        Alpha quotes 1000 and does not carry delivery; beta quotes 1100 and
        does. Ranking the headline numbers hands the package to alpha and the
        buyer pays 1200.
        """
        result = cmp.compare(
            _rfq(
                bids=[
                    _quote(
                        id="bid-a",
                        bidder_contact_id="alpha",
                        bid_amount="1000",
                        adjustments=[_adjustment(amount="200", included_in_bid=False)],
                    ),
                    _quote(
                        id="bid-b",
                        bidder_contact_id="beta",
                        bid_amount="1100",
                        adjustments=[_adjustment(amount="200", included_in_bid=True)],
                    ),
                ]
            )
        )
        assert _ranked_ids(result) == ["bid-b", "bid-a"]
        alpha = result.get("bid-a")
        assert alpha is not None
        assert alpha.normalised_amount == Decimal("1200")
        assert cmp.NOTE_ADJUSTED in alpha.notes

    def test_an_included_item_moves_nothing(self) -> None:
        result = cmp.compare(_rfq(bids=[_quote(adjustments=[_adjustment(amount="500", included_in_bid=True)])]))
        quote = result.ranked[0]
        assert quote.normalised_amount == Decimal("1000")
        assert quote.adjustments_included == 1
        assert quote.adjustments_applied == Decimal("0")

    def test_a_discount_lowers_the_comparable_total(self) -> None:
        result = cmp.compare(_rfq(bids=[_quote(adjustments=[_adjustment(kind="discount", amount="-150")])]))
        assert result.ranked[0].normalised_amount == Decimal("850")

    def test_a_buyer_allowance_prices_a_gap_the_supplier_left(self) -> None:
        result = cmp.compare(
            _rfq(
                bids=[
                    _quote(
                        adjustments=[_adjustment(kind="installation", amount="300", source="buyer")],
                    )
                ]
            )
        )
        assert result.ranked[0].normalised_amount == Decimal("1300")

    def test_an_adjustment_is_converted_with_the_quote(self) -> None:
        result = cmp.compare(
            _rfq(
                bids=[
                    _quote(
                        currency_code="GBP",
                        exchange_rate="1.2",
                        bid_amount="1000",
                        adjustments=[_adjustment(amount="100", currency_code="GBP")],
                    )
                ]
            )
        )
        assert result.ranked[0].normalised_amount == Decimal("1320.0")

    def test_an_adjustment_in_a_third_currency_is_not_guessed_at(self) -> None:
        result = cmp.compare(
            _rfq(
                bids=[
                    _quote(
                        currency_code="GBP",
                        exchange_rate="1.2",
                        adjustments=[_adjustment(amount="100", currency_code="JPY")],
                    )
                ]
            )
        )
        assert _ranked_ids(result) == []
        assert cmp.REASON_ADJUSTMENT_CURRENCY in result.excluded[0].reasons

    def test_an_unreadable_adjustment_amount_is_reported(self) -> None:
        result = cmp.compare(_rfq(bids=[_quote(adjustments=[_adjustment(amount="tbc")])]))
        assert cmp.REASON_ADJUSTMENT_UNREADABLE in result.excluded[0].reasons


# ── Scope coverage ──────────────────────────────────────────────────────────


class TestScopeCoverage:
    @staticmethod
    def _two_line_rfq(**overrides: Any) -> dict[str, Any]:
        return _rfq(
            lines=[
                _line(id="line-1", line_no=1, code="A1", description="Ductwork"),
                _line(id="line-2", line_no=2, code="A2", description="Commissioning"),
            ],
            **overrides,
        )

    def test_a_quote_for_part_of_the_scope_is_kept_out_of_the_ranking(self) -> None:
        result = cmp.compare(
            self._two_line_rfq(
                bids=[
                    _quote(
                        id="bid-a",
                        bidder_contact_id="alpha",
                        bid_amount="900",
                        lines=[_quote_line(rfq_line_id="line-1", amount="900")],
                    ),
                    _quote(
                        id="bid-b",
                        bidder_contact_id="beta",
                        bid_amount="1000",
                        lines=[
                            _quote_line(rfq_line_id="line-1", amount="800"),
                            _quote_line(id="quoted-2", rfq_line_id="line-2", amount="200"),
                        ],
                    ),
                ]
            )
        )
        assert _ranked_ids(result) == ["bid-b"]
        partial = result.get("bid-a")
        assert partial is not None
        assert cmp.REASON_SCOPE_NOT_COVERED in partial.reasons
        assert partial.lines_covered == 1
        assert partial.lines_required == 2
        assert partial.uncovered_lines == ("2-A2 (Commissioning)",)

    def test_a_partial_quote_ranks_when_the_rfq_allows_it(self) -> None:
        result = cmp.compare(
            self._two_line_rfq(
                require_full_scope=False,
                bids=[
                    _quote(
                        id="bid-a",
                        bid_amount="900",
                        lines=[_quote_line(rfq_line_id="line-1", amount="900")],
                    )
                ],
            )
        )
        assert _ranked_ids(result) == ["bid-a"]
        assert cmp.NOTE_PARTIAL_SCOPE in result.ranked[0].notes
        assert result.ranked[0].coverage == Decimal("0.5")

    def test_an_optional_line_never_counts_against_coverage(self) -> None:
        result = cmp.compare(
            _rfq(
                lines=[
                    _line(id="line-1", line_no=1),
                    _line(id="line-2", line_no=2, code="A2", description="Spare filters", is_optional=True),
                ],
                bids=[_quote(lines=[_quote_line(rfq_line_id="line-1", amount="1000")])],
            )
        )
        assert _ranked_ids(result) == ["bid-a"]
        assert result.ranked[0].coverage == Decimal("1")

    def test_a_line_the_supplier_excluded_is_a_gap_that_says_so(self) -> None:
        result = cmp.compare(
            self._two_line_rfq(
                require_full_scope=False,
                bids=[
                    _quote(
                        lines=[
                            _quote_line(rfq_line_id="line-1", amount="1000"),
                            _quote_line(id="quoted-2", rfq_line_id="line-2", amount="0", is_excluded=True),
                        ]
                    )
                ],
            )
        )
        quote = result.ranked[0]
        assert quote.excluded_lines == ("2-A2 (Commissioning)",)
        assert quote.lines_covered == 1

    def test_a_line_the_supplier_added_is_counted_as_an_extra(self) -> None:
        result = cmp.compare(
            _rfq(
                lines=[_line(id="line-1")],
                bids=[
                    _quote(
                        lines=[
                            _quote_line(rfq_line_id="line-1", amount="900"),
                            _quote_line(id="quoted-2", rfq_line_id=None, description="Scaffold", amount="100"),
                        ]
                    )
                ],
            )
        )
        quote = result.ranked[0]
        assert quote.extra_lines == 1
        assert cmp.NOTE_EXTRA_LINES in quote.notes

    def test_lines_that_do_not_add_up_to_the_headline_are_flagged(self) -> None:
        result = cmp.compare(
            _rfq(
                lines=[_line(id="line-1")],
                bids=[_quote(bid_amount="1000", lines=[_quote_line(rfq_line_id="line-1", amount="880")])],
            )
        )
        quote = result.ranked[0]
        assert cmp.NOTE_LINES_DISAGREE in quote.notes
        assert quote.line_total == Decimal("880")
        # The headline is what the supplier offered, so that is what ranks.
        assert quote.normalised_amount == Decimal("1000")


# ── Units ───────────────────────────────────────────────────────────────────


class TestUnits:
    def test_a_different_unit_without_a_factor_is_not_comparable(self) -> None:
        result = cmp.compare(
            _rfq(
                lines=[_line(id="line-1", unit="m2")],
                bids=[_quote(lines=[_quote_line(rfq_line_id="line-1", unit="m3", amount="1000")])],
            )
        )
        assert _ranked_ids(result) == []
        assert cmp.REASON_UNIT_NOT_CONVERTIBLE in result.excluded[0].reasons

    def test_a_different_unit_with_a_factor_is_comparable(self) -> None:
        result = cmp.compare(
            _rfq(
                lines=[_line(id="line-1", unit="m2")],
                bids=[
                    _quote(
                        lines=[
                            _quote_line(
                                rfq_line_id="line-1",
                                unit="ft2",
                                amount="1000",
                                unit_conversion_factor="0.092903",
                            )
                        ]
                    )
                ],
            )
        )
        assert _ranked_ids(result) == ["bid-a"]

    def test_the_same_unit_written_differently_is_the_same_unit(self) -> None:
        result = cmp.compare(
            _rfq(
                lines=[_line(id="line-1", unit="M2")],
                bids=[_quote(lines=[_quote_line(rfq_line_id="line-1", unit=" m2 ", amount="1000")])],
            )
        )
        assert _ranked_ids(result) == ["bid-a"]


# ── Standing ────────────────────────────────────────────────────────────────


class TestStanding:
    def test_a_late_quote_is_visible_and_unranked_until_it_is_admitted(self) -> None:
        payload = _rfq(
            bids=[
                _quote(id="bid-a", bidder_contact_id="alpha", bid_amount="1000"),
                _quote(id="bid-b", bidder_contact_id="beta", bid_amount="800", status="late", is_late=True),
            ]
        )
        result = cmp.compare(payload)
        assert _ranked_ids(result) == ["bid-a"]
        assert _excluded_ids(result) == ["bid-b"]
        assert cmp.REASON_LATE_NOT_ADMITTED in result.excluded[0].reasons

        payload["bids"][1]["admitted_at"] = "2026-07-09T10:00:00Z"
        admitted = cmp.compare(payload)
        assert _ranked_ids(admitted) == ["bid-b", "bid-a"]
        assert cmp.NOTE_LATE_ADMITTED in admitted.ranked[0].notes

    @pytest.mark.parametrize(
        ("bid_status", "reason"),
        [("withdrawn", cmp.REASON_WITHDRAWN), ("disqualified", cmp.REASON_DISQUALIFIED)],
    )
    def test_a_quote_ruled_out_never_ranks(self, bid_status: str, reason: str) -> None:
        result = cmp.compare(_rfq(bids=[_quote(status=bid_status)]))
        assert _ranked_ids(result) == []
        assert reason in result.excluded[0].reasons

    def test_an_expired_quote_is_noted_rather_than_dropped(self) -> None:
        """A supplier will often honour a lapsed price; that is a conversation."""
        result = cmp.compare(_rfq(bids=[_quote(submitted_at="2026-01-01", validity_days=30)]))
        assert _ranked_ids(result) == ["bid-a"]
        assert cmp.NOTE_VALIDITY_EXPIRED in result.ranked[0].notes

    def test_the_clock_is_data(self) -> None:
        """The same quote is expired or current depending on the date supplied."""
        quote = _quote(submitted_at="2026-06-01", validity_days=30)
        early = cmp.compare(_rfq(as_of="2026-06-15", bids=[quote]))
        late = cmp.compare(_rfq(as_of="2026-08-15", bids=[quote]))
        assert cmp.NOTE_VALIDITY_EXPIRED not in early.ranked[0].notes
        assert cmp.NOTE_VALIDITY_EXPIRED in late.ranked[0].notes


# ── Best value ──────────────────────────────────────────────────────────────


class TestBestValue:
    @staticmethod
    def _field(weight: str) -> dict[str, Any]:
        return _rfq(
            evaluation_method="best_value",
            technical_weight=weight,
            bids=[
                _quote(id="bid-a", bidder_contact_id="alpha", bid_amount="1000", technical_score="80"),
                _quote(id="bid-b", bidder_contact_id="beta", bid_amount="800", technical_score="60"),
            ],
        )

    def test_a_low_technical_weight_favours_the_cheaper_quote(self) -> None:
        result = cmp.compare(self._field("40"))
        assert _ranked_ids(result) == ["bid-b", "bid-a"]
        assert result.ranked[0].total_score == Decimal("84")

    def test_a_high_technical_weight_can_change_the_winner(self) -> None:
        """The weight is the whole point of the method, so it has to move the order."""
        result = cmp.compare(self._field("80"))
        assert _ranked_ids(result) == ["bid-a", "bid-b"]
        assert result.ranked[0].price_score == Decimal("80")

    def test_a_quote_with_no_technical_score_is_not_scored_as_zero(self) -> None:
        payload = self._field("40")
        payload["bids"][0]["technical_score"] = None
        result = cmp.compare(payload)
        assert _ranked_ids(result) == ["bid-b"]
        assert cmp.REASON_TECHNICAL_SCORE_MISSING in result.excluded[0].reasons


# ── The report ──────────────────────────────────────────────────────────────


class TestReportShape:
    def test_every_number_leaves_as_a_string(self) -> None:
        """Money crosses the wire as a Decimal string; a float never appears."""
        result = cmp.compare(
            _rfq(
                lines=[_line(id="line-1")],
                bids=[
                    _quote(
                        currency_code="GBP",
                        exchange_rate="1.15",
                        lines=[_quote_line(rfq_line_id="line-1", amount="1000")],
                        adjustments=[_adjustment()],
                    )
                ],
            )
        )
        payload = result.as_dict()
        rows = payload["ranked"] + payload["excluded"]
        assert rows
        for row in rows:
            for key in ("headline_amount", "converted_amount", "normalised_amount", "adjustments_applied"):
                assert row[key] is None or isinstance(row[key], str), key
            assert isinstance(row["coverage"], str)
            assert not any(isinstance(value, float) for value in row.values())

    def test_the_report_carries_the_basis_it_used(self) -> None:
        payload = cmp.compare(_rfq(bids=[_quote()])).as_dict()
        assert payload["basis_currency"] == "EUR"
        assert payload["method"] == cmp.METHOD_LOWEST_PRICE
        assert payload["as_of"] == TODAY
        assert payload["require_full_scope"] is True

    def test_an_rfq_with_no_quotes_recommends_nothing(self) -> None:
        result = cmp.compare(_rfq())
        assert result.ranked == ()
        assert result.excluded == ()
        assert result.recommended_bid_id is None
