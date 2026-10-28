# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Tests for the multi-project (schedule-of-schedules) CPM engine - T3.3.

Pure-Python, no DB - everything under test post-processes the output of the
single-project kernel ``compute_cpm`` and imports nothing beyond the
``portfolio_cpm`` + ``cpm`` modules and the standard library.

Coverage maps to the roadmap acceptance criteria for the PURE engine:

* #5 (standalone boundary floor): a B->A cross-project edge modelled as a
  :class:`BoundaryConstraint` floors A's early start at the frozen boundary
  index even though B's activities are absent; a ``broken``-status boundary
  still constrains using the frozen index.
* #6 (cross-project cycle): a cycle that exists only across projects
  (A->B->A via ``cross_edges``) raises :class:`CycleError`.
* a genuine portfolio super-graph pass over two schedules joined by an
  in-scope cross edge: the global early-finish and critical path are correct.
* synthetic boundary nodes never appear in results or the critical path.

Plus: determinism under shuffled input, multiple boundaries on one activity,
the largest of several floors wins, lag handling (incl. negative lag),
stale-status parity with live, and validation of unsupported link types.
"""

from __future__ import annotations

import random

import pytest

from app.modules.schedule_advanced.cpm import (
    Activity,
    CPMResult,
    CycleError,
    TaskNetwork,
    compute_cpm,
)
from app.modules.schedule_advanced.portfolio_cpm import (
    SYNTHETIC_PREFIX,
    BoundaryConstraint,
    CrossEdge,
    compute_portfolio_cpm,
    is_synthetic_id,
    portfolio_critical_path,
    standalone_with_boundaries,
)

# ── Fixtures ─────────────────────────────────────────────────────────────────


def _schedule_a() -> list[Activity]:
    """Project A, id-namespaced. Local chain A1(2) -> A2(3), finish 5.

    A2 will (in the standalone case) also depend on Project B's activity via a
    boundary; that boundary, not the local chain, will drive A2's start.
    """
    return [
        Activity(id="A:1", duration=2, predecessors=[]),
        Activity(id="A:2", duration=3, predecessors=[("A:1", "FS", 0)]),
    ]


def _schedule_b() -> list[Activity]:
    """Project B, id-namespaced. Local chain B1(4) -> B2(6), B2 finishes day 10."""
    return [
        Activity(id="B:1", duration=4, predecessors=[]),
        Activity(id="B:2", duration=6, predecessors=[("B:1", "FS", 0)]),
    ]


# ── Acceptance #5: standalone boundary floor ─────────────────────────────────


def test_standalone_boundary_floors_local_start_without_far_activities():
    """B->A cross edge as a BoundaryConstraint floors A's ES at the frozen index.

    Project B's activity (B2) last published an early-finish of day 10. A's
    activity A2 depends on it FS with no lag. Computing A *alone* - B's
    activities are NOT in the list - A2's early start must still floor at 10,
    not at its local predecessor's finish (day 2).
    """
    activities = _schedule_a()
    # Frozen far-side early-finish = 10 (B2's last published EF).
    boundary = BoundaryConstraint(local_activity_id="A:2", dep_type="FS", boundary_index=10, lag=0, status="live")

    results = standalone_with_boundaries(activities, [boundary])

    # A1 unaffected: ES 0, EF 2.
    assert results["A:1"].es == 0
    assert results["A:1"].ef == 2
    # A2 floored at the frozen boundary (10), not its local pred finish (2).
    assert results["A:2"].es == 10
    assert results["A:2"].ef == 13
    # Far side never leaks into results.
    assert set(results) == {"A:1", "A:2"}


def test_standalone_boundary_floor_with_lag():
    """The floor is boundary_index + lag for an FS boundary."""
    activities = _schedule_a()
    boundary = BoundaryConstraint(local_activity_id="A:2", dep_type="FS", boundary_index=10, lag=3)
    results = standalone_with_boundaries(activities, [boundary])
    assert results["A:2"].es == 13  # 10 + 3
    assert results["A:2"].ef == 16


def test_standalone_negative_lag_boundary():
    """A negative lag (lead) lowers the floor but cannot fall below local logic."""
    activities = _schedule_a()
    # Floor would be 10 + (-1) = 9, still above the local pred finish (2).
    boundary = BoundaryConstraint(local_activity_id="A:2", dep_type="FS", boundary_index=10, lag=-1)
    results = standalone_with_boundaries(activities, [boundary])
    assert results["A:2"].es == 9


def test_broken_status_boundary_still_constrains():
    """A `broken`-status boundary still floors the local start (frozen snapshot).

    Acceptance #5, second half: delete B -> link shows `broken`, A still
    constrained by the frozen date (NOT unconstrained). The result must be
    identical to the `live` case - status is provenance only, never math.
    """
    activities = _schedule_a()
    broken = BoundaryConstraint(local_activity_id="A:2", dep_type="FS", boundary_index=10, status="broken")
    live = BoundaryConstraint(local_activity_id="A:2", dep_type="FS", boundary_index=10, status="live")

    broken_res = standalone_with_boundaries(activities, [broken])
    live_res = standalone_with_boundaries(activities, [live])

    assert broken_res["A:2"].es == 10  # frozen index still constrains
    assert broken_res == live_res  # status changes nothing about the numbers


def test_stale_status_boundary_matches_live():
    """A `stale`-status boundary (far side never computed) also constrains identically."""
    activities = _schedule_a()
    stale = BoundaryConstraint(local_activity_id="A:2", dep_type="FS", boundary_index=7, status="stale")
    live = BoundaryConstraint(local_activity_id="A:2", dep_type="FS", boundary_index=7, status="live")
    assert standalone_with_boundaries(activities, [stale]) == standalone_with_boundaries(activities, [live])


def test_boundary_below_local_logic_is_a_no_op():
    """A frozen floor lower than the local predecessor finish does not move ES."""
    activities = _schedule_a()
    # Local A2 starts at day 2 (after A1). A floor of 1 must not lower it.
    boundary = BoundaryConstraint(local_activity_id="A:2", dep_type="FS", boundary_index=1)
    results = standalone_with_boundaries(activities, [boundary])
    assert results["A:2"].es == 2  # local logic wins


def test_multiple_boundaries_largest_floor_wins():
    """When one activity carries several boundaries, the highest floor governs."""
    activities = _schedule_a()
    boundaries = [
        BoundaryConstraint(local_activity_id="A:2", boundary_index=4, lag=1),  # floor 5
        BoundaryConstraint(local_activity_id="A:2", boundary_index=10, lag=0),  # floor 10
        BoundaryConstraint(local_activity_id="A:2", boundary_index=8, lag=1),  # floor 9
    ]
    results = standalone_with_boundaries(activities, boundaries)
    assert results["A:2"].es == 10  # max(5, 10, 9)


def test_ss_boundary_uses_same_construction():
    """An SS boundary floors ES at boundary_index + lag (shares the FS synthetic)."""
    activities = _schedule_a()
    boundary = BoundaryConstraint(local_activity_id="A:2", dep_type="SS", boundary_index=6, lag=2)
    results = standalone_with_boundaries(activities, [boundary])
    assert results["A:2"].es == 8  # 6 + 2


# ── Acceptance #6: cross-project cycle ───────────────────────────────────────


def test_cross_project_cycle_raises():
    """A cycle existing only across projects (A->B->A) raises CycleError.

    Locally each schedule is acyclic; the cycle is closed entirely by the two
    in-scope cross edges A:1 -> B:1 and B:1 -> A:1.
    """
    activities = [
        Activity(id="A:1", duration=2, predecessors=[]),
        Activity(id="B:1", duration=3, predecessors=[]),
    ]
    cross = [
        CrossEdge(predecessor_id="A:1", successor_id="B:1", dep_type="FS"),
        CrossEdge(predecessor_id="B:1", successor_id="A:1", dep_type="FS"),
    ]
    with pytest.raises(CycleError) as exc:
        compute_portfolio_cpm(activities, cross_edges=cross)
    # The offending ids are surfaced (the integrator maps them to names).
    cycle_ids = set(exc.value.cycle_path)
    assert "A:1" in cycle_ids
    assert "B:1" in cycle_ids
    # No synthetic node ever participates in a cross-project cycle.
    assert not any(is_synthetic_id(x) for x in exc.value.cycle_path)


def test_longer_cross_project_cycle_raises():
    """A 3-project cycle A->B->C->A across cross edges also raises."""
    activities = [
        Activity(id="A:1", duration=1),
        Activity(id="B:1", duration=1),
        Activity(id="C:1", duration=1),
    ]
    cross = [
        CrossEdge(predecessor_id="A:1", successor_id="B:1"),
        CrossEdge(predecessor_id="B:1", successor_id="C:1"),
        CrossEdge(predecessor_id="C:1", successor_id="A:1"),
    ]
    with pytest.raises(CycleError):
        compute_portfolio_cpm(activities, cross_edges=cross)


def test_cross_project_cycle_also_raised_by_critical_path():
    """portfolio_critical_path propagates the same CycleError, not a silent empty."""
    activities = [Activity(id="A:1", duration=2), Activity(id="B:1", duration=3)]
    cross = [
        CrossEdge(predecessor_id="A:1", successor_id="B:1"),
        CrossEdge(predecessor_id="B:1", successor_id="A:1"),
    ]
    with pytest.raises(CycleError):
        portfolio_critical_path(activities, cross_edges=cross)


# ── Genuine portfolio super-graph pass over two schedules ────────────────────


def test_portfolio_super_graph_join_two_schedules():
    """Two schedules joined by an in-scope cross edge: global EF + CP are correct.

    Schedule A: A1(2) -> A2(3).            Local A finish = 5.
    Schedule B: B1(4) -> B2(6).            Local B finish = 10.
    Cross edge (REAL): B2 -> A2 (FS, 0).   A2 now waits for B2's finish (10).

    Global forward pass:
        B1: ES 0, EF 4
        B2: ES 4, EF 10
        A1: ES 0, EF 2
        A2: ES max(local A1 EF=2, cross B2 EF=10) = 10, EF 13   <- project finish
    Critical path: B1 -> B2 -> A2 (the date-driving chain across projects).
    """
    activities = _schedule_a() + _schedule_b()
    cross = [CrossEdge(predecessor_id="B:2", successor_id="A:2", dep_type="FS", lag=0)]

    results = compute_portfolio_cpm(activities, cross_edges=cross)

    assert results["B:1"].es == 0 and results["B:1"].ef == 4
    assert results["B:2"].es == 4 and results["B:2"].ef == 10
    assert results["A:1"].es == 0 and results["A:1"].ef == 2
    assert results["A:2"].es == 10 and results["A:2"].ef == 13  # cross edge drives it

    # Global early-finish (max EF) is 13, set by A2 through the cross edge.
    assert max(r.ef for r in results.values()) == 13

    # Critical path spans both projects: B1 -> B2 -> A2.
    cp = portfolio_critical_path(activities, cross_edges=cross)
    assert cp == ["B:1", "B:2", "A:2"]
    # A1 has float (finishes day 2, needed only by day 10) - not critical.
    assert results["A:1"].is_critical is False
    assert results["A:1"].total_float == 8  # 10 - 2


def test_portfolio_two_independent_schedules_each_island_to_own_finish():
    """With no cross edge, the two schedules stay independent islands.

    The kernel anchors each weakly-connected component to its OWN finish, so
    both chains are fully critical at their own length and neither A nor B is
    dragged to the other's finish.
    """
    activities = _schedule_a() + _schedule_b()
    results = compute_portfolio_cpm(activities)

    # Island A finishes at 5; island B at 10; each is internally critical.
    assert results["A:2"].ef == 5
    assert results["B:2"].ef == 10
    assert all(results[a].is_critical for a in ("A:1", "A:2", "B:1", "B:2"))


def test_portfolio_combines_real_cross_edge_and_boundary():
    """A super-graph can mix an in-scope real cross edge and an out-of-scope floor.

    Two in-scope schedules A and B joined by a real edge B2->A2, plus a frozen
    boundary on B1 from a THIRD, out-of-scope project C (C finished day 7).
    B1's start floors at 7, cascading through B2 and the cross edge into A2.
    """
    activities = _schedule_a() + _schedule_b()
    cross = [CrossEdge(predecessor_id="B:2", successor_id="A:2")]
    boundaries = [BoundaryConstraint(local_activity_id="B:1", boundary_index=7)]

    results = compute_portfolio_cpm(activities, cross_edges=cross, boundaries=boundaries)

    assert results["B:1"].es == 7 and results["B:1"].ef == 11
    assert results["B:2"].es == 11 and results["B:2"].ef == 17
    assert results["A:2"].es == 17 and results["A:2"].ef == 20
    assert max(r.ef for r in results.values()) == 20


# ── Synthetic nodes never leak ───────────────────────────────────────────────


def test_synthetic_nodes_absent_from_results():
    """No __boundary__ node appears in the returned results dict."""
    activities = _schedule_a()
    boundaries = [
        BoundaryConstraint(local_activity_id="A:2", boundary_index=10),
        BoundaryConstraint(local_activity_id="A:1", boundary_index=4),
    ]
    results = standalone_with_boundaries(activities, boundaries)
    assert all(not is_synthetic_id(aid) for aid in results)
    assert all(not str(aid).startswith(SYNTHETIC_PREFIX) for aid in results)
    assert set(results) == {"A:1", "A:2"}


def test_synthetic_nodes_absent_from_critical_path():
    """The boundary that drives the critical start does not put a synthetic node on the CP."""
    activities = _schedule_a()
    # Floor A2 well past local logic so the boundary is what drives the finish.
    boundaries = [BoundaryConstraint(local_activity_id="A:2", boundary_index=20)]
    cp = portfolio_critical_path(activities, boundaries=boundaries)
    assert cp, "expected a non-empty critical path"
    assert all(not is_synthetic_id(aid) for aid in cp)
    # A2 (floored to start at 20) is on the critical path; A1 is not the driver.
    assert "A:2" in cp


def test_synthetic_node_does_not_collide_with_real_ids():
    """Real id-namespaced ids and synthetic ids never overlap."""
    activities = _schedule_a()
    boundaries = [BoundaryConstraint(local_activity_id="A:2", boundary_index=5)]
    results = standalone_with_boundaries(activities, boundaries)
    # Real ids use "A:2" style; synthetic uses the "__boundary__" prefix.
    assert not any(aid.startswith(SYNTHETIC_PREFIX) for aid in results)


# ── Result shape parity with the kernel ──────────────────────────────────────


def test_result_shape_matches_kernel():
    """Returned objects are kernel CPMResult instances with the kernel's fields."""
    activities = _schedule_a()
    results = compute_portfolio_cpm(activities)
    r = results["A:2"]
    assert isinstance(r, CPMResult)
    for fld in ("es", "ef", "ls", "lf", "total_float", "free_float", "is_critical"):
        assert hasattr(r, fld)


def test_no_boundaries_no_cross_edges_equals_plain_cpm():
    """With neither boundaries nor cross edges the engine == a plain kernel run."""
    activities = _schedule_a() + _schedule_b()
    portfolio = compute_portfolio_cpm(activities)
    plain = compute_cpm(TaskNetwork(activities))
    assert portfolio == plain


def test_empty_input_returns_empty():
    """An empty activity list yields an empty result and an empty critical path."""
    assert compute_portfolio_cpm([]) == {}
    assert portfolio_critical_path([]) == []


# ── Tolerance: unknown ids dropped, partial sub-network never crashes ─────────


def test_cross_edge_to_unknown_successor_is_dropped():
    """A cross edge whose successor is out of scope is ignored, not a crash."""
    activities = _schedule_a()
    # Successor "Z:9" is not in the merged list - drop quietly.
    cross = [CrossEdge(predecessor_id="A:1", successor_id="Z:9")]
    results = compute_portfolio_cpm(activities, cross_edges=cross)
    assert set(results) == {"A:1", "A:2"}


def test_boundary_for_unknown_local_id_is_ignored():
    """A boundary on an id absent from the merged list is a no-op, not a crash."""
    activities = _schedule_a()
    boundaries = [BoundaryConstraint(local_activity_id="GHOST", boundary_index=99)]
    results = standalone_with_boundaries(activities, boundaries)
    assert set(results) == {"A:1", "A:2"}
    assert results["A:2"].es == 2  # untouched local logic


# ── Validation of unsupported link types / statuses ──────────────────────────


@pytest.mark.parametrize("bad_type", ["FF", "SF"])
def test_unsupported_boundary_dep_type_rejected(bad_type):
    """FF / SF boundary link types raise a clear ValueError in v1."""
    with pytest.raises(ValueError, match="supports only"):
        BoundaryConstraint(local_activity_id="A:2", dep_type=bad_type, boundary_index=5)


def test_invalid_boundary_status_rejected():
    """An out-of-range status raises (must be live | stale | broken)."""
    with pytest.raises(ValueError, match="status must be one of"):
        BoundaryConstraint(local_activity_id="A:2", boundary_index=5, status="green")


def test_boundary_floor_helper():
    """BoundaryConstraint.floor() == boundary_index + lag."""
    assert BoundaryConstraint(local_activity_id="x", boundary_index=10, lag=3).floor() == 13
    assert BoundaryConstraint(local_activity_id="x", boundary_index=10, lag=-2).floor() == 8


# ── Determinism ──────────────────────────────────────────────────────────────


def test_determinism_under_shuffled_input():
    """Shuffling the activity / edge / boundary order yields identical output."""
    base_acts = _schedule_a() + _schedule_b()
    cross = [CrossEdge(predecessor_id="B:2", successor_id="A:2")]
    boundaries = [
        BoundaryConstraint(local_activity_id="B:1", boundary_index=7),
        BoundaryConstraint(local_activity_id="A:1", boundary_index=1),
    ]

    canonical = compute_portfolio_cpm(base_acts, cross_edges=cross, boundaries=boundaries)
    canonical_cp = portfolio_critical_path(base_acts, cross_edges=cross, boundaries=boundaries)

    rng = random.Random(20260623)
    for _ in range(8):
        acts = list(base_acts)
        rng.shuffle(acts)
        cr = list(cross)
        rng.shuffle(cr)
        bd = list(boundaries)
        rng.shuffle(bd)
        assert compute_portfolio_cpm(acts, cross_edges=cr, boundaries=bd) == canonical
        assert portfolio_critical_path(acts, cross_edges=cr, boundaries=bd) == canonical_cp


def test_critical_path_consistent_with_results_is_critical():
    """Every id on the returned critical path is flagged is_critical in results."""
    activities = _schedule_a() + _schedule_b()
    cross = [CrossEdge(predecessor_id="B:2", successor_id="A:2")]
    results = compute_portfolio_cpm(activities, cross_edges=cross)
    cp = portfolio_critical_path(activities, cross_edges=cross)
    for aid in cp:
        assert results[aid].is_critical is True
