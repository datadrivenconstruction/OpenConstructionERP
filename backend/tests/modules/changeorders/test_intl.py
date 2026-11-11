"""Pure helpers of the change order module: money parsing, pricing, rollups."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.changeorders import intl


def test_labels_fall_back_to_readable_code():
    assert intl.status_label("approved") == intl.CHANGE_ORDER_STATUS_LABELS["approved"]
    assert intl.status_label("on_hold") == "On hold"
    assert intl.status_label(None) == "Unknown"
    assert intl.approval_decision_label("") == "Unknown"
    assert intl.approval_decision_label("some_thing") == "Some thing"
    assert intl.reason_category_label(None) == "Unspecified"
    assert intl.reason_category_label("odd_one") == "Odd one"
    assert intl.change_type_label(None) == "Change"
    assert intl.change_type_label("x_y") == "X y"
    assert intl.variation_type_label("") == "Not yet typed"
    assert intl.variation_type_label("CLAIM") == intl.VARIATION_TYPE_LABELS["claim"]
    assert intl.variation_type_label("new_kind") == "New kind"


def test_label_dicts_have_known_codes():
    for code in intl.REASON_CATEGORIES:
        assert intl.reason_category_label(code)
    for code in intl.CHANGE_ORDER_STATUSES:
        assert intl.status_label(code)
    assert intl.VARIATION_TYPES[0] == "works_change"


@pytest.mark.parametrize("value", [None, "abc", "NaN", "Infinity", "1e15", "-1e15"])
def test_parse_money_rejects_bad_input(value):
    with pytest.raises(ValueError):
        intl.parse_money(value)


def test_parse_money_goes_through_str_for_floats():
    assert intl.parse_money(0.1) == Decimal("0.1")
    assert intl.parse_money("12.50") == Decimal("12.50")
    assert intl.parse_money(7) == Decimal(7)


def test_parse_non_negative_money():
    assert intl.parse_non_negative_money("0") == 0
    with pytest.raises(ValueError, match="non-negative"):
        intl.parse_non_negative_money("-1", "qty")


def test_round_money_half_up_and_currency_normalised():
    assert intl.round_money(Decimal("2.675")) == Decimal("2.68")
    assert intl.round_money(Decimal("-2.675")) == Decimal("-2.68")
    assert intl.normalize_currency(" eur ") == "EUR"
    assert intl.normalize_currency(None) == ""


def test_price_line_signed_delta_and_to_dict():
    credit = intl.price_line("10", "5", "10", "10")
    assert credit.cost_delta == Decimal("-50")
    assert credit.to_dict() == {"original_amount": "100.00", "new_amount": "50.00", "cost_delta": "-50.00"}
    with pytest.raises(ValueError):
        intl.price_line("-1", "1", "1", "1")


def test_line_cost_delta_prefers_components_over_precomputed():
    line = {"original_quantity": 1, "new_quantity": 3, "original_rate": 10, "new_rate": 10, "cost_delta": "999"}
    assert intl.line_cost_delta(line) == Decimal("20")
    assert intl.line_cost_delta({"cost_delta": "12.5"}) == Decimal("12.5")

    class Obj:
        cost_delta = "7"

    assert intl.line_cost_delta(Obj()) == Decimal("7")
    with pytest.raises(ValueError, match="quantity/rate"):
        intl.line_cost_delta({})


def test_price_change_order_markup_and_empty():
    lines = [{"cost_delta": "100"}, {"cost_delta": "-20"}]
    price = intl.price_change_order(lines, markup_pct="10", currency=" usd")
    assert price.net_lines_total == Decimal("80")
    assert price.markup_amount == Decimal("8")
    assert price.priced_total == Decimal("88")
    out = price.to_dict()
    assert out["currency"] == "USD"
    assert out["line_count"] == 2
    assert out["priced_total"] == "88.00"
    assert out["markup_pct"] == "10"

    empty = intl.price_change_order([])
    assert empty.priced_total == 0
    assert empty.currency == ""


@pytest.mark.parametrize("pct", ["-100.5", "1001", "abc", "NaN"])
def test_price_change_order_rejects_bad_markup(pct):
    with pytest.raises(ValueError):
        intl.price_change_order([], markup_pct=pct)


def test_totals_by_approval_status_orders_by_lifecycle():
    orders = [
        {"status": "approved", "cost_impact": "100", "currency": "EUR"},
        {"status": "draft", "cost_impact": "5", "currency": ""},
        {"status": "approved", "cost_impact": "50.5", "currency": "eur"},
        {"status": "weird", "cost_impact": "1"},
        {"status": "", "cost_impact": "2"},
    ]
    totals = intl.totals_by_approval_status(orders)
    keys = list(totals)
    assert keys.index("draft") < keys.index("approved")
    assert keys[-2:] == ["weird", "unknown"]
    assert totals["approved"].count == 2
    assert totals["approved"].to_dict()["total_cost_impact"] == "150.50"
    assert intl.totals_by_approval_status([]) == {}


def test_totals_refuse_mixed_currencies():
    orders = [{"status": "draft", "cost_impact": "1", "currency": "EUR"}, {"status": "draft", "currency": "USD"}]
    with pytest.raises(ValueError, match="across currencies"):
        intl.totals_by_approval_status(orders)
    with pytest.raises(ValueError, match="expected USD"):
        intl.totals_by_approval_status(orders[:1], currency="usd")


def test_contract_sum_effect_counts_only_approved():
    orders = [
        {"status": "approved", "cost_impact": "1000", "currency": "EUR"},
        {"status": "approved", "cost_impact": "-200"},
        {"status": "submitted", "cost_impact": "5000"},
    ]
    effect = intl.contract_sum_effect("10000", orders)
    assert effect.revised_contract_sum == Decimal("10800")
    assert effect.approved_count == 2
    assert effect.considered_count == 3
    assert effect.currency == "EUR"
    out = effect.to_dict()
    assert out["pct_change"] == "8"
    assert out["revised_contract_sum"] == "10800.00"


def test_contract_sum_effect_zero_original_has_undefined_percent():
    effect = intl.contract_sum_effect(0, [{"status": "approved", "cost_impact": "10"}])
    assert effect.pct_defined is False
    assert effect.to_dict()["pct_change"] is None
    assert effect.revised_contract_sum == Decimal("10")


def test_contract_sum_effect_validates_inputs():
    with pytest.raises(ValueError, match="counted_status"):
        intl.contract_sum_effect(1, [], counted_status="nope")
    with pytest.raises(ValueError, match="non-negative"):
        intl.contract_sum_effect(-1, [])
    submitted = intl.contract_sum_effect(
        100, [{"status": "submitted", "cost_impact": "10"}], counted_status="submitted"
    )
    assert submitted.approved_change_total == Decimal("10")
