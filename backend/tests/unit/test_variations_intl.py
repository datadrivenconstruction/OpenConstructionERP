"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠International robustness of the variations value roll-ups.

Pure, database-free tests for the additive helpers that turn a set of
variations into a currency-safe revised contract sum. They pin the
behaviour the platform needs for worldwide use: no hardcoded currency,
Decimal-exact money, no summing across currencies, guarded divisions and
plain-language output.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.modules.variations.service import (
    assert_single_currency,
    build_contract_sum_rollup,
    cumulative_contract_sum_movement,
    explain_variation_concept,
    percent_of_contract,
    plain_status_label,
    rollup_by_value_status,
    variation_value_bucket,
)


def _item(status: str, amount: str, currency: str = "") -> SimpleNamespace:
    return SimpleNamespace(status=status, final_cost_impact=Decimal(amount), currency=currency)


# --- Status bucketing --------------------------------------------------------


def test_variation_value_bucket_maps_known_statuses() -> None:
    assert variation_value_bucket("approved") == "agreed"
    assert variation_value_bucket("completed") == "agreed"
    assert variation_value_bucket("submitted") == "pending"
    assert variation_value_bucket("under_review") == "pending"
    assert variation_value_bucket("rejected") == "rejected"
    assert variation_value_bucket("voided") == "rejected"


def test_variation_value_bucket_is_case_insensitive() -> None:
    assert variation_value_bucket("  Approved ") == "agreed"


def test_variation_value_bucket_unknown_is_other_not_agreed() -> None:
    # An unexpected code must never be treated as agreed money.
    assert variation_value_bucket("some_new_state") == "other"
    assert variation_value_bucket(None) == "other"
    assert variation_value_bucket("") == "other"


# --- Plain labels + concept explanations ------------------------------------


def test_plain_status_label_known_and_fallback() -> None:
    assert plain_status_label("voided") == "Voided, carries no value"
    assert plain_status_label("in_progress") == "In progress"
    # Unmapped code reads cleanly rather than showing a raw snake_case token.
    assert plain_status_label("brand_new") == "Brand new"
    assert plain_status_label(None) == "Unknown"


def test_explain_variation_concept_known_and_unknown() -> None:
    for concept in (
        "agreed_value",
        "pending_value",
        "rejected_value",
        "time_impact",
        "contract_sum_movement",
        "revised_contract_sum",
        "percent_of_contract",
        "final_account",
    ):
        text = explain_variation_concept(concept)
        assert text and text.endswith(".")
        # Plain output only: no em-dash or en-dash punctuation.
        assert chr(0x2014) not in text
        assert chr(0x2013) not in text
    assert explain_variation_concept("nope") == ""


# --- Currency guard ----------------------------------------------------------


def test_assert_single_currency_returns_shared_code() -> None:
    rows = [_item("approved", "10", "EUR"), _item("approved", "20", "EUR")]
    assert assert_single_currency(rows) == "EUR"


def test_assert_single_currency_ignores_blank_codes() -> None:
    rows = [_item("approved", "10", ""), _item("approved", "20", "USD")]
    assert assert_single_currency(rows) == "USD"


def test_assert_single_currency_all_blank_returns_empty() -> None:
    rows = [_item("approved", "10", ""), _item("approved", "20", "")]
    assert assert_single_currency(rows) == ""


def test_assert_single_currency_mixed_raises_valueerror() -> None:
    rows = [_item("approved", "10", "EUR"), _item("approved", "20", "USD")]
    with pytest.raises(ValueError, match="mixed currencies"):
        assert_single_currency(rows)


# --- Roll-up by value status -------------------------------------------------


def test_rollup_by_value_status_groups_and_counts() -> None:
    rows = [
        _item("approved", "100", "GBP"),
        _item("completed", "50", "GBP"),
        _item("submitted", "30", "GBP"),
        _item("rejected", "999", "GBP"),
    ]
    out = rollup_by_value_status(rows)
    assert out["currency"] == "GBP"
    assert out["count"] == 4
    assert out["totals"]["agreed"] == Decimal("150")
    assert out["totals"]["pending"] == Decimal("30")
    assert out["totals"]["rejected"] == Decimal("999")
    assert out["counts"]["agreed"] == 2


def test_rollup_by_value_status_empty_is_all_zero() -> None:
    out = rollup_by_value_status([])
    assert out["count"] == 0
    assert out["currency"] == ""
    assert out["totals"] == {
        "agreed": Decimal("0"),
        "pending": Decimal("0"),
        "rejected": Decimal("0"),
        "other": Decimal("0"),
    }


def test_rollup_by_value_status_decimal_exact_no_float_drift() -> None:
    rows = [_item("approved", "0.1", "JPY"), _item("approved", "0.2", "JPY")]
    assert rollup_by_value_status(rows)["totals"]["agreed"] == Decimal("0.3")


def test_rollup_by_value_status_mixed_currency_raises() -> None:
    rows = [_item("approved", "10", "EUR"), _item("approved", "20", "USD")]
    with pytest.raises(ValueError, match="mixed currencies"):
        rollup_by_value_status(rows)


def test_rollup_by_value_status_ignores_none_rows() -> None:
    rows = [_item("approved", "10", "EUR"), None]
    assert rollup_by_value_status(rows)["count"] == 1


# --- Cumulative movement -----------------------------------------------------


def test_cumulative_movement_counts_agreed_only() -> None:
    rows = [
        _item("approved", "100", "EUR"),
        _item("submitted", "40", "EUR"),  # pending, excluded
        _item("rejected", "500", "EUR"),  # rejected, excluded
    ]
    assert cumulative_contract_sum_movement(rows) == Decimal("100")


def test_cumulative_movement_nets_credits() -> None:
    rows = [
        _item("approved", "100", "EUR"),
        _item("completed", "-30", "EUR"),  # agreed credit / omission
    ]
    assert cumulative_contract_sum_movement(rows) == Decimal("70")


def test_cumulative_movement_empty_is_zero() -> None:
    assert cumulative_contract_sum_movement([]) == Decimal("0")


# --- Percent of contract -----------------------------------------------------


def test_percent_of_contract_basic() -> None:
    assert percent_of_contract("150000", "1000000") == Decimal("15.00")


def test_percent_of_contract_negative_amount() -> None:
    assert percent_of_contract("-50000", "1000000") == Decimal("-5.00")


def test_percent_of_contract_zero_contract_raises() -> None:
    with pytest.raises(ValueError, match="undefined"):
        percent_of_contract("100", "0")


def test_percent_of_contract_none_contract_raises() -> None:
    with pytest.raises(ValueError, match="undefined"):
        percent_of_contract("100", None)


# --- Explainable contract-sum roll-up ---------------------------------------


def test_build_contract_sum_rollup_components() -> None:
    rows = [
        _item("approved", "200000", "EUR"),  # agreed addition
        _item("completed", "-50000", "EUR"),  # agreed omission
        _item("submitted", "80000", "EUR"),  # pending
        _item("rejected", "999999", "EUR"),  # rejected
    ]
    out = build_contract_sum_rollup("1000000", rows)
    assert out["currency"] == "EUR"
    assert out["original"] == Decimal("1000000")
    assert out["agreed_additions"] == Decimal("200000")
    assert out["agreed_omissions"] == Decimal("-50000")
    assert out["net_movement"] == Decimal("150000")
    assert out["pending"] == Decimal("80000")
    assert out["rejected"] == Decimal("999999")
    assert out["revised_contract_sum"] == Decimal("1150000")
    assert out["percent_movement"] == Decimal("15.00")
    assert "1150000" in out["summary"]
    assert chr(0x2014) not in out["summary"]


def test_build_contract_sum_rollup_empty_echoes_original() -> None:
    out = build_contract_sum_rollup("500000", [])
    assert out["net_movement"] == Decimal("0")
    assert out["revised_contract_sum"] == Decimal("500000")
    assert out["percent_movement"] == Decimal("0.00")
    assert out["summary"].endswith(".")


def test_build_contract_sum_rollup_zero_original_percent_is_none() -> None:
    rows = [_item("approved", "100", "EUR")]
    out = build_contract_sum_rollup("0", rows)
    # Zero contract sum must not divide; percent is a well-defined None.
    assert out["percent_movement"] is None
    assert out["revised_contract_sum"] == Decimal("100")


def test_build_contract_sum_rollup_decimal_exact() -> None:
    rows = [_item("approved", "0.1", "EUR"), _item("approved", "0.2", "EUR")]
    out = build_contract_sum_rollup("0.3", rows)
    assert out["net_movement"] == Decimal("0.3")
    assert out["revised_contract_sum"] == Decimal("0.6")


def test_build_contract_sum_rollup_currency_agnostic() -> None:
    # Works with any ISO code, nothing is hardcoded.
    for code in ("EUR", "USD", "JPY", "INR", "BRL", "NGN"):
        rows = [_item("approved", "100", code)]
        out = build_contract_sum_rollup("1000", rows)
        assert out["currency"] == code
        assert out["revised_contract_sum"] == Decimal("1100")


def test_build_contract_sum_rollup_expected_currency_mismatch_raises() -> None:
    rows = [_item("approved", "100", "USD")]
    with pytest.raises(ValueError, match="expected"):
        build_contract_sum_rollup("1000", rows, currency="EUR")


def test_build_contract_sum_rollup_mixed_currency_raises() -> None:
    rows = [_item("approved", "100", "USD"), _item("approved", "50", "EUR")]
    with pytest.raises(ValueError, match="mixed currencies"):
        build_contract_sum_rollup("1000", rows)
