# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Polish statutory late payment: dated interest, term caps and recovery compensation.

Each case is chosen so that a wrong implementation gives a different answer:
the half-year boundary, a day before the first known period, the statute's
tier boundaries, and a delay that straddles two rates.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest

from app.core import late_payment as lp
from app.modules.payment_clock.data import PAYMENT_REGIMES, regime_by_code


class TestStatutoryRate:
    def test_the_rate_changes_on_the_first_day_of_the_second_half_year(self) -> None:
        assert lp.statutory_late_interest_rate("PL", "commercial", date(2026, 6, 30)) == Decimal("14.00")
        assert lp.statutory_late_interest_rate("PL", "commercial", date(2026, 7, 1)) == Decimal("13.75")

    def test_a_public_medical_debtor_pays_eight_points_not_ten(self) -> None:
        assert lp.statutory_late_interest_rate("PL", "public_medical", date(2026, 3, 1)) == Decimal("12.00")
        assert lp.statutory_late_interest_rate("PL", "public", date(2026, 3, 1)) == Decimal("14.00")

    def test_a_day_before_the_first_known_period_is_unknown_and_not_extrapolated(self) -> None:
        assert lp.statutory_late_interest_rate("PL", "commercial", date(2025, 12, 31)) is None
        assert lp.rate_unknown_reason("PL", "commercial", date(2025, 12, 31)) == "no_reference_rate_period"

    def test_a_day_after_the_last_known_period_is_unknown(self) -> None:
        assert lp.statutory_late_interest_rate("PL", "commercial", date(2027, 1, 1)) is None

    def test_a_country_without_data_is_unknown(self) -> None:
        assert lp.statutory_late_interest_rate("DE", "commercial", date(2026, 3, 1)) is None
        assert lp.rate_unknown_reason("DE", "commercial", date(2026, 3, 1)) == "no_country_data"

    def test_an_unknown_debtor_kind_is_refused(self) -> None:
        with pytest.raises(ValueError):
            lp.statutory_late_interest_rate("PL", "consumer", date(2026, 3, 1))


class TestLateInterest:
    def test_a_delay_across_the_half_year_is_split_at_each_rate(self) -> None:
        # Due 2026-06-20, paid 2026-07-10: interest runs 21 June to 10 July
        # inclusive, 20 days. 21-30 June is 10 days at 14.00 %, 1-10 July is
        # 10 days at 13.75 %, actual/365:
        #   100000 x 0.14   x 10 / 365 = 383.5616... -> 383.56
        #   100000 x 0.1375 x 10 / 365 = 376.7123... -> 376.71
        #   total 277500 / 365          = 760.2739... -> 760.27
        result = lp.late_interest("PL", "commercial", Decimal("100000"), date(2026, 6, 20), date(2026, 7, 10))
        assert [(p.start, p.end, p.days, p.rate_percent) for p in result.periods] == [
            (date(2026, 6, 21), date(2026, 6, 30), 10, Decimal("14.00")),
            (date(2026, 7, 1), date(2026, 7, 10), 10, Decimal("13.75")),
        ]
        assert [p.interest for p in result.periods] == [Decimal("383.56"), Decimal("376.71")]
        assert result.interest == Decimal("760.27")
        assert result.unknown_days == 0

    def test_a_single_rate_would_give_another_amount(self) -> None:
        # The same 20 days all at 14 % would be 767.12; the split is what is tested.
        result = lp.late_interest("PL", "commercial", Decimal("100000"), date(2026, 6, 20), date(2026, 7, 10))
        assert result.interest != Decimal("767.12")

    def test_paid_on_time_owes_nothing(self) -> None:
        result = lp.late_interest("PL", "commercial", Decimal("100000"), date(2026, 6, 20), date(2026, 6, 20))
        assert result.interest == Decimal("0.00")
        assert result.periods == ()

    def test_days_without_a_known_rate_are_counted_and_not_priced(self) -> None:
        # Due 2025-12-26, paid 2026-01-05: 27-31 December 2025 (5 days) have no
        # known rate; 1-5 January 2026 (5 days) are at 14 %.
        #   100000 x 0.14 x 5 / 365 = 191.7808... -> 191.78
        result = lp.late_interest("PL", "commercial", Decimal("100000"), date(2025, 12, 26), date(2026, 1, 5))
        assert result.unknown_days == 5
        assert result.interest == Decimal("191.78")
        assert result.complete is False


class TestRecoveryCompensation:
    @pytest.mark.parametrize(
        ("claim", "eur"),
        [
            ("4999.99", "40"),
            ("5000.00", "40"),  # "does not exceed PLN 5,000"
            ("5000.01", "70"),
            ("49999.99", "70"),
            ("50000.00", "100"),  # "equal to or higher than PLN 50,000"
            ("50000.01", "100"),
        ],
    )
    def test_the_tier_follows_the_statute_boundaries(self, claim: str, eur: str) -> None:
        amount_eur, amount_pln = lp.recovery_compensation("PL", Decimal(claim), eur_rate=Decimal("4.2500"))
        assert amount_eur == Decimal(eur)
        assert amount_pln == (Decimal(eur) * Decimal("4.2500")).quantize(Decimal("0.01"))

    def test_seventy_euro_at_a_given_rate(self) -> None:
        assert lp.recovery_compensation("PL", Decimal("12000"), eur_rate=Decimal("4.2731")) == (
            Decimal("70"),
            Decimal("299.12"),
        )

    def test_a_country_without_data_has_none(self) -> None:
        assert lp.recovery_compensation("DE", Decimal("12000"), eur_rate=Decimal("1")) is None


class TestTermCaps:
    def test_commercial_sixty_public_thirty(self) -> None:
        assert lp.payment_term_cap_days("PL", "commercial") == 60
        assert lp.payment_term_cap_days("PL", "public") == 30
        assert lp.payment_term_cap_days("PL", "public_medical") == 60
        assert lp.payment_term_cap_days("DE", "commercial") is None

    def test_a_term_above_the_cap_is_flagged_and_one_at_it_is_not(self) -> None:
        assert lp.term_exceeds_cap("PL", "public", 31) is True
        assert lp.term_exceeds_cap("PL", "public", 30) is False
        assert lp.term_exceeds_cap("PL", "commercial", 60) is False
        assert lp.term_exceeds_cap("PL", "commercial", 61) is True
        assert lp.term_exceeds_cap("DE", "commercial", 400) is False


class TestData:
    def test_the_shipped_rows_validate(self) -> None:
        assert lp.validate_rows() == []

    def test_overlapping_periods_are_refused(self) -> None:
        data = json.loads(lp.DATA_PATH.read_text(encoding="utf-8"))
        periods = data["countries"]["PL"]["reference_rate_periods"]
        periods[1]["effective_from"] = "2026-06-30"
        assert any("overlap" in p for p in lp.validate_rows(data))

    def test_a_published_rate_that_disagrees_with_the_formula_is_refused(self) -> None:
        data = json.loads(lp.DATA_PATH.read_text(encoding="utf-8"))
        data["countries"]["PL"]["reference_rate_periods"][0]["published_rates"]["commercial"] = "13.00"
        assert any("published" in p for p in lp.validate_rows(data))

    def test_a_row_without_a_source_is_refused(self) -> None:
        data = json.loads(lp.DATA_PATH.read_text(encoding="utf-8"))
        del data["countries"]["PL"]["term_caps"][0]["source_url"]
        assert any("source_url" in p for p in lp.validate_rows(data))


class TestPaymentClockRows:
    def test_poland_has_a_commercial_and_a_public_row(self) -> None:
        codes = {r["code"] for r in PAYMENT_REGIMES if r.get("country_code") == "PL"}
        assert codes == {"pl_late_payment_b2b", "pl_late_payment_public"}

    def test_the_rows_carry_the_same_margin_as_the_engine(self) -> None:
        for code, kind in (("pl_late_payment_b2b", "commercial"), ("pl_late_payment_public", "public")):
            row = regime_by_code(code)
            assert row is not None
            assert row["interest_basis"] == "reference_rate_plus_margin"
            assert row["interest_margin_percent"] == lp.margin_percent("PL", kind, date(2026, 10, 19))
            assert row["final_date_days"] == 30

    def test_the_rows_have_every_key_the_hungarian_row_has(self) -> None:
        reference = set(regime_by_code("hu_ptk_6_130") or {})
        for code in ("pl_late_payment_b2b", "pl_late_payment_public"):
            assert set(regime_by_code(code) or {}) == reference
