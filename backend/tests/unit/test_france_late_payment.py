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


def test_a_public_debtor_has_no_rate_until_its_fixing_model_is_expressible() -> None:
    assert lp.rate_unknown_reason("FR", "public", date(2026, 8, 1)) == "no_margin_for_debtor_kind"


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
