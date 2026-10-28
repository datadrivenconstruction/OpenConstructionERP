# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure Monte Carlo cost-risk engine.

These exercise :mod:`app.modules.boq.cost_risk_engine` directly with plain
floats - no database, FastAPI or numpy - so they run on any interpreter, exactly
like the takeoff ``recognize`` tests. They lock in the statistical contract the
BOQ cost-risk panel depends on: ordered percentiles, reproducible seeds, an
honest variance decomposition that sums to 100%, and the headline property that
*systemic correlation widens the spread* (the whole reason for the upgrade).
"""

from __future__ import annotations

from app.modules.boq import cost_risk_engine as eng


def _pos(ordinal: str, base: float, *, dist: str = "pert") -> eng.PositionInput:
    return eng.PositionInput(ordinal=ordinal, description=f"Item {ordinal}", base=base, distribution=dist)


def _uniform_band(positions: list[eng.PositionInput], **kw) -> eng.CostRiskResult:
    return eng.simulate(positions, iterations=4000, optimistic_pct=30.0, pessimistic_pct=30.0, seed=7, **kw)


def test_empty_positions_return_insufficient() -> None:
    res = eng.simulate([], iterations=1000)
    assert res.convergence_status == "insufficient"
    assert res.base_total == 0
    assert res.recommended_budget == 0


def test_zero_base_total_is_safe() -> None:
    res = eng.simulate([_pos("1", 0.0), _pos("2", 0.0)], iterations=1000)
    assert res.base_total == 0
    assert res.drivers == []


def test_percentiles_are_monotonic() -> None:
    res = eng.simulate([_pos("1", 1000), _pos("2", 500), _pos("3", 250)], iterations=4000, seed=42)
    p = res.percentiles
    keys = ["p5", "p10", "p25", "p50", "p75", "p80", "p90", "p95"]
    values = [p[k] for k in keys]
    assert values == sorted(values), values
    assert p["p5"] > 0


def test_seed_is_reproducible() -> None:
    positions = [_pos("1", 800), _pos("2", 1200), _pos("3", 300)]
    a = eng.simulate(positions, iterations=3000, seed=123, correlation=0.3)
    b = eng.simulate(positions, iterations=3000, seed=123, correlation=0.3)
    assert a.mean == b.mean
    assert a.percentiles == b.percentiles
    assert a.std_dev == b.std_dev


def test_correlation_widens_the_spread() -> None:
    # Five identical lines, symmetric band. With the SAME seed the marginal
    # draws are identical; correlation only changes how they are paired, so any
    # increase in total spread is attributable to correlation alone.
    positions = [_pos(str(i), 100.0) for i in range(5)]
    independent = _uniform_band(positions, correlation=0.0)
    correlated = _uniform_band(positions, correlation=0.8)
    assert correlated.std_dev > independent.std_dev * 1.3, (
        independent.std_dev,
        correlated.std_dev,
    )
    # Means must stay essentially unchanged - correlation must not bias the total.
    assert abs(correlated.mean - independent.mean) < independent.mean * 0.02


def test_variance_contributions_sum_to_100() -> None:
    positions = [_pos("1", 1000), _pos("2", 700), _pos("3", 400), _pos("4", 200)]
    res = eng.simulate(positions, iterations=5000, seed=9, correlation=0.0)
    total = sum(d.contribution_pct for d in res.drivers)
    assert abs(total - 100.0) < 1.0, total


def test_largest_band_dominates_the_tornado() -> None:
    # Same base, very different uncertainty: the wide-band line must rank first.
    tight = eng.PositionInput(ordinal="TIGHT", description="tight", base=1000, low=950, mode=1000, high=1050)
    wide = eng.PositionInput(ordinal="WIDE", description="wide", base=1000, low=600, mode=1000, high=1600)
    res = eng.simulate([tight, wide], iterations=5000, seed=5, correlation=0.0)
    assert res.drivers[0].ordinal == "WIDE"
    assert res.drivers[0].contribution_pct > res.drivers[-1].contribution_pct


def test_recommended_budget_is_target_percentile() -> None:
    res = eng.simulate([_pos("1", 1000), _pos("2", 500)], iterations=4000, seed=11, target_confidence=80)
    assert res.recommended_budget == res.percentiles["p80"]
    assert res.contingency >= 0
    assert res.recommended_budget >= res.percentiles["p50"]


def test_symmetric_band_centers_probability_near_base() -> None:
    res = eng.simulate([_pos("1", 1000)], iterations=8000, optimistic_pct=20.0, pessimistic_pct=20.0, seed=3)
    # Symmetric PERT around the base -> the base sits near the median.
    assert 40.0 < res.prob_within_base < 60.0, res.prob_within_base


def test_triangular_distribution_respects_bounds() -> None:
    res = eng.simulate(
        [_pos("1", 1000, dist="triangular")],
        iterations=4000,
        optimistic_pct=10.0,
        pessimistic_pct=10.0,
        seed=8,
    )
    assert res.percentiles["p5"] >= 900.0 - 1e-6
    assert res.percentiles["p95"] <= 1100.0 + 1e-6


def test_histogram_counts_sum_to_iterations() -> None:
    res = eng.simulate([_pos("1", 500), _pos("2", 800)], iterations=3000, seed=2)
    assert sum(b.count for b in res.histogram) == 3000


def test_cdf_is_monotone_and_bounded() -> None:
    res = eng.simulate([_pos("1", 500), _pos("2", 800)], iterations=3000, seed=2)
    probs = [pt.cumulative_prob for pt in res.cdf]
    costs = [pt.cost for pt in res.cdf]
    assert probs[0] == 0.0 and abs(probs[-1] - 1.0) < 1e-9
    assert probs == sorted(probs)
    assert costs == sorted(costs)


def test_convergence_reports_insufficient_for_tiny_runs() -> None:
    res = eng.simulate([_pos("1", 500), _pos("2", 800)], iterations=100, seed=2)
    assert res.convergence_status == "insufficient"


def test_convergence_is_stable_for_large_runs() -> None:
    res = eng.simulate([_pos("1", 500), _pos("2", 800), _pos("3", 300)], iterations=20000, seed=2)
    assert res.convergence_status in {"converged", "marginal"}
    assert res.convergence_margin_pct < 2.0


def test_coefficient_of_variation_is_positive() -> None:
    res = eng.simulate([_pos("1", 1000), _pos("2", 1000)], iterations=4000, seed=4)
    assert res.cv_pct > 0
    assert res.std_dev > 0
