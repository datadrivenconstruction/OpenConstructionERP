# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure Monte Carlo schedule-risk engine.

These exercise :mod:`app.modules.schedule_advanced.schedule_risk_engine`
directly with plain :class:`~cpm.Activity` values - no database, FastAPI or
numpy - so they run on any interpreter, exactly like the cost-risk and takeoff
``recognize`` tests. They lock in the statistical contract the schedule-risk
panel depends on: ordered finish-date percentiles, reproducible seeds,
criticality indices that capture path-switching, correlation that widens the
spread, discrete events that shift the mean by ~probability x impact, and a
Joint Confidence Level that respects the cost/schedule dependence.
"""

from __future__ import annotations

import pytest

from app.modules.schedule_advanced import schedule_risk_engine as eng
from app.modules.schedule_advanced.cpm import Activity, CycleError, TaskNetwork, compute_cpm

# ── Fixtures / helpers ───────────────────────────────────────────────────────


def _chain(durations: list[int]) -> list[Activity]:
    """A straight FS chain A->B->C->... with the given durations."""
    acts: list[Activity] = []
    prev: str | None = None
    for i, d in enumerate(durations):
        aid = chr(ord("A") + i)
        preds = [(prev, "FS", 0)] if prev is not None else []
        acts.append(Activity(id=aid, duration=d, predecessors=preds))
        prev = aid
    return acts


def _risk(aid: str, base: float, low: float, mode: float, high: float, dist: str = "pert") -> eng.ActivityDurationInput:
    return eng.ActivityDurationInput(activity_id=aid, base=base, low=low, mode=mode, high=high, distribution=dist)


def _det_finish(activities: list[Activity]) -> float:
    """Deterministic finish via the canonical compute_cpm (cross-check)."""
    res = compute_cpm(TaskNetwork(activities))
    return float(max(r.ef for r in res.values()))


# ── Reproducibility ──────────────────────────────────────────────────────────


def test_seed_is_reproducible() -> None:
    acts = _chain([10, 5, 8])
    risks = [_risk("A", 10, 7, 10, 16), _risk("B", 5, 3, 5, 9), _risk("C", 8, 6, 8, 13)]
    a = eng.simulate_schedule(acts, None, risks, [], iterations=3000, seed=123, correlation=0.3)
    b = eng.simulate_schedule(acts, None, risks, [], iterations=3000, seed=123, correlation=0.3)
    assert a.percentiles == b.percentiles
    assert a.mean == b.mean
    assert a.std_dev == b.std_dev
    assert [c.criticality_index for c in a.criticality] == [c.criticality_index for c in b.criticality]


def test_no_seed_is_still_deterministic() -> None:
    # When no seed is given one is derived from the inputs, so two calls agree.
    acts = _chain([10, 5, 8])
    risks = [_risk("A", 10, 7, 10, 16)]
    a = eng.simulate_schedule(acts, None, risks, [], iterations=2000)
    b = eng.simulate_schedule(acts, None, risks, [], iterations=2000)
    assert a.seed == b.seed
    assert a.percentiles == b.percentiles


def test_jcl_is_reproducible() -> None:
    acts = _chain([10, 5, 8])
    risks = [_risk("A", 10, 7, 10, 16), _risk("B", 5, 3, 5, 9)]
    cost = eng.CostInputs(base_cost=100000, cost_low=85000, cost_mode=100000, cost_high=140000)
    a = eng.simulate_schedule(acts, None, risks, [], iterations=3000, seed=7, correlation=0.4, cost_inputs=cost)
    b = eng.simulate_schedule(acts, None, risks, [], iterations=3000, seed=7, correlation=0.4, cost_inputs=cost)
    assert a.joint_confidence is not None and b.joint_confidence is not None
    assert a.joint_confidence.jcl == b.joint_confidence.jcl


# ── Percentile contract ──────────────────────────────────────────────────────


def test_percentiles_are_monotonic_and_above_minimum() -> None:
    acts = _chain([10, 5, 8])
    risks = [_risk("A", 10, 8, 10, 15), _risk("B", 5, 4, 5, 8), _risk("C", 8, 6, 8, 12)]
    res = eng.simulate_schedule(acts, None, risks, [], iterations=4000, seed=42)
    keys = ["p5", "p10", "p25", "p50", "p75", "p80", "p90", "p95"]
    values = [res.percentiles[k] for k in keys]
    assert values == sorted(values), values
    # Every sampled finish must be >= the deterministic minimum finish, which is
    # the sum of the optimistic bounds along the only path: 8 + 4 + 6 = 18.
    assert res.percentiles["p5"] >= 18.0 - 1e-6


def test_recommended_finish_is_target_percentile() -> None:
    acts = _chain([10, 5])
    risks = [_risk("A", 10, 8, 10, 16), _risk("B", 5, 4, 5, 9)]
    res = eng.simulate_schedule(acts, None, risks, [], iterations=4000, seed=11, target_confidence=80)
    assert res.recommended_finish == res.percentiles["p80"]
    assert res.recommended_finish >= res.percentiles["p50"]


# ── Deterministic collapse ───────────────────────────────────────────────────


def test_zero_width_bands_collapse_to_deterministic_finish() -> None:
    # No band (low==mode==high) and no events -> every iteration is the
    # deterministic CPM finish, criticality on-path == 1, off-path == 0.
    # A->B->C is the long path (10+5+8=23); D hangs off A (A->D, dur 2) -> not
    # critical (its EF 12 << project finish 23).
    acts = [
        Activity(id="A", duration=10, predecessors=[]),
        Activity(id="B", duration=5, predecessors=[("A", "FS", 0)]),
        Activity(id="C", duration=8, predecessors=[("B", "FS", 0)]),
        Activity(id="D", duration=2, predecessors=[("A", "FS", 0)]),
    ]
    det = _det_finish(acts)
    risks = [
        _risk("A", 10, 10, 10, 10),
        _risk("B", 5, 5, 5, 5),
        _risk("C", 8, 8, 8, 8),
        _risk("D", 2, 2, 2, 2),
    ]
    res = eng.simulate_schedule(acts, None, risks, [], iterations=1000, seed=1)
    assert res.std_dev == pytest.approx(0.0, abs=1e-9)
    assert res.mean == pytest.approx(det)
    assert all(p == pytest.approx(det) for p in res.percentiles.values())
    ci = {c.activity_id: c.criticality_index for c in res.criticality}
    assert ci["A"] == 1.0 and ci["B"] == 1.0 and ci["C"] == 1.0
    assert ci["D"] == 0.0


def test_default_band_when_no_risk_entry() -> None:
    # Activities with no risk entry still get a band from the global percentages,
    # so the finish is uncertain even with an empty activity_risks list.
    acts = _chain([10, 10])
    res = eng.simulate_schedule(acts, None, [], [], iterations=3000, seed=2)
    assert res.std_dev > 0
    assert res.deterministic_finish == pytest.approx(20.0)


# ── Criticality index ────────────────────────────────────────────────────────


def test_criticality_index_in_unit_interval() -> None:
    acts = _chain([10, 5, 8])
    risks = [_risk("A", 10, 7, 10, 16), _risk("B", 5, 3, 5, 9), _risk("C", 8, 6, 8, 13)]
    res = eng.simulate_schedule(acts, None, risks, [], iterations=3000, seed=3)
    for c in res.criticality:
        assert 0.0 <= c.criticality_index <= 1.0
        assert 0.0 <= c.cruciality <= 1.0


def test_near_parallel_paths_share_criticality() -> None:
    # Two near-equal parallel paths from START to END:
    #   START -> P1 -> END   (P1 ~ 20 days)
    #   START -> P2 -> END   (P2 ~ 20 days)
    # With overlapping duration bands either path can win, so BOTH P1 and P2 must
    # have a criticality index strictly between 0 and 1 (path-switching).
    acts = [
        Activity(id="START", duration=1, predecessors=[]),
        Activity(id="P1", duration=20, predecessors=[("START", "FS", 0)]),
        Activity(id="P2", duration=20, predecessors=[("START", "FS", 0)]),
        Activity(id="END", duration=1, predecessors=[("P1", "FS", 0), ("P2", "FS", 0)]),
    ]
    risks = [
        _risk("P1", 20, 14, 20, 28),
        _risk("P2", 20, 14, 20, 28),
    ]
    res = eng.simulate_schedule(acts, None, risks, [], iterations=5000, seed=4, correlation=0.0)
    ci = {c.activity_id: c.criticality_index for c in res.criticality}
    assert 0.0 < ci["P1"] < 1.0, ci
    assert 0.0 < ci["P2"] < 1.0, ci
    # START and END are on every path, so they are always critical.
    assert ci["START"] == 1.0
    assert ci["END"] == 1.0
    # The two symmetric paths should split criticality roughly evenly.
    assert abs(ci["P1"] - ci["P2"]) < 0.15, ci


def test_always_critical_chain_has_unit_index() -> None:
    acts = _chain([10, 5, 8])
    risks = [_risk("A", 10, 7, 10, 16), _risk("B", 5, 3, 5, 9), _risk("C", 8, 6, 8, 13)]
    res = eng.simulate_schedule(acts, None, risks, [], iterations=2000, seed=5)
    # A single chain: every activity is on the only path every iteration.
    for c in res.criticality:
        assert c.criticality_index == 1.0


# ── Correlation widens the spread ────────────────────────────────────────────


def test_correlation_widens_the_spread() -> None:
    # A chain of five uncertain activities. Correlated duration overruns stack
    # along the single path, so higher rho -> larger finish std-dev, with the
    # mean essentially unchanged (correlation reorders, never rebiases).
    acts = _chain([10, 10, 10, 10, 10])
    risks = [_risk(chr(ord("A") + i), 10, 6, 10, 16) for i in range(5)]
    independent = eng.simulate_schedule(acts, None, risks, [], iterations=5000, seed=7, correlation=0.0)
    correlated = eng.simulate_schedule(acts, None, risks, [], iterations=5000, seed=7, correlation=0.85)
    assert correlated.std_dev > independent.std_dev * 1.3, (independent.std_dev, correlated.std_dev)
    assert abs(correlated.mean - independent.mean) < independent.mean * 0.02


# ── Discrete risk events ─────────────────────────────────────────────────────


def test_series_event_shifts_mean_by_prob_times_impact() -> None:
    # An always-critical chain. A risk event with probability p adds D days
    # (fixed impact band collapses to D) to a critical activity in series, so the
    # mean finish rises by ~ p * D over the no-event baseline.
    acts = _chain([10, 5, 8])
    risks = [
        _risk("A", 10, 10, 10, 10),
        _risk("B", 5, 5, 5, 5),
        _risk("C", 8, 8, 8, 8),
    ]
    baseline = eng.simulate_schedule(acts, None, risks, [], iterations=8000, seed=8)
    p, d = 0.5, 10.0
    event = eng.RiskEvent(
        event_id="E1",
        probability=p,
        impact_low=d,
        impact_mode=d,
        impact_high=d,
        affected_activity_ids=["B"],
        application_mode="series",
    )
    with_event = eng.simulate_schedule(acts, None, risks, [event], iterations=8000, seed=8)
    shift = with_event.mean - baseline.mean
    assert shift == pytest.approx(p * d, abs=0.6), shift


def test_parallel_event_shifts_less_than_series() -> None:
    # An event affecting two parallel activities: in series it lands on BOTH; in
    # parallel only on the driving one. On a path where both feed the same
    # successor, parallel lifts the finish no more than series does.
    acts = [
        Activity(id="START", duration=1, predecessors=[]),
        Activity(id="P1", duration=20, predecessors=[("START", "FS", 0)]),
        Activity(id="P2", duration=20, predecessors=[("START", "FS", 0)]),
        Activity(id="END", duration=1, predecessors=[("P1", "FS", 0), ("P2", "FS", 0)]),
    ]
    risks = [_risk("P1", 20, 18, 20, 24), _risk("P2", 20, 18, 20, 24)]
    base_ev = dict(
        event_id="E",
        probability=0.8,
        impact_low=8.0,
        impact_mode=8.0,
        impact_high=8.0,
        affected_activity_ids=["P1", "P2"],
    )
    series = eng.simulate_schedule(
        acts, None, risks, [eng.RiskEvent(application_mode="series", **base_ev)], iterations=6000, seed=9
    )
    parallel = eng.simulate_schedule(
        acts, None, risks, [eng.RiskEvent(application_mode="parallel", **base_ev)], iterations=6000, seed=9
    )
    assert parallel.mean <= series.mean + 1e-6, (parallel.mean, series.mean)
    # And both must exceed the no-event mean (the event does delay the project).
    no_event = eng.simulate_schedule(acts, None, risks, [], iterations=6000, seed=9)
    assert parallel.mean > no_event.mean


# ── Joint Confidence Level ───────────────────────────────────────────────────


def test_jcl_exceeds_product_under_positive_correlation() -> None:
    # When cost and schedule share a positive correlation driver you tend to be
    # lucky (or unlucky) on BOTH at once, so the probability of hitting both
    # marginal targets is HIGHER than the independent product. (The PM-folklore
    # "JCL is worse than naive" refers to the contingency needed to reach a fixed
    # joint confidence, not the probability at the marginal point - see
    # _build_joint_confidence.) This is the FKG / positive-association property:
    # P(A and B) >= P(A) P(B) for the decreasing events {finish<=t}, {cost<=c}.
    acts = _chain([10, 5, 8])
    risks = [_risk("A", 10, 7, 10, 16), _risk("B", 5, 3, 5, 9), _risk("C", 8, 6, 8, 13)]
    cost = eng.CostInputs(base_cost=100000, cost_low=80000, cost_mode=100000, cost_high=150000)
    res = eng.simulate_schedule(acts, None, risks, [], iterations=8000, seed=10, correlation=0.7, cost_inputs=cost)
    jc = res.joint_confidence
    assert jc is not None
    product = jc.prob_on_time * jc.prob_on_budget
    assert jc.jcl >= product - 0.02, (jc.jcl, product)  # >= product (MC slack)
    assert jc.jcl > product + 0.02  # and meaningfully above it under rho=0.7
    assert jc.correlation > 0.2  # the shared driver really did correlate them


def test_jcl_approximates_product_at_zero_correlation() -> None:
    acts = _chain([10, 5, 8])
    risks = [_risk("A", 10, 7, 10, 16), _risk("B", 5, 3, 5, 9), _risk("C", 8, 6, 8, 13)]
    cost = eng.CostInputs(base_cost=100000, cost_low=80000, cost_mode=100000, cost_high=150000)
    res = eng.simulate_schedule(acts, None, risks, [], iterations=10000, seed=11, correlation=0.0, cost_inputs=cost)
    jc = res.joint_confidence
    assert jc is not None
    product = jc.prob_on_time * jc.prob_on_budget
    # Independent: joint ~ product (allow Monte-Carlo slack).
    assert abs(jc.jcl - product) < 0.04, (jc.jcl, product)
    assert abs(jc.correlation) < 0.1


def test_jcl_scatter_is_downsampled() -> None:
    acts = _chain([10, 5, 8])
    risks = [_risk("A", 10, 7, 10, 16)]
    cost = eng.CostInputs(base_cost=100000, cost_low=80000, cost_mode=100000, cost_high=150000)
    res = eng.simulate_schedule(acts, None, risks, [], iterations=5000, seed=12, cost_inputs=cost, scatter_points=300)
    assert res.joint_confidence is not None
    assert 0 < len(res.joint_confidence.scatter) <= 300


# ── Distributions ────────────────────────────────────────────────────────────


def test_lognormal_stays_in_clamps_and_is_right_skewed() -> None:
    # A single uncertain activity with a lognormal duration. Drawn values must
    # stay within [low, high]; the distribution is right-skewed so mean > median.
    acts = [Activity(id="A", duration=10, predecessors=[])]
    risks = [_risk("A", 10, 8, 10, 30, dist="lognormal")]
    res = eng.simulate_schedule(acts, None, risks, [], iterations=8000, seed=13, correlation=0.0)
    assert res.percentiles["p5"] >= 8.0 - 1e-6
    assert res.percentiles["p95"] <= 30.0 + 1e-6
    assert res.mean > res.percentiles["p50"], (res.mean, res.percentiles["p50"])


def test_triangular_respects_bounds() -> None:
    acts = [Activity(id="A", duration=10, predecessors=[])]
    risks = [_risk("A", 10, 9, 10, 11, dist="triangular")]
    res = eng.simulate_schedule(acts, None, risks, [], iterations=4000, seed=14)
    assert res.percentiles["p5"] >= 9.0 - 1e-6
    assert res.percentiles["p95"] <= 11.0 + 1e-6


def test_normal_respects_clamps() -> None:
    acts = [Activity(id="A", duration=10, predecessors=[])]
    risks = [_risk("A", 10, 6, 10, 14, dist="normal")]
    res = eng.simulate_schedule(acts, None, risks, [], iterations=6000, seed=15)
    assert res.percentiles["p5"] >= 6.0 - 1e-6
    assert res.percentiles["p95"] <= 14.0 + 1e-6
    # Symmetric: mean ~ median ~ mode.
    assert abs(res.mean - 10.0) < 0.5
    assert abs(res.percentiles["p50"] - 10.0) < 0.5


# ── Structure ────────────────────────────────────────────────────────────────


def test_histogram_counts_sum_to_iterations() -> None:
    acts = _chain([10, 5])
    risks = [_risk("A", 10, 7, 10, 16), _risk("B", 5, 3, 5, 9)]
    res = eng.simulate_schedule(acts, None, risks, [], iterations=3000, seed=16)
    assert sum(b.count for b in res.histogram) == 3000


def test_cdf_is_monotone_and_bounded() -> None:
    acts = _chain([10, 5])
    risks = [_risk("A", 10, 7, 10, 16), _risk("B", 5, 3, 5, 9)]
    res = eng.simulate_schedule(acts, None, risks, [], iterations=3000, seed=17)
    probs = [pt.cumulative_prob for pt in res.cdf]
    costs = [pt.cost for pt in res.cdf]
    assert probs[0] == 0.0 and abs(probs[-1] - 1.0) < 1e-9
    assert probs == sorted(probs)
    assert costs == sorted(costs)


def test_tornado_ranks_widest_band_first() -> None:
    # Two activities on one chain; the wide-band one must dominate the tornado.
    acts = _chain([10, 10])
    risks = [
        _risk("A", 10, 9, 10, 11),  # tight
        _risk("B", 10, 4, 10, 20),  # wide
    ]
    res = eng.simulate_schedule(acts, None, risks, [], iterations=6000, seed=18, correlation=0.0)
    assert res.drivers[0].activity_id == "B"
    assert abs(res.drivers[0].rank_correlation) > abs(res.drivers[-1].rank_correlation)


def test_convergence_reports_for_large_runs() -> None:
    acts = _chain([10, 5, 8])
    risks = [_risk("A", 10, 7, 10, 16), _risk("B", 5, 3, 5, 9), _risk("C", 8, 6, 8, 13)]
    res = eng.simulate_schedule(acts, None, risks, [], iterations=20000, seed=19)
    assert res.convergence_status in {"converged", "marginal"}
    assert res.convergence_margin_pct < 2.0


# ── Errors ───────────────────────────────────────────────────────────────────


def test_cycle_network_raises() -> None:
    acts = [
        Activity(id="A", duration=5, predecessors=[("C", "FS", 0)]),
        Activity(id="B", duration=5, predecessors=[("A", "FS", 0)]),
        Activity(id="C", duration=5, predecessors=[("B", "FS", 0)]),
    ]
    with pytest.raises(CycleError):
        eng.simulate_schedule(acts, None, [], [], iterations=500, seed=20)


def test_empty_network_is_safe() -> None:
    res = eng.simulate_schedule([], None, [], [], iterations=500, seed=21)
    assert res.deterministic_finish == 0.0
    assert res.mean == 0.0
    assert res.criticality == []
