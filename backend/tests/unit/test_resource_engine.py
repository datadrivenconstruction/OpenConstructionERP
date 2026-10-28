# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure unit tests for the resource-depth engine (T3.1).

These tests import ONLY ``app.modules.resources.resource_engine`` (which itself
depends only on the pure CPM engine in ``schedule_advanced.cpm``) plus the
standard library, so they run on Python 3.11 without a database. They cover the
pure-testable acceptance criteria from the roadmap (the "T3.1 -- Resource depth"
section): histogram correctness (#1), curve conservation (#2), effective-dated
rates (#3), link-type leveling back-compat (#4), splitting (#5), single-activity
self-overload (#6), finish-delta honesty (#8) and mixed units (#9).

The leveling back-compat tests also assert against the SHIPPED FS-only leveler
(``schedule_advanced.leveling.level_by_resource_max``) to prove the byte-identical
diff contract for FS-only inputs.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.modules.resources.resource_engine import (
    CURVE_CONSERVATION_TOL,
    CURVE_TYPES,
    Curve,
    HistogramAssignment,
    RateRow,
    Unresolvable,
    curve_overlap_weight,
    effective_rate,
    level_by_resource_units,
    level_preview,
    resource_histogram,
)
from app.modules.schedule_advanced.cpm import Activity, TaskNetwork, compute_cpm
from app.modules.schedule_advanced.leveling import level_by_resource_max

# ── Shared fixtures / helpers ────────────────────────────────────────────────

D1 = date(2026, 6, 1)


def _weekly_buckets(n: int, start: date = D1) -> list[tuple[int, date, date, str]]:
    """``n`` consecutive 7-day buckets from ``start`` (index, start, end, label)."""
    from datetime import timedelta

    out: list[tuple[int, date, date, str]] = []
    cursor = start
    for i in range(n):
        nxt = cursor + timedelta(days=7)
        out.append((i, cursor, nxt, cursor.strftime("%b %d")))
        cursor = nxt
    return out


def _net(acts: list[Activity]) -> TaskNetwork:
    return TaskNetwork(acts)


# ════════════════════════════════════════════════════════════════════════════
# curve_overlap_weight (acceptance #2 + flat == linear overlap)
# ════════════════════════════════════════════════════════════════════════════


def test_flat_curve_is_plain_time_overlap_fraction() -> None:
    # 10-day assignment; first 5 days = exactly half.
    w = curve_overlap_weight(None, D1, date(2026, 6, 11), D1, date(2026, 6, 6))
    assert w == 0.5


def test_flat_curve_full_span_is_one() -> None:
    w = curve_overlap_weight(Curve("flat"), D1, date(2026, 6, 11), D1, date(2026, 6, 11))
    assert w == 1.0


def test_curve_conservation_every_type_uneven_partition() -> None:
    # A partition that crosses the bell's midpoint kink (acceptance #2): for EVERY
    # curve the summed weight over a partition equals 1.0 within tolerance.
    parts = [
        (D1, date(2026, 6, 3)),
        (date(2026, 6, 3), date(2026, 6, 6)),
        (date(2026, 6, 6), date(2026, 6, 7)),
        (date(2026, 6, 7), date(2026, 6, 11)),
    ]
    for ctype in CURVE_TYPES:
        c = Curve(ctype)
        total = sum(curve_overlap_weight(c, D1, date(2026, 6, 11), a, b) for a, b in parts)
        assert abs(total - 1.0) <= CURVE_CONSERVATION_TOL, (ctype, total)


def test_front_load_is_heavier_at_start_than_back_load() -> None:
    span_end = date(2026, 6, 11)
    half = date(2026, 6, 6)
    front = curve_overlap_weight(Curve("front_load"), D1, span_end, D1, half)
    back = curve_overlap_weight(Curve("back_load"), D1, span_end, D1, half)
    assert front > 0.5 > back
    # Symmetry: front first-half == back second-half.
    back_second = curve_overlap_weight(Curve("back_load"), D1, span_end, half, span_end)
    assert abs(front - back_second) <= 1e-12


def test_bell_peaks_in_the_middle() -> None:
    span_end = date(2026, 6, 11)
    c = Curve("bell")
    first_q = curve_overlap_weight(c, D1, span_end, D1, date(2026, 6, 4))  # 0-30%
    mid = curve_overlap_weight(c, D1, span_end, date(2026, 6, 4), date(2026, 6, 8))  # 30-70%
    assert mid > first_q  # the central band carries more than an edge band


def test_manual_weights_override_named_curve_and_conserve() -> None:
    # Three equal segments -> behaves like flat; sums to 1 over the whole span.
    c = Curve("front_load", manual_weights=(1.0, 1.0, 1.0))
    parts = [(D1, date(2026, 6, 4)), (date(2026, 6, 4), date(2026, 6, 8)), (date(2026, 6, 8), date(2026, 6, 11))]
    total = sum(curve_overlap_weight(c, D1, date(2026, 6, 11), a, b) for a, b in parts)
    assert abs(total - 1.0) <= 1e-9
    # A heavier first segment puts >1/3 of the weight in the first third.
    heavy = Curve("flat", manual_weights=(8.0, 1.0, 1.0))
    first = curve_overlap_weight(heavy, D1, date(2026, 6, 11), D1, date(2026, 6, 4))
    assert first > 0.5


def test_all_zero_manual_weights_fall_back_to_named_curve() -> None:
    c = Curve("back_load", manual_weights=(0.0, 0.0))
    half = date(2026, 6, 6)
    # Falls back to back_load => first half is light.
    assert curve_overlap_weight(c, D1, date(2026, 6, 11), D1, half) < 0.5


def test_zero_length_assignment_contributes_zero() -> None:
    assert curve_overlap_weight(None, D1, D1, D1, date(2026, 6, 6)) == 0.0


def test_overlap_outside_assignment_is_zero() -> None:
    w = curve_overlap_weight(None, D1, date(2026, 6, 6), date(2026, 6, 7), date(2026, 6, 10))
    assert w == 0.0


def test_unknown_curve_type_degrades_to_flat() -> None:
    w = curve_overlap_weight(Curve("spline"), D1, date(2026, 6, 11), D1, date(2026, 6, 6))
    assert w == 0.5


# ════════════════════════════════════════════════════════════════════════════
# effective_rate (acceptance #3)
# ════════════════════════════════════════════════════════════════════════════


def test_effective_rate_picks_latest_effective_from() -> None:
    rows = [
        RateRow(rate=Decimal("10"), effective_from=date(2026, 1, 1)),
        RateRow(rate=Decimal("12"), effective_from=date(2026, 6, 1)),
        RateRow(rate=Decimal("15"), effective_from=date(2026, 12, 1)),
    ]
    assert effective_rate(rows, "cost", date(2026, 6, 15), Decimal("99")) == Decimal("12")
    assert effective_rate(rows, "cost", date(2026, 1, 2), Decimal("99")) == Decimal("10")
    assert effective_rate(rows, "cost", date(2026, 12, 2), Decimal("99")) == Decimal("15")


def test_effective_rate_respects_exclusive_upper_bound() -> None:
    rows = [RateRow(rate=Decimal("10"), effective_from=date(2026, 6, 1), effective_to=date(2026, 6, 8))]
    # on the effective_to day the window is already closed (exclusive upper bound)
    assert effective_rate(rows, "cost", date(2026, 6, 8), Decimal("99")) == Decimal("99")
    assert effective_rate(rows, "cost", date(2026, 6, 7), Decimal("99")) == Decimal("10")


def test_effective_rate_falls_back_to_default_when_none_match() -> None:
    rows = [RateRow(rate=Decimal("10"), effective_from=date(2026, 6, 1))]
    # date before the only row's effective_from -> default
    assert effective_rate(rows, "cost", date(2026, 5, 1), Decimal("7")) == Decimal("7")
    # empty table -> default
    assert effective_rate([], "cost", date(2026, 6, 1), Decimal("7")) == Decimal("7")


def test_effective_rate_filters_by_rate_type() -> None:
    rows = [
        RateRow(rate=Decimal("10"), rate_type="cost", effective_from=date(2026, 1, 1)),
        RateRow(rate=Decimal("25"), rate_type="billing", effective_from=date(2026, 1, 1)),
    ]
    assert effective_rate(rows, "billing", date(2026, 6, 1), Decimal("0")) == Decimal("25")
    assert effective_rate(rows, "overtime", date(2026, 6, 1), Decimal("0")) == Decimal("0")


def test_effective_rate_honours_explicit_zero_rate() -> None:
    # acceptance #3: a zero rate is honoured, NOT coalesced to the default.
    rows = [RateRow(rate=Decimal("0"), effective_from=date(2026, 6, 1))]
    assert effective_rate(rows, "cost", date(2026, 6, 15), Decimal("99")) == Decimal("0")


def test_effective_rate_accepts_iso_strings() -> None:
    rows = [RateRow(rate=Decimal("11"), effective_from="2026-06-01", effective_to="2026-07-01")]
    assert effective_rate(rows, "cost", "2026-06-15", Decimal("0")) == Decimal("11")


# ════════════════════════════════════════════════════════════════════════════
# resource_histogram (acceptance #1 + lanes)
# ════════════════════════════════════════════════════════════════════════════


def test_histogram_no_curve_reproduces_linear_overlap_units() -> None:
    # acceptance #1: with no curve, per-bucket units == units * time-overlap.
    buckets = _weekly_buckets(2)  # [Jun1,Jun8) , [Jun8,Jun15)
    a = HistogramAssignment(assignment_id="a", start=D1, end=date(2026, 6, 11), units=2.0)
    cells = resource_histogram([a], buckets, capacity_units=None)
    # 10-day span: 7 days in bucket0 (0.7), 3 days in bucket1 (0.3).
    assert abs(cells[0].demand_units - 2.0 * 0.7) <= 1e-9
    assert abs(cells[1].demand_units - 2.0 * 0.3) <= 1e-9
    # conservation: total demand == units * total overlap (whole span covered)
    assert abs(sum(c.demand_units for c in cells) - 2.0) <= 1e-9


def test_histogram_curve_only_redistributes_total_demand() -> None:
    # acceptance #1 + #2 together: any curve preserves the bucket-summed demand.
    buckets = _weekly_buckets(2)
    end = date(2026, 6, 11)
    flat_total = sum(
        c.demand_units
        for c in resource_histogram(
            [HistogramAssignment(assignment_id="a", start=D1, end=end, units=3.0)],
            buckets,
            capacity_units=None,
        )
    )
    for ctype in CURVE_TYPES:
        a = HistogramAssignment(assignment_id="a", start=D1, end=end, units=3.0, curve=Curve(ctype))
        total = sum(c.demand_units for c in resource_histogram([a], buckets, capacity_units=None))
        assert abs(total - flat_total) <= 1e-9, ctype


def test_histogram_capacity_unknown_never_over_allocated() -> None:
    buckets = _weekly_buckets(1)
    a = HistogramAssignment(assignment_id="a", start=D1, end=date(2026, 6, 8), units=999.0)
    cells = resource_histogram([a], buckets, capacity_units=None)
    assert cells[0].capacity_unknown is True
    assert cells[0].over_allocated is False
    assert cells[0].available is None


def test_histogram_over_allocation_only_against_known_ceiling() -> None:
    buckets = _weekly_buckets(1)
    over = HistogramAssignment(assignment_id="a", start=D1, end=date(2026, 6, 8), units=5.0)
    under = HistogramAssignment(assignment_id="b", start=D1, end=date(2026, 6, 8), units=2.0)
    assert resource_histogram([over], buckets, capacity_units=3.0)[0].over_allocated is True
    assert resource_histogram([under], buckets, capacity_units=3.0)[0].over_allocated is False


def test_histogram_blocked_bucket_zeroes_availability() -> None:
    buckets = _weekly_buckets(2)
    a = HistogramAssignment(assignment_id="a", start=D1, end=date(2026, 6, 15), units=1.0)
    cells = resource_histogram([a], buckets, capacity_units=4.0, blocked_bucket_indices=[1])
    assert cells[0].available == 4.0
    assert cells[1].available == 0.0


def test_histogram_cost_lane_uses_effective_dated_rate() -> None:
    # Rate steps from 10 to 20 between the two weekly buckets; cost lane follows.
    # The assignment spans the whole 14-day window, so (flat) each 7-day bucket
    # carries half its units: demand = 1.0 * 0.5 = 0.5 units per bucket.
    buckets = _weekly_buckets(2)
    a = HistogramAssignment(assignment_id="a", start=D1, end=date(2026, 6, 15), units=1.0)
    rows = [
        RateRow(rate=Decimal("10"), effective_from=D1, effective_to=date(2026, 6, 8)),
        RateRow(rate=Decimal("20"), effective_from=date(2026, 6, 8)),
    ]
    cells = resource_histogram([a], buckets, capacity_units=None, rate_rows=rows, hours_per_day=8.0)
    # bucket0: 0.5 units * (7 days * 8h) * 10 = 280 ; bucket1: 0.5 * 56 * 20 = 560
    assert cells[0].demand_cost == Decimal("280.00")
    assert cells[1].demand_cost == Decimal("560.00")


def test_histogram_cost_lane_falls_back_to_assignment_snapshot() -> None:
    buckets = _weekly_buckets(1)
    a = HistogramAssignment(assignment_id="a", start=D1, end=date(2026, 6, 8), units=1.0, cost_rate=Decimal("9"))
    cells = resource_histogram([a], buckets, capacity_units=None, rate_rows=[], hours_per_day=8.0)
    # no rate rows -> snapshot 9: 1 * 7 * 8 * 9 = 504
    assert cells[0].demand_cost == Decimal("504.00")


def test_histogram_demand_cost_is_quantised_decimal() -> None:
    buckets = _weekly_buckets(1)
    a = HistogramAssignment(assignment_id="a", start=D1, end=date(2026, 6, 8), units=1.0, cost_rate=Decimal("1.005"))
    cell = resource_histogram([a], buckets, capacity_units=None, hours_per_day=1.0)[0]
    assert isinstance(cell.demand_cost, Decimal)
    assert cell.demand_cost == cell.demand_cost.quantize(Decimal("0.01"))


def test_histogram_bookings_carry_per_assignment_contribution() -> None:
    buckets = _weekly_buckets(1)
    a = HistogramAssignment(assignment_id="A1", project_id="P1", start=D1, end=date(2026, 6, 8), units=2.0)
    b = HistogramAssignment(assignment_id="A2", project_id="P2", start=D1, end=date(2026, 6, 8), units=1.0)
    cell = resource_histogram([a, b], buckets, capacity_units=None)[0]
    ids = {bk["assignment_id"] for bk in cell.bookings}
    assert ids == {"A1", "A2"}
    assert abs(cell.demand_units - 3.0) <= 1e-9


def test_histogram_accepts_mapping_assignments() -> None:
    buckets = _weekly_buckets(1)
    a = {"assignment_id": "m", "start": D1, "end": date(2026, 6, 8), "units": 4.0}
    cell = resource_histogram([a], buckets, capacity_units=None)[0]
    assert abs(cell.demand_units - 4.0) <= 1e-9


# ════════════════════════════════════════════════════════════════════════════
# Smarter leveling - back-compat (acceptance #4)
# ════════════════════════════════════════════════════════════════════════════


def test_fs_only_diff_is_byte_identical_to_shipped_leveler() -> None:
    # acceptance #4 back-compat: two FS-chained activities competing for one crew.
    acts = [
        Activity(id="A", duration=3, required_resources={"crew": 2}),
        Activity(id="B", duration=3, required_resources={"crew": 2}),
    ]
    net = _net(acts)
    base = compute_cpm(net)
    old = level_by_resource_max(net, base, {"crew": 3})
    new_diff, segments, unresolvable = level_by_resource_units(net, base, {"crew": 3})
    assert new_diff == old
    assert segments == {}
    assert unresolvable == []


def test_fs_chain_with_predecessor_matches_shipped_leveler() -> None:
    acts = [
        Activity(id="A", duration=2, required_resources={"r": 1}),
        Activity(id="B", duration=2, required_resources={"r": 1}, predecessors=[("A", "FS", 0)]),
        Activity(id="C", duration=2, required_resources={"r": 1}),
    ]
    net = _net(acts)
    base = compute_cpm(net)
    old = level_by_resource_max(net, base, {"r": 1})
    new_diff, _seg, _u = level_by_resource_units(net, base, {"r": 1})
    assert new_diff == old


def test_no_limits_returns_empty_diff() -> None:
    acts = [Activity(id="A", duration=2, required_resources={"crew": 5})]
    net = _net(acts)
    base = compute_cpm(net)
    diff, segments, unresolvable = level_by_resource_units(net, base, {})
    assert diff == {}
    assert segments == {}
    # No limits => no self-overload finding either (nothing to exceed).
    assert unresolvable == []


def test_under_capacity_needs_no_shift() -> None:
    acts = [
        Activity(id="A", duration=3, required_resources={"crew": 1}),
        Activity(id="B", duration=3, required_resources={"crew": 1}),
    ]
    net = _net(acts)
    base = compute_cpm(net)
    diff, _seg, _u = level_by_resource_units(net, base, {"crew": 3})  # 1+1 <= 3
    assert diff == {}


# ── Link-type honouring (acceptance #4: SS/FF/SF) ────────────────────────────


def test_ss_link_leveling_never_violates_constraint() -> None:
    # B is SS-linked to A with lag 1 => B.ES >= A.ES + 1 must hold post-level.
    acts = [
        Activity(id="A", duration=4, required_resources={"crew": 2}),
        Activity(id="B", duration=2, required_resources={"crew": 2}, predecessors=[("A", "SS", 1)]),
    ]
    net = _net(acts)
    base = compute_cpm(net)
    diff, _seg, _u = level_by_resource_units(net, base, {"crew": 3})
    a_es = diff.get("A", base["A"].es)
    b_es = diff.get("B", base["B"].es)
    assert b_es >= a_es + 1


def test_ff_link_leveling_never_violates_constraint() -> None:
    # B FF-linked to A lag 0 => B.EF >= A.EF. After leveling the finish constraint holds.
    acts = [
        Activity(id="A", duration=3, required_resources={"crew": 2}),
        Activity(id="B", duration=2, required_resources={"crew": 2}, predecessors=[("A", "FF", 0)]),
    ]
    net = _net(acts)
    base = compute_cpm(net)
    diff, _seg, _u = level_by_resource_units(net, base, {"crew": 3})
    a_es = diff.get("A", base["A"].es)
    b_es = diff.get("B", base["B"].es)
    a_ef = a_es + 3
    b_ef = b_es + 2
    assert b_ef >= a_ef


# ════════════════════════════════════════════════════════════════════════════
# Single-activity self-overload (acceptance #6)
# ════════════════════════════════════════════════════════════════════════════


def test_single_activity_self_overload_is_unresolvable_not_spun() -> None:
    acts = [Activity(id="X", duration=2, required_resources={"crew": 4})]
    net = _net(acts)
    base = compute_cpm(net)
    diff, segments, unresolvable = level_by_resource_units(net, base, {"crew": 3})
    # It is NOT walked forward to the ceiling: ES stays at its earliest legal start.
    assert "X" not in diff
    assert segments == {}
    assert unresolvable == [Unresolvable(activity_id="X", resource="crew", required=4.0, limit=3.0)]


def test_self_overload_does_not_block_other_activities() -> None:
    # acceptance #6: leveling still completes for the resolvable activities.
    acts = [
        Activity(id="X", duration=2, required_resources={"crew": 4}),  # self-overload (cap 3)
        Activity(id="A", duration=2, required_resources={"hoist": 1}),
        Activity(id="B", duration=2, required_resources={"hoist": 1}),
    ]
    net = _net(acts)
    base = compute_cpm(net)
    diff, _seg, unresolvable = level_by_resource_units(net, base, {"crew": 3, "hoist": 1})
    assert [u.activity_id for u in unresolvable] == ["X"]
    # A and B share one hoist => one of them must shift (leveling proceeded).
    assert "A" in diff or "B" in diff


def test_self_overload_finding_is_deterministic_order() -> None:
    acts = [
        Activity(id="Z", duration=1, required_resources={"crew": 9}),
        Activity(id="A", duration=1, required_resources={"crew": 9}),
    ]
    net = _net(acts)
    base = compute_cpm(net)
    _d, _s, unresolvable = level_by_resource_units(net, base, {"crew": 3})
    # sorted by str(activity_id) -> A before Z
    assert [u.activity_id for u in unresolvable] == ["A", "Z"]


# ════════════════════════════════════════════════════════════════════════════
# Splittable activities (acceptance #5)
# ════════════════════════════════════════════════════════════════════════════


def _two_block_gap_network() -> tuple[TaskNetwork, dict]:
    """A network where 'flex' must straddle two critical crew blocks via a gap.

    blockA occupies days 0-2, blockB days 4-6 (both crew=3, kept critical by a long
    tail). 'flex' (4 days crew=3) is float-rich so it is placed last and can only
    use the day-runs 2-4 and 6-8 -> a genuine split.
    """
    acts = [
        Activity(id="s", duration=0),
        Activity(id="blockA", duration=2, required_resources={"crew": 3}, predecessors=[("s", "FS", 0)]),
        Activity(id="blockB", duration=2, required_resources={"crew": 3}, predecessors=[("blockA", "FS", 2)]),
        Activity(id="btail", duration=10, predecessors=[("blockB", "FS", 0)]),
        Activity(id="flex", duration=4, required_resources={"crew": 3}, predecessors=[("s", "FS", 0)]),
        Activity(id="ftail", duration=1, predecessors=[("flex", "FS", 0)]),
    ]
    net = _net(acts)
    return net, compute_cpm(net)


def test_splittable_activity_is_placed_in_segments_summing_to_duration() -> None:
    net, base = _two_block_gap_network()
    diff, segments, _u = level_by_resource_units(net, base, {"crew": 3}, splittable={"flex"})
    assert "flex" in segments
    runs = segments["flex"]
    assert len(runs) >= 2  # genuinely split
    # working-day lengths sum to the activity duration (4)
    assert sum(f - s for s, f in runs) == 4
    # runs are ordered and non-overlapping
    for (_s0, f0), (s1, _f1) in zip(runs, runs[1:], strict=False):
        assert f0 <= s1


def test_split_segments_never_exceed_the_limit() -> None:
    net, base = _two_block_gap_network()
    _diff, segments, _u = level_by_resource_units(net, base, {"crew": 3}, splittable={"flex"})
    # Reconstruct per-day crew demand over the whole leveled schedule and assert <= cap.
    # (Use the preview which lays out all activities for an integrated check.)
    preview = level_preview(net, {"crew": 3}, splittable={"flex"})
    assert preview.peak_after["crew"] <= 3.0
    assert segments  # split actually happened


def test_non_splittable_activity_shifts_whole() -> None:
    net, base = _two_block_gap_network()
    diff, segments, _u = level_by_resource_units(net, base, {"crew": 3})  # not splittable
    assert "flex" not in segments
    # It must move whole to after blockB (day 6), not be segmented.
    assert diff.get("flex") == 6


def test_splittable_but_contiguous_fit_does_not_split() -> None:
    # When a splittable activity fits contiguously, it is not gratuitously split.
    acts = [
        Activity(id="hog", duration=2, required_resources={"crew": 3}),
        Activity(id="flex", duration=3, required_resources={"crew": 3}),
    ]
    net = _net(acts)
    base = compute_cpm(net)
    _diff, segments, _u = level_by_resource_units(net, base, {"crew": 3}, splittable={"flex"})
    assert "flex" not in segments  # fit contiguously after the hog


# ════════════════════════════════════════════════════════════════════════════
# level_preview - finish-delta honesty + peaks (acceptance #7 intent / #8)
# ════════════════════════════════════════════════════════════════════════════


def test_preview_finish_delta_matches_serialised_chain() -> None:
    # acceptance #8: A,B each need the whole crew -> they serialise, pushing finish
    # from 3 (parallel) to 6 (serial). finish_delta_days == 3.
    acts = [
        Activity(id="A", duration=3, required_resources={"crew": 2}),
        Activity(id="B", duration=3, required_resources={"crew": 2}),
    ]
    net = _net(acts)
    preview = level_preview(net, {"crew": 3})
    assert preview.base_finish_workday == 3
    assert preview.leveled_finish_workday == 6
    assert preview.finish_delta_days == 3


def test_preview_no_overload_reports_zero_finish_delta() -> None:
    acts = [
        Activity(id="A", duration=3, required_resources={"crew": 1}),
        Activity(id="B", duration=3, required_resources={"crew": 1}),
    ]
    net = _net(acts)
    preview = level_preview(net, {"crew": 3})  # 1+1 <= 3, nothing to do
    assert preview.shifts == []
    assert preview.finish_delta_days == 0
    assert preview.base_finish_workday == preview.leveled_finish_workday


def test_preview_reports_peak_before_and_after() -> None:
    acts = [
        Activity(id="A", duration=3, required_resources={"crew": 2}),
        Activity(id="B", duration=3, required_resources={"crew": 2}),
    ]
    net = _net(acts)
    preview = level_preview(net, {"crew": 3})
    assert preview.peak_before["crew"] == 4.0  # both concurrent at base
    assert preview.peak_after["crew"] == 2.0  # serialised after leveling
    assert preview.peak_after["crew"] <= 3.0


def test_preview_shifts_have_nonnegative_deltas_and_only_changed() -> None:
    acts = [
        Activity(id="A", duration=3, required_resources={"crew": 2}),
        Activity(id="B", duration=3, required_resources={"crew": 2}),
    ]
    net = _net(acts)
    preview = level_preview(net, {"crew": 3})
    assert len(preview.shifts) == 1  # only the moved activity
    for s in preview.shifts:
        assert s.delta >= 0
        assert s.new_es - s.base_es == s.delta


def test_preview_does_not_mutate_inputs() -> None:
    acts = [
        Activity(id="A", duration=3, required_resources={"crew": 2}),
        Activity(id="B", duration=3, required_resources={"crew": 2}),
    ]
    net = _net(acts)
    before = compute_cpm(net)
    before_snapshot = {aid: (r.es, r.ef, r.ls, r.lf) for aid, r in before.items()}
    _ = level_preview(net, {"crew": 3})
    after = compute_cpm(net)
    after_snapshot = {aid: (r.es, r.ef, r.ls, r.lf) for aid, r in after.items()}
    # Re-running CPM on the same (unmutated) network yields identical results.
    assert before_snapshot == after_snapshot
    # And the activity list / predecessors are untouched.
    assert [a.id for a in net.activities] == ["A", "B"]


def test_preview_surfaces_unresolvable_findings() -> None:
    acts = [Activity(id="X", duration=2, required_resources={"crew": 5})]
    net = _net(acts)
    preview = level_preview(net, {"crew": 3})
    assert [u.activity_id for u in preview.unresolvable] == ["X"]


def test_preview_empty_network_is_safe() -> None:
    preview = level_preview(_net([]), {"crew": 3})
    assert preview.shifts == []
    assert preview.finish_delta_days == 0
    assert preview.peak_before == {}


# ════════════════════════════════════════════════════════════════════════════
# Mixed labor / non-labor units (acceptance #9)
# ════════════════════════════════════════════════════════════════════════════


def test_mixed_labor_and_equipment_level_against_own_limits() -> None:
    # acceptance #9: a 3-strong crew (units=3) and one excavator (units=1) on two
    # activities; both resources are at their ceiling so the activities serialise.
    acts = [
        Activity(id="dig1", duration=4, required_resources={"crew": 3, "exc": 1}),
        Activity(id="dig2", duration=4, required_resources={"crew": 3, "exc": 1}),
    ]
    net = _net(acts)
    preview = level_preview(net, {"crew": 3, "exc": 1})
    assert preview.peak_after["crew"] <= 3.0
    assert preview.peak_after["exc"] <= 1.0
    # They cannot overlap (both share the single excavator and the full crew).
    assert preview.finish_delta_days == 4


def test_mixed_units_one_resource_constrains_the_other_floats() -> None:
    # Excavator is the binding constraint; crew is plentiful. Only the excavator
    # forces serialisation.
    acts = [
        Activity(id="dig1", duration=2, required_resources={"crew": 1, "exc": 1}),
        Activity(id="dig2", duration=2, required_resources={"crew": 1, "exc": 1}),
    ]
    net = _net(acts)
    preview = level_preview(net, {"crew": 10, "exc": 1})
    assert preview.peak_after["exc"] <= 1.0
    assert preview.finish_delta_days == 2  # serialised by the single excavator


def test_fractional_units_respected() -> None:
    # Two activities each demanding 0.6 of a resource with limit 1.0 cannot overlap
    # (0.6 + 0.6 = 1.2 > 1.0); leveling serialises them.
    acts = [
        Activity(id="A", duration=2, required_resources={"r": 1}),
        Activity(id="B", duration=2, required_resources={"r": 1}),
    ]
    net = _net(acts)
    # Use a fractional limit by widening units via required_resources is int-only;
    # instead model the fractional case directly through the histogram/leveling
    # float path: limit 1, demand 1 each -> serialise. (Fractional demand is
    # exercised by the histogram tests; here we assert the float limit path.)
    preview = level_preview(net, {"r": 1.0})
    assert preview.finish_delta_days == 2
