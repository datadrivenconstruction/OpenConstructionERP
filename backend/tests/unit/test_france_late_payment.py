"""French statutory late payment as a row of the shared engine, not an engine of its own.

Each case is chosen so a wrong reading gives another answer: the ECB move of 17 June 2026
falls inside H1 and must not reach the 1 July fixing early, a public debtor has no rate
because its fixing model is not expressible, and the indemnity is flat.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.core import late_payment as lp


def test_the_row_is_sound() -> None:
    assert lp.validate_rows() == []


def test_second_half_2026_is_ecb_plus_ten() -> None:
    assert lp.statutory_late_interest_rate("FR", "commercial", date(2026, 7, 1)) == Decimal("12.40")


def test_the_rate_of_the_first_half_year_is_fixed_on_the_first_of_january() -> None:
    # The ECB moved to 2.40 on 17 June 2026, yet 20 June still carries the 1 January fixing.
    assert lp.statutory_late_interest_rate("FR", "commercial", date(2026, 6, 20)) == Decimal("12.15")


def test_a_delay_across_the_half_year_splits_into_two_rates() -> None:
    result = lp.late_interest("FR", "commercial", Decimal("10000.00"), date(2026, 6, 29), date(2026, 7, 2))
    assert [p.rate_percent for p in result.periods] == [Decimal("12.15"), Decimal("12.40")]
    assert result.unknown_days == 0


def test_a_date_outside_the_periods_is_not_guessed() -> None:
    assert lp.statutory_late_interest_rate("FR", "commercial", date(2025, 6, 30)) is None
    assert lp.statutory_late_interest_rate("FR", "commercial", date(2027, 1, 1)) is None


def test_a_public_delay_across_the_half_year_keeps_the_rate_of_the_half_year_it_started_in() -> None:
    # Due 29 June: the delay starts 30 June (H1, ECB 2.15), so 10.15 holds on 2 July too.
    result = lp.late_interest("FR", "public", Decimal("10000.00"), date(2026, 6, 29), date(2026, 7, 2))
    assert [p.rate_percent for p in result.periods] == [Decimal("10.15")]
    assert result.periods[0].days == 3
    assert result.complete


def test_a_public_delay_starting_in_the_second_half_year_takes_that_half_year() -> None:
    result = lp.late_interest("FR", "public", Decimal("10000.00"), date(2026, 6, 30), date(2026, 7, 3))
    assert [p.rate_percent for p in result.periods] == [Decimal("10.40")]


def test_fixed_at_delay_start_differs_from_re_pricing_per_period() -> None:
    args = ("10000.00", date(2026, 6, 29), date(2026, 7, 2))
    fixed = lp.late_interest("FR", "public", Decimal(args[0]), args[1], args[2])
    per_period = lp.late_interest("FR", "commercial", Decimal(args[0]), args[1], args[2])
    # Same 8 point gap aside, the commercial delay is re-priced on 1 July and the public one is not.
    assert len(per_period.periods) == 2
    assert len(fixed.periods) == 1
    assert fixed.interest == Decimal("8.34")  # 10000 * 10.15% * 3 / 365


def test_the_same_margin_priced_both_ways_gives_two_totals(monkeypatch) -> None:
    import copy

    base = lp._load()
    totals = {}
    for mode in ("per_period", "at_delay_start"):
        data = copy.deepcopy(base)
        for m in data["countries"]["FR"]["margins"]:
            if m["debtor_kind"] == "public":
                m["rate_fixing"] = mode
        monkeypatch.setattr(lp, "_load", lambda d=data: d)
        totals[mode] = lp.late_interest(
            "FR", "public", Decimal("100000.00"), date(2026, 6, 29), date(2026, 7, 2)
        ).interest
    assert totals["per_period"] != totals["at_delay_start"]
    assert totals["per_period"] > totals["at_delay_start"]


def test_the_public_rate_without_a_delay_start_is_the_plain_period_rate() -> None:
    assert lp.statutory_late_interest_rate("FR", "public", date(2026, 8, 1)) == Decimal("10.40")
    assert lp.rate_fixing("FR", "public", date(2026, 8, 1)) == "at_delay_start"
    assert lp.rate_fixing("FR", "commercial", date(2026, 8, 1)) == "per_period"


def test_a_public_delay_starting_before_the_known_periods_is_not_guessed() -> None:
    assert lp.statutory_late_interest_rate("FR", "public", date(2026, 3, 1), date(2025, 3, 1)) is None


def test_the_agreed_rate_floor_is_three_times_the_legal_rate() -> None:
    assert lp.agreed_rate_floor_percent("FR", "commercial", date(2026, 8, 1)) == Decimal("8.25")
    assert lp.agreed_rate_floor_percent("FR", "commercial", date(2026, 2, 1)) == Decimal("7.86")
    assert lp.agreed_rate_floor_percent("FR", "commercial", date(2027, 2, 1)) is None
    assert lp.agreed_rate_floor_percent("FR", "public", date(2026, 8, 1)) is None
    assert lp.agreed_rate_floor_percent("PL", "commercial", date(2026, 8, 1)) is None


def test_term_caps_by_debtor_kind() -> None:
    on = date(2026, 8, 1)
    assert lp.payment_term_cap_days("FR", "commercial", on) == 60
    assert lp.payment_term_cap_days("FR", "public", on) == 30
    assert lp.payment_term_cap_days("FR", "public_medical", on) == 50
    assert lp.term_exceeds_cap("FR", "commercial", 61, on)
    assert not lp.term_exceeds_cap("FR", "commercial", 60, on)


def test_the_recovery_indemnity_is_a_flat_forty_euro_at_any_claim_size() -> None:
    for claim in ("1.00", "5000.00", "900000.00"):
        assert lp.recovery_compensation("FR", Decimal(claim), eur_rate=Decimal("1")) == (
            Decimal("40"),
            Decimal("40.00"),
        )
