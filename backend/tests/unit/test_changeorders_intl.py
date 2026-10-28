# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the change orders international helpers (app.modules.changeorders.intl).

Pure functions, no database. These cover the international-robustness contract:
Decimal-exact money, no hardcoded currency, never summing across currency codes,
markup as an explicit parameter, and clean ValueError for edge cases instead of
500 / NaN / inf.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.changeorders.intl import (
    CHANGE_ORDER_STATUSES,
    ChangeOrderPrice,
    ContractSumEffect,
    approval_decision_label,
    change_type_label,
    contract_sum_effect,
    explain_contract_impact,
    explain_priced_value,
    explain_time_extension,
    line_cost_delta,
    normalize_currency,
    parse_money,
    parse_non_negative_money,
    price_change_order,
    price_line,
    reason_category_label,
    round_money,
    status_label,
    totals_by_approval_status,
)


def _order(status: str, cost_impact: str, currency: str = "") -> dict[str, str]:
    return {"status": status, "cost_impact": cost_impact, "currency": currency}


# -- labels + explainers ------------------------------------------------------


def test_status_label_known_and_unknown() -> None:
    assert "Approved" in status_label("approved")
    assert status_label("weird_code") == "Weird code"
    assert status_label("") == "Unknown"
    assert status_label(None) == "Unknown"


def test_decision_reason_change_type_labels() -> None:
    assert "accepted" in approval_decision_label("approved").lower()
    assert "client" in reason_category_label("client_request").lower()
    assert "credit" in change_type_label("removed").lower()
    # Unknown codes never blank out.
    assert reason_category_label("") == "Unspecified"
    assert change_type_label(None) == "Change"


def test_explainers_are_one_line_plain_text() -> None:
    for text in (explain_priced_value(), explain_contract_impact()):
        assert "\n" not in text
        assert len(text) > 20
    assert "No time extension" in explain_time_extension(0)
    assert "1 day" in explain_time_extension(1)
    assert "5 days" in explain_time_extension(5)
    # Bad input degrades to the no-extension message, never crashes.
    assert "No time extension" in explain_time_extension(None)


# -- money primitives ---------------------------------------------------------


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity", "1e1000", "garbage", None])
def test_parse_money_rejects_bad_values(bad: object) -> None:
    with pytest.raises(ValueError):
        parse_money(bad)


def test_parse_money_is_decimal_exact() -> None:
    # A float 0.1 must not enter as 0.1000000000000000055...
    assert parse_money(0.1) == Decimal("0.1")
    assert parse_money("1250.50") == Decimal("1250.50")
    assert parse_money(-500) == Decimal("-500")


def test_parse_non_negative_money_rejects_negative() -> None:
    with pytest.raises(ValueError):
        parse_non_negative_money("-1")
    assert parse_non_negative_money("0") == Decimal("0")


def test_round_money_half_up_two_dp() -> None:
    assert round_money(Decimal("1.005")) == Decimal("1.01")
    assert round_money(Decimal("2.344")) == Decimal("2.34")


def test_normalize_currency() -> None:
    assert normalize_currency(" usd ") == "USD"
    assert normalize_currency(None) == ""
    assert normalize_currency("") == ""


# -- line pricing -------------------------------------------------------------


def test_price_line_positive_delta() -> None:
    lp = price_line("10", "12", "100", "100")
    assert lp.original_amount == Decimal("1000")
    assert lp.new_amount == Decimal("1200")
    assert lp.cost_delta == Decimal("200")


def test_price_line_credit_is_negative() -> None:
    lp = price_line("10", "4", "50", "50")
    assert lp.cost_delta == Decimal("-300")
    assert lp.to_dict()["cost_delta"] == "-300.00"


def test_price_line_rejects_negative_inputs() -> None:
    with pytest.raises(ValueError):
        price_line("-1", "2", "3", "4")


def test_line_cost_delta_from_components_or_precomputed() -> None:
    from_components = line_cost_delta(
        {"original_quantity": "1", "new_quantity": "2", "original_rate": "10", "new_rate": "10"}
    )
    assert from_components == Decimal("10")
    # Precomputed cost_delta used as-is when quantities/rates absent.
    assert line_cost_delta({"cost_delta": "42.50"}) == Decimal("42.50")


def test_line_cost_delta_requires_some_signal() -> None:
    with pytest.raises(ValueError):
        line_cost_delta({"description": "nothing priced"})


# -- change order priced total (lines + markup) -------------------------------


def test_price_change_order_default_markup_is_zero() -> None:
    lines = [
        {"cost_delta": "1000"},
        {"cost_delta": "500"},
    ]
    priced = price_change_order(lines, currency="USD")
    assert isinstance(priced, ChangeOrderPrice)
    assert priced.net_lines_total == Decimal("1500")
    assert priced.markup_amount == Decimal("0")
    assert priced.priced_total == Decimal("1500")
    assert priced.currency == "USD"
    assert priced.line_count == 2


def test_price_change_order_applies_markup() -> None:
    priced = price_change_order([{"cost_delta": "1000"}], markup_pct="15", currency="gbp")
    assert priced.markup_amount == Decimal("150")
    assert priced.priced_total == Decimal("1150")
    assert priced.currency == "GBP"
    d = priced.to_dict()
    assert d["priced_total"] == "1150.00"
    assert d["markup_pct"] == "15"


def test_price_change_order_empty_is_zero_not_error() -> None:
    priced = price_change_order([], markup_pct="10", currency="EUR")
    assert priced.net_lines_total == Decimal("0")
    assert priced.priced_total == Decimal("0")
    assert priced.line_count == 0


def test_price_change_order_negative_markup_is_discount() -> None:
    priced = price_change_order([{"cost_delta": "1000"}], markup_pct="-10")
    assert priced.priced_total == Decimal("900")


@pytest.mark.parametrize("bad", ["NaN", "-101", "2000", "junk"])
def test_price_change_order_rejects_bad_markup(bad: str) -> None:
    with pytest.raises(ValueError):
        price_change_order([{"cost_delta": "1000"}], markup_pct=bad)


def test_price_change_order_decimal_exact_no_float_drift() -> None:
    # 0.1 + 0.2 must be exact 0.30, not 0.30000000000000004.
    priced = price_change_order([{"cost_delta": "0.1"}, {"cost_delta": "0.2"}])
    assert priced.net_lines_total == Decimal("0.3")


# -- totals by approval status ------------------------------------------------


def test_totals_by_approval_status_groups_and_sums() -> None:
    orders = [
        _order("approved", "1000", "USD"),
        _order("approved", "500", "USD"),
        _order("draft", "250", "USD"),
        _order("rejected", "99", "USD"),
    ]
    totals = totals_by_approval_status(orders)
    assert totals["approved"].count == 2
    assert totals["approved"].total_cost_impact == Decimal("1500")
    assert totals["draft"].count == 1
    assert totals["rejected"].total_cost_impact == Decimal("99")
    # Ordering follows the canonical lifecycle.
    assert list(totals.keys()) == ["draft", "approved", "rejected"]


def test_totals_by_approval_status_empty_is_empty_dict() -> None:
    assert totals_by_approval_status([]) == {}


def test_totals_by_approval_status_rejects_currency_mix() -> None:
    orders = [_order("approved", "1000", "USD"), _order("approved", "500", "EUR")]
    with pytest.raises(ValueError):
        totals_by_approval_status(orders)


def test_totals_by_approval_status_empty_currency_is_not_a_conflict() -> None:
    orders = [_order("approved", "1000", ""), _order("approved", "500", "USD")]
    totals = totals_by_approval_status(orders)
    assert totals["approved"].total_cost_impact == Decimal("1500")


def test_totals_by_approval_status_explicit_currency_mismatch_raises() -> None:
    orders = [_order("approved", "1000", "USD")]
    with pytest.raises(ValueError):
        totals_by_approval_status(orders, currency="EUR")


# -- contract sum effect ------------------------------------------------------


def test_contract_sum_effect_only_approved_moves_the_sum() -> None:
    orders = [
        _order("approved", "1000", "USD"),
        _order("approved", "500", "USD"),
        _order("submitted", "9999", "USD"),
        _order("rejected", "7777", "USD"),
    ]
    eff = contract_sum_effect("100000", orders, currency="USD")
    assert isinstance(eff, ContractSumEffect)
    assert eff.approved_change_total == Decimal("1500")
    assert eff.revised_contract_sum == Decimal("101500")
    assert eff.approved_count == 2
    assert eff.considered_count == 4
    assert eff.pct_defined is True
    assert eff.pct_change == Decimal("1.5")


def test_contract_sum_effect_credit_lowers_the_sum() -> None:
    orders = [_order("approved", "-2000", "EUR")]
    eff = contract_sum_effect("50000", orders, currency="EUR")
    assert eff.revised_contract_sum == Decimal("48000")
    assert eff.pct_change == Decimal("-4")


def test_contract_sum_effect_zero_original_guards_division() -> None:
    orders = [_order("approved", "1000", "USD")]
    eff = contract_sum_effect("0", orders, currency="USD")
    assert eff.revised_contract_sum == Decimal("1000")
    assert eff.pct_defined is False
    assert eff.pct_change == Decimal("0")
    assert eff.to_dict()["pct_change"] is None


def test_contract_sum_effect_empty_orders() -> None:
    eff = contract_sum_effect("100000", [], currency="USD")
    assert eff.approved_change_total == Decimal("0")
    assert eff.revised_contract_sum == Decimal("100000")
    assert eff.pct_change == Decimal("0")


def test_contract_sum_effect_rejects_negative_original() -> None:
    with pytest.raises(ValueError):
        contract_sum_effect("-1", [], currency="USD")


def test_contract_sum_effect_rejects_currency_mix() -> None:
    orders = [_order("approved", "1000", "USD"), _order("approved", "500", "JPY")]
    with pytest.raises(ValueError):
        contract_sum_effect("100000", orders, currency="USD")


def test_contract_sum_effect_rejects_unknown_counted_status() -> None:
    with pytest.raises(ValueError):
        contract_sum_effect("100000", [], currency="USD", counted_status="banana")


def test_contract_sum_effect_custom_counted_status() -> None:
    orders = [_order("executed", "3000", "USD"), _order("approved", "1000", "USD")]
    eff = contract_sum_effect("10000", orders, currency="USD", counted_status="executed")
    assert eff.approved_change_total == Decimal("3000")
    assert eff.approved_count == 1


def test_no_currency_is_hardcoded_anywhere() -> None:
    # A change order priced with no currency stays unspecified, never a default.
    priced = price_change_order([{"cost_delta": "10"}])
    assert priced.currency == ""
    eff = contract_sum_effect("100", [], currency=None)
    assert eff.currency == ""


def test_lifecycle_constant_shape() -> None:
    assert CHANGE_ORDER_STATUSES[0] == "draft"
    assert "executed" in CHANGE_ORDER_STATUSES
