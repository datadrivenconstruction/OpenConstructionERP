# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Price adjustment: one country-neutral engine, the Egyptian Art. 97 formula as data.

Law 182/2018 Art. 47 makes price adjustment mandatory on public contracts of
six months or more, settled every three months. Executive Regulations Art. 97
give the formula: the value of the work in the period times the sum over the
variable items of coefficient times the relative change of its index (CAPMAS
producer prices), with every coefficient above zero and their sum below one,
so a fixed part of the price never moves. The worked example below is the one
in ``docs/design/egypt/contracts.md``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.modules.contracts.price_adjustment import (
    PRICE_ADJUSTMENT_REGIMES,
    PriceAdjustmentError,
    add_months,
    adjustment_dates,
    coefficient_problems,
    compute_adjustment,
    qualifies,
    regime_for,
)

_EG = "eg_law182_art97"
_COEFFICIENTS = [("cement", "0.15"), ("steel", "0.25"), ("labour", "0.20")]
_BASE = {"cement": "200", "steel": "300", "labour": "150"}
_NOW = {"cement": "230", "steel": "270", "labour": "165"}


def test_the_worked_example() -> None:
    result = compute_adjustment(_EG, "10000000", _COEFFICIENTS, _BASE, _NOW)
    by_item = {i.item: i.amount for i in result.items}
    # Cement +15 % x 0.15, steel -10 % x 0.25, labour +10 % x 0.20 = +0.0175.
    assert by_item == {
        "cement": Decimal("225000.00"),
        "steel": Decimal("-250000.00"),
        "labour": Decimal("200000.00"),
    }
    assert result.total == Decimal("175000.00")
    assert result.fixed_portion == Decimal("0.40")
    assert result.as_dict()["total"] == "175000.00"


def test_a_falling_market_is_a_deduction() -> None:
    result = compute_adjustment(_EG, "1000000", [("steel", "0.5")], {"steel": "300"}, {"steel": "240"})
    assert result.total == Decimal("-100000.00")


def test_the_egyptian_formula_equals_the_fidic_form_with_the_fixed_part() -> None:
    # FIDIC 13.8: Pn = a + sum(b * Ln/Lo), adjustment = V * (Pn - 1), with a = 1 - sum(b).
    result = compute_adjustment(_EG, "10000000", _COEFFICIENTS, _BASE, _NOW)
    pn = result.fixed_portion + sum(Decimal(c) * Decimal(_NOW[k]) / Decimal(_BASE[k]) for k, c in _COEFFICIENTS)
    assert (Decimal("10000000") * (pn - 1)).quantize(Decimal("0.01")) == result.total


@pytest.mark.parametrize(
    ("coefficients", "problem"),
    [
        ([], "no_coefficients"),
        ([("cement", "0.15"), ("steel", "0.70"), ("labour", "0.20")], "coefficient_sum_not_below_one"),
        ([("cement", "0.5"), ("steel", "0.5")], "coefficient_sum_not_below_one"),
        ([("cement", "0"), ("steel", "0.2")], "coefficient_not_positive"),
        ([("cement", "abc")], "coefficient_not_a_number"),
        ([("cement", "0.1"), ("Cement", "0.1")], "duplicate_item"),
    ],
)
def test_the_law_refuses_a_set_without_a_fixed_part_or_with_a_dead_item(coefficients: list, problem: str) -> None:
    problems = [p["problem"] for p in coefficient_problems(regime_for(_EG), coefficients)]
    assert problem in problems
    with pytest.raises(PriceAdjustmentError) as caught:
        compute_adjustment(_EG, "1000", coefficients, {"cement": "1", "steel": "1", "labour": "1"}, {})
    assert caught.value.problem == problems[0]


def test_the_contract_regime_allows_what_the_egyptian_law_refuses() -> None:
    # A plain contractual indexation may index the whole price, or carry an item at zero.
    assert coefficient_problems(regime_for("contract_indexation"), [("a", "0.5"), ("b", "0.5")]) == []
    assert coefficient_problems(regime_for("contract_indexation"), [("a", "0"), ("b", "0.3")]) == []
    assert [p["problem"] for p in coefficient_problems(regime_for("contract_indexation"), [("a", "1.2")])] == [
        "coefficient_sum_above_one"
    ]


def test_a_missing_index_or_a_zero_base_is_refused_rather_than_guessed() -> None:
    with pytest.raises(PriceAdjustmentError) as missing:
        compute_adjustment(_EG, "1000", [("steel", "0.3")], {"steel": "100"}, {})
    assert missing.value.problem == "missing_index"
    with pytest.raises(PriceAdjustmentError) as zero:
        compute_adjustment(_EG, "1000", [("steel", "0.3")], {"steel": "0"}, {"steel": "10"})
    assert zero.value.problem == "base_index_not_positive"
    with pytest.raises(PriceAdjustmentError) as unknown:
        compute_adjustment("nowhere", "1000", [("steel", "0.3")], {}, {})
    assert unknown.value.problem == "unknown_regime"


# ── Which contracts qualify, and when each quarter is settled ────────────────


def test_five_months_does_not_qualify_and_has_no_settlement() -> None:
    start, end = date(2026, 1, 15), date(2026, 6, 14)
    assert qualifies(_EG, start, end) is False
    assert adjustment_dates(_EG, start, start, end) == []


def test_exactly_six_months_qualifies() -> None:
    assert qualifies(_EG, date(2026, 1, 15), date(2026, 7, 15)) is True


def test_nine_months_settles_every_quarter_from_the_base_date() -> None:
    start, end = date(2026, 1, 15), date(2026, 10, 15)
    assert qualifies(_EG, start, end) is True
    assert adjustment_dates(_EG, start, start, end) == [date(2026, 4, 15), date(2026, 7, 15), date(2026, 10, 15)]


def test_an_unknown_date_is_not_read_as_no() -> None:
    assert qualifies(_EG, None, date(2026, 10, 15)) is None
    assert qualifies("contract_indexation", date(2026, 1, 1), date(2027, 1, 1)) is None


def test_a_month_end_base_date_clamps_to_the_shorter_month() -> None:
    assert add_months(date(2026, 11, 30), 3) == date(2027, 2, 28)


def test_the_regime_states_its_sources() -> None:
    regime = PRICE_ADJUSTMENT_REGIMES[_EG]
    assert regime["period_months"] == 3
    assert regime["min_duration_months"] == 6
    assert regime["coefficient_rule"] == "positive_sum_below_one"
    assert "Art. 97" in regime["statute"]
