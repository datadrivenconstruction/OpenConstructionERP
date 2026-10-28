"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the international contract money and date helpers.

Database-free: everything under test in ``app.modules.contracts.intl`` is pure
and stdlib-only, so these tests need no session, app, or config. They pin the
international-robustness, edge-case, and explainability guarantees:

    * Money stays Decimal-exact; percentages round to the 0.0001 minor unit.
    * Currencies are never summed across differing codes.
    * Retention respects a cap; the amount payable floors at zero.
    * A payment due date on a weekend is shifted per the chosen rule.
    * Division by zero, empty sets, and bad input give clean values or a
      ValueError, never a NaN / inf or a 500.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.modules.contracts.intl import (
    DEFAULT_PAYMENT_TERM_DAYS,
    DEFAULT_RETENTION_PERCENT,
    MONEY_QUANTUM,
    amount_payable_this_period,
    build_payment_certificate,
    cumulative_certified_vs_contract_sum,
    defects_liability_end,
    describe_status,
    ensure_single_currency,
    explain_concept,
    normalize_currency,
    parse_iso_date,
    payment_due_date,
    quantize_money,
    require_non_negative,
    require_percent,
    retention_on_certified,
    retention_release_amount,
    to_decimal,
    total_in_single_currency,
)

# ── Low-level guards ───────────────────────────────────────────────────────


def test_to_decimal_none_and_empty_are_zero() -> None:
    assert to_decimal(None) == Decimal("0")
    assert to_decimal("") == Decimal("0")


def test_to_decimal_parses_string_and_int() -> None:
    assert to_decimal("12.50") == Decimal("12.50")
    assert to_decimal(7) == Decimal("7")


def test_to_decimal_rejects_non_numeric() -> None:
    with pytest.raises(ValueError, match="must be a number"):
        to_decimal("not-a-number", "fee")


def test_to_decimal_rejects_nan_and_inf() -> None:
    with pytest.raises(ValueError, match="finite"):
        to_decimal(float("nan"), "x")
    with pytest.raises(ValueError, match="finite"):
        to_decimal(Decimal("Infinity"), "x")


def test_quantize_money_rounds_half_up_to_quantum() -> None:
    assert quantize_money("1.00005") == Decimal("1.0001")
    assert str(MONEY_QUANTUM) == "0.0001"


def test_require_non_negative_rejects_negative() -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        require_non_negative("-1", "amount")


def test_require_percent_bounds() -> None:
    assert require_percent("100", "p") == Decimal("100")
    with pytest.raises(ValueError, match="between 0 and 100"):
        require_percent("150", "p")
    with pytest.raises(ValueError, match="between 0 and 100"):
        require_percent("-5", "p")


def test_parse_iso_date_accepts_string_and_date() -> None:
    assert parse_iso_date("2026-07-05") == date(2026, 7, 5)
    assert parse_iso_date(date(2026, 1, 2)) == date(2026, 1, 2)


def test_parse_iso_date_rejects_bad_string() -> None:
    with pytest.raises(ValueError, match="valid ISO date"):
        parse_iso_date("05/07/2026", "claim_date")


# ── Currency safety ────────────────────────────────────────────────────────


def test_normalize_currency() -> None:
    assert normalize_currency(" eur ") == "EUR"
    assert normalize_currency(None) == ""


def test_ensure_single_currency_ignores_blanks() -> None:
    assert ensure_single_currency(["USD", "", "usd"]) == "USD"
    assert ensure_single_currency([]) == ""


def test_ensure_single_currency_rejects_mix() -> None:
    with pytest.raises(ValueError, match="cannot mix currencies"):
        ensure_single_currency(["EUR", "USD"])


def test_total_in_single_currency_sums_pairs_and_dicts() -> None:
    out = total_in_single_currency(
        [
            (Decimal("100.25"), "GBP"),
            {"amount": "50.75", "currency": "gbp"},
        ]
    )
    assert out["currency"] == "GBP"
    assert out["total"] == Decimal("151.0000")
    assert out["count"] == 2


def test_total_in_single_currency_empty_is_zero_unset() -> None:
    out = total_in_single_currency([])
    assert out["total"] == Decimal("0")
    assert out["currency"] == ""


def test_total_in_single_currency_rejects_mixed() -> None:
    with pytest.raises(ValueError, match="cannot mix currencies"):
        total_in_single_currency([(1, "EUR"), (2, "USD")])


# ── Retention on certified ─────────────────────────────────────────────────


def test_retention_on_certified_default_percent() -> None:
    out = retention_on_certified(Decimal("10000"))
    assert out["retention_percent"] == DEFAULT_RETENTION_PERCENT
    assert out["retention_held"] == Decimal("500.0000")
    assert out["cap_reached"] is False
    assert "explanation" in out


def test_retention_on_certified_custom_percent() -> None:
    out = retention_on_certified(Decimal("10000"), retention_percent=Decimal("3"))
    assert out["retention_held"] == Decimal("300.0000")


def test_retention_on_certified_respects_cap() -> None:
    # 10% of 10000 = 1000 raw, but only 200 room left under a 5000 cap that
    # already holds 4800.
    out = retention_on_certified(
        Decimal("10000"),
        retention_percent=Decimal("10"),
        retention_cap=Decimal("5000"),
        retention_already_held=Decimal("4800"),
    )
    assert out["retention_before_cap"] == Decimal("1000.0000")
    assert out["retention_held"] == Decimal("200.0000")
    assert out["cumulative_retention_held"] == Decimal("5000.0000")
    assert out["cap_reached"] is True
    assert "capped" in out["explanation"].lower()


def test_retention_on_certified_cap_already_reached_holds_zero() -> None:
    out = retention_on_certified(
        Decimal("10000"),
        retention_percent=Decimal("10"),
        retention_cap=Decimal("5000"),
        retention_already_held=Decimal("5000"),
    )
    assert out["retention_held"] == Decimal("0")
    assert out["cap_reached"] is True


def test_retention_on_certified_rejects_negative_amount() -> None:
    with pytest.raises(ValueError, match="certified_amount"):
        retention_on_certified(Decimal("-1"))


def test_retention_on_certified_rejects_bad_percent() -> None:
    with pytest.raises(ValueError, match="between 0 and 100"):
        retention_on_certified(Decimal("100"), retention_percent=Decimal("120"))


# ── Retention release ──────────────────────────────────────────────────────


def test_retention_release_default_substantial_completion() -> None:
    out = retention_release_amount(Decimal("10000"), "substantial_completion")
    assert out["percent_released"] == Decimal("50")
    assert out["amount_released"] == Decimal("5000.0000")
    assert out["remaining"] == Decimal("5000.0000")


def test_retention_release_zero_held() -> None:
    out = retention_release_amount(0, "substantial_completion")
    assert out["amount_released"] == Decimal("0")
    assert out["remaining"] == Decimal("0")


def test_retention_release_unknown_event_releases_nothing() -> None:
    out = retention_release_amount(Decimal("10000"), "no_such_event")
    assert out["percent_released"] == Decimal("0")
    assert out["amount_released"] == Decimal("0")


def test_retention_release_custom_schedule() -> None:
    out = retention_release_amount(
        Decimal("20000"),
        "milestone_x",
        schedule={"milestone_x": Decimal("25")},
    )
    assert out["amount_released"] == Decimal("5000.0000")


# ── Amount payable this period ─────────────────────────────────────────────


def test_amount_payable_basic() -> None:
    out = amount_payable_this_period(
        Decimal("10000"),
        retention_held_to_date=Decimal("500"),
        previously_paid=Decimal("4000"),
    )
    assert out["amount_payable"] == Decimal("5500.0000")
    assert out["floored"] is False


def test_amount_payable_floors_at_zero() -> None:
    out = amount_payable_this_period(
        Decimal("1000"),
        retention_held_to_date=Decimal("50"),
        previously_paid=Decimal("2000"),
    )
    assert out["amount_payable"] == Decimal("0")
    assert out["floored"] is True
    assert out["net_before_floor"] < Decimal("0")


def test_amount_payable_rejects_negative_input() -> None:
    with pytest.raises(ValueError, match="previously_paid"):
        amount_payable_this_period(Decimal("100"), previously_paid=Decimal("-1"))


# ── Payment due date ───────────────────────────────────────────────────────


def test_payment_due_date_default_net_term() -> None:
    # 2026-01-01 (Thursday) + 30 days = 2026-01-31 (Saturday) -> next Monday.
    out = payment_due_date("2026-01-01")
    assert out["net_days"] == DEFAULT_PAYMENT_TERM_DAYS
    assert out["raw_due_date"] == "2026-01-31"
    assert out["due_date"] == "2026-02-02"
    assert out["shifted"] is True
    assert out["due_weekday"] == "Monday"


def test_payment_due_date_weekday_no_shift() -> None:
    # 2026-01-05 (Monday) + 14 = 2026-01-19 (Monday), no weekend shift.
    out = payment_due_date("2026-01-05", net_days=14)
    assert out["due_date"] == "2026-01-19"
    assert out["shifted"] is False


def test_payment_due_date_previous_business_day_rule() -> None:
    out = payment_due_date("2026-01-01", net_days=30, weekend_rule="previous_business_day")
    # Saturday 2026-01-31 -> previous Friday 2026-01-30.
    assert out["due_date"] == "2026-01-30"
    assert out["due_weekday"] == "Friday"


def test_payment_due_date_none_rule_keeps_weekend() -> None:
    out = payment_due_date("2026-01-01", net_days=30, weekend_rule="none")
    assert out["due_date"] == "2026-01-31"
    assert out["shifted"] is False


def test_payment_due_date_rejects_bad_rule() -> None:
    with pytest.raises(ValueError, match="weekend_rule"):
        payment_due_date("2026-01-01", weekend_rule="whenever")


def test_payment_due_date_rejects_negative_days() -> None:
    with pytest.raises(ValueError, match="net_days must not be negative"):
        payment_due_date("2026-01-01", net_days=-5)


def test_payment_due_date_rejects_bool_days() -> None:
    with pytest.raises(ValueError, match="net_days must be an integer"):
        payment_due_date("2026-01-01", net_days=True)


# ── Cumulative certified vs contract sum ───────────────────────────────────


def test_cumulative_certified_basic() -> None:
    out = cumulative_certified_vs_contract_sum(
        [Decimal("2000"), Decimal("3000")],
        Decimal("10000"),
    )
    assert out["cumulative_certified"] == Decimal("5000.0000")
    assert out["remaining"] == Decimal("5000.0000")
    assert out["percent_certified"] == Decimal("50.0000")
    assert out["over_certified"] is False


def test_cumulative_certified_empty_set() -> None:
    out = cumulative_certified_vs_contract_sum([], Decimal("10000"))
    assert out["cumulative_certified"] == Decimal("0")
    assert out["percent_certified"] == Decimal("0")


def test_cumulative_certified_zero_contract_sum_no_div_by_zero() -> None:
    out = cumulative_certified_vs_contract_sum([Decimal("100")], Decimal("0"))
    assert out["percent_certified"] == Decimal("0")
    assert out["over_certified"] is True
    assert out["remaining"] == Decimal("-100.0000")


def test_cumulative_certified_over_certified() -> None:
    out = cumulative_certified_vs_contract_sum([Decimal("12000")], Decimal("10000"))
    assert out["over_certified"] is True
    assert "over-certified" in out["explanation"].lower()


# ── Defects liability period ───────────────────────────────────────────────


def test_defects_liability_end_default_months() -> None:
    out = defects_liability_end("2026-03-15")
    assert out["end_date"] == "2027-03-15"
    assert out["basis"] == "months"
    assert out["months"] == 12


def test_defects_liability_end_month_day_clamp() -> None:
    # 31 Jan + 1 month clamps to 28 Feb (non-leap 2027).
    out = defects_liability_end("2027-01-31", months=1)
    assert out["end_date"] == "2027-02-28"


def test_defects_liability_end_days_basis() -> None:
    out = defects_liability_end("2026-03-15", days=90)
    assert out["basis"] == "days"
    assert out["end_date"] == "2026-06-13"


def test_defects_liability_end_rejects_negative() -> None:
    with pytest.raises(ValueError, match="months must be a non-negative integer"):
        defects_liability_end("2026-03-15", months=-1)


# ── Composite payment certificate ──────────────────────────────────────────


def test_build_payment_certificate_ties_pieces_together() -> None:
    cert = build_payment_certificate(
        Decimal("10000"),
        currency="eur",
        retention_percent=Decimal("5"),
        previously_paid=Decimal("2000"),
        invoice_date="2026-01-05",
        net_days=30,
    )
    assert cert["currency"] == "EUR"
    assert cert["retention"]["retention_held"] == Decimal("500.0000")
    # payable = 10000 - 500 retention - 2000 prior = 7500
    assert cert["amount_payable"] == Decimal("7500.0000")
    assert cert["payment_due"]["due_date"] == "2026-02-04"


def test_build_payment_certificate_without_invoice_date() -> None:
    cert = build_payment_certificate(Decimal("1000"))
    assert cert["payment_due"] is None
    assert cert["amount_payable"] == Decimal("950.0000")


# ── Plain-language explainers ──────────────────────────────────────────────


def test_explain_concept_known() -> None:
    assert "holds back" in explain_concept("retention").lower()
    assert explain_concept("certified_value")


def test_explain_concept_unknown_is_safe() -> None:
    out = explain_concept("some_new_term")
    assert "some new term" in out.lower()


def test_describe_status_known() -> None:
    assert describe_status("contract", "active") == "Active and in force"
    assert describe_status("claim", "certified") == "Certified, cleared for payment"


def test_describe_status_unknown_degrades_gracefully() -> None:
    assert describe_status("contract", "weird_code") == "Weird Code"
    assert describe_status("nope", "") == "Unknown"
