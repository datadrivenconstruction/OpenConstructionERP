# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the cost-composition KPI math (bi_dashboards.kpis).

These exercise the pure, DB-free helpers that back the six cost-composition
tiles directly with fixture cost / EVM snapshots - no database, FastAPI or
ORM - exactly like the EVM formula and progress-math tests. The registered
async KPI wrappers only assemble the snapshot and delegate to these helpers,
so pinning the helpers pins the tiles.

Money stays ``Decimal`` end to end. Every division is guarded: the helper
returns ``None`` (composition returns ``{}``) when its denominator is absent,
which the async wrapper renders as the dashboard "no data" state rather than
a misleading 0. The tests pin the exact Decimal outputs, the None / empty
sentinels for zero and negative denominators, and the empty-input case.
"""

from __future__ import annotations

from decimal import Decimal

from app.modules.bi_dashboards.kpis import (
    KPI_FORMULAS,
    KPI_RECORD_PROVIDERS,
    SYSTEM_KPI_META,
    _budget_consumed_pct,
    _composition_percentages,
    _cost_per_period,
    _cost_per_unit,
    _eac_from_primitives,
    _pct_over_budget,
    list_system_kpis,
)

# The six cost-composition tiles this feature adds.
_COST_KPI_CODES = (
    "forecast_final_cost",
    "pct_over_budget",
    "budget_consumed_pct",
    "cost_per_day",
    "cost_per_m2",
    "cost_split_by_category",
)


def _d(value: str | int) -> Decimal:
    """Convert a value to Decimal. Mirrors service-layer money coercion."""
    return Decimal(str(value))


class TestForecastFinalCost:
    """Forecast final cost = EAC, reused from the EVM primitives."""

    def test_on_budget_project_forecasts_to_bac(self) -> None:
        # Perfect project: EV = AC = PV = BAC -> CPI = SPI = 1 -> EAC = BAC.
        eac = _eac_from_primitives(_d(500), _d(500), _d(500), _d(500))
        assert eac == _d(500)

    def test_not_started_forecasts_to_bac(self) -> None:
        # No actuals / no progress yet -> EAC falls back to the budget.
        eac = _eac_from_primitives(_d(1000), _d(0), _d(0), _d(0))
        assert eac == _d(1000)

    def test_over_running_project_forecasts_above_bac(self) -> None:
        # BAC=1000, PV=1000, EV=500, AC=500 -> CPI=1, SPI=0.5 (behind).
        # EAC = 500 + (1000-500)/(1*0.5) = 500 + 1000 = 1500.
        eac = _eac_from_primitives(_d(1000), _d(1000), _d(500), _d(500))
        assert eac == _d(1500)
        assert isinstance(eac, Decimal)


class TestPctOverBudget:
    """(forecast - BAC) / BAC * 100. Positive = over budget."""

    def test_over_budget_is_positive(self) -> None:
        assert _pct_over_budget(_d(1000), _d(1150)) == _d(15)

    def test_under_budget_is_negative(self) -> None:
        assert _pct_over_budget(_d(1000), _d(900)) == _d(-10)

    def test_on_budget_is_zero(self) -> None:
        assert _pct_over_budget(_d(1000), _d(1000)) == _d(0)

    def test_chains_from_forecast_final_cost(self) -> None:
        # EAC=1500 against BAC=1000 -> 50% over.
        eac = _eac_from_primitives(_d(1000), _d(1000), _d(500), _d(500))
        assert _pct_over_budget(_d(1000), eac) == _d(50)

    def test_zero_bac_returns_none(self) -> None:
        assert _pct_over_budget(_d(0), _d(500)) is None

    def test_negative_bac_returns_none(self) -> None:
        assert _pct_over_budget(_d(-10), _d(500)) is None

    def test_result_is_decimal(self) -> None:
        assert isinstance(_pct_over_budget(_d(1000), _d(1150)), Decimal)


class TestBudgetConsumedPct:
    """AC / BAC * 100. May exceed 100 on overrun."""

    def test_partial_consumption(self) -> None:
        assert _budget_consumed_pct(_d(1000), _d(400)) == _d(40)

    def test_full_consumption(self) -> None:
        assert _budget_consumed_pct(_d(1000), _d(1000)) == _d(100)

    def test_overrun_exceeds_hundred(self) -> None:
        assert _budget_consumed_pct(_d(1000), _d(1200)) == _d(120)

    def test_nothing_spent_is_zero(self) -> None:
        assert _budget_consumed_pct(_d(1000), _d(0)) == _d(0)

    def test_zero_bac_returns_none(self) -> None:
        assert _budget_consumed_pct(_d(0), _d(400)) is None

    def test_negative_bac_returns_none(self) -> None:
        assert _budget_consumed_pct(_d(-1), _d(400)) is None


class TestCostPerPeriod:
    """Cost velocity / burn rate: AC / elapsed days."""

    def test_daily_burn(self) -> None:
        assert _cost_per_period(_d(9000), _d(30)) == _d(300)

    def test_zero_actual_cost_is_zero(self) -> None:
        assert _cost_per_period(_d(0), _d(30)) == _d(0)

    def test_zero_elapsed_returns_none(self) -> None:
        assert _cost_per_period(_d(9000), _d(0)) is None

    def test_negative_elapsed_returns_none(self) -> None:
        # Start date in the future -> no meaningful velocity.
        assert _cost_per_period(_d(9000), _d(-5)) is None

    def test_result_is_decimal(self) -> None:
        assert isinstance(_cost_per_period(_d(9000), _d(30)), Decimal)


class TestCostPerUnit:
    """Unit cost: AC / gross floor area (m2)."""

    def test_cost_per_m2(self) -> None:
        assert _cost_per_unit(_d(500000), _d(1000)) == _d(500)

    def test_zero_area_returns_none(self) -> None:
        assert _cost_per_unit(_d(500000), _d(0)) is None

    def test_negative_area_returns_none(self) -> None:
        assert _cost_per_unit(_d(500000), _d(-1)) is None

    def test_zero_cost_is_zero(self) -> None:
        assert _cost_per_unit(_d(0), _d(1000)) == _d(0)


class TestCompositionPercentages:
    """Labor / material / equipment split as percentages of the total."""

    def test_clean_three_way_split(self) -> None:
        result = _composition_percentages(
            {"labor": _d(300), "material": _d(500), "equipment": _d(200)},
        )
        assert result["labor"] == _d(30)
        assert result["material"] == _d(50)
        assert result["equipment"] == _d(20)

    def test_percentages_sum_to_one_hundred(self) -> None:
        result = _composition_percentages(
            {"labor": _d(300), "material": _d(500), "equipment": _d(200)},
        )
        assert sum(result.values(), Decimal("0")) == _d(100)

    def test_repeating_decimal_is_deterministic(self) -> None:
        # 1 : 2 split -> shares are non-terminating; assert against the exact
        # same Decimal expression the helper uses (no rounding surprise).
        result = _composition_percentages({"a": _d(1), "b": _d(2)})
        assert result["a"] == _d(1) / _d(3) * Decimal("100")
        assert result["b"] == _d(2) / _d(3) * Decimal("100")

    def test_negative_category_kept_when_total_positive(self) -> None:
        # A credit note can push one category negative; total stays positive.
        result = _composition_percentages({"labor": _d(120), "credit": _d(-20)})
        assert result["labor"] == _d(120)
        assert result["credit"] == _d(-20)

    def test_empty_input_returns_empty(self) -> None:
        assert _composition_percentages({}) == {}

    def test_all_zero_returns_empty(self) -> None:
        assert _composition_percentages({"labor": _d(0), "material": _d(0)}) == {}

    def test_non_positive_total_returns_empty(self) -> None:
        assert _composition_percentages({"labor": _d(-10), "material": _d(-5)}) == {}

    def test_values_are_decimal(self) -> None:
        result = _composition_percentages({"labor": _d(300), "material": _d(700)})
        assert all(isinstance(v, Decimal) for v in result.values())


class TestRegistration:
    """The six tiles must be wired to the shared registry so the existing
    ``/kpis/{code}/compute`` endpoint, the KPI catalog seed and the
    drill-down all pick them up with no new endpoint or migration."""

    def test_all_codes_have_a_formula(self) -> None:
        for code in _COST_KPI_CODES:
            assert code in KPI_FORMULAS, f"{code} is not registered as a KPI formula"

    def test_all_codes_are_seeded_metadata(self) -> None:
        seeded = {meta["code"] for meta in list_system_kpis()}
        for code in _COST_KPI_CODES:
            assert code in SYSTEM_KPI_META
            assert code in seeded, f"{code} missing from list_system_kpis (seed source)"

    def test_all_codes_have_a_drilldown_provider(self) -> None:
        for code in _COST_KPI_CODES:
            assert code in KPI_RECORD_PROVIDERS, f"{code} has no drill-down provider"

    def test_metadata_units_and_category(self) -> None:
        expected_unit = {
            "forecast_final_cost": "currency",
            "pct_over_budget": "percent",
            "budget_consumed_pct": "percent",
            "cost_per_day": "currency",
            "cost_per_m2": "currency",
            "cost_split_by_category": "percent",
        }
        for code, unit in expected_unit.items():
            meta = SYSTEM_KPI_META[code]
            assert meta["unit"] == unit, f"{code} unit {meta['unit']} != {unit}"
            assert meta["category"] == "cost"
