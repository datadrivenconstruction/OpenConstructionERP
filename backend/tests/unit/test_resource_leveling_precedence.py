# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Precedence feasibility of the resource-leveling priority queue.

The leveler orders activities by the shipped key (LS asc -> total_float asc ->
id) and places them one at a time, bounding each start by the predecessors it has
already placed. That key is only precedence-feasible while lag is non-negative::

    FS lag L: LS(pred) <= LS(succ) - L - dur(pred)
    SS lag L: LS(pred) <= LS(succ) - L

Under a negative lag a predecessor can sort AFTER its own successor. The
successor is then bounded by nothing (its predecessor is unplaced, so
``_earliest_legal_start`` skips it) and lands on its base CPM early start, which
can violate the link the CPM page draws.

These tests pin the fix from both sides: the emitted plan must satisfy every link
it was given, and FS-only networks must keep the order -- and therefore the diff
-- they had before the gate existed.

Pure module: imports only the engine, the CPM engine and the standard library, so
it runs without a database.
"""

from __future__ import annotations

from typing import Any

from app.modules.resources.resource_engine import (
    _precedence_feasible_order,
    level_by_resource_units,
    level_preview,
)
from app.modules.schedule_advanced.cpm import Activity, CPMResult, TaskNetwork, compute_cpm

# ── Helpers ──────────────────────────────────────────────────────────────────


def _starts(
    network: TaskNetwork,
    base: dict[Any, CPMResult],
    diff: dict[Any, int],
) -> dict[Any, int]:
    """Leveled start per activity: the diff where it moved, base ES otherwise."""
    return {aid: diff.get(aid, result.es) for aid, result in base.items()}


def _link_violations(
    network: TaskNetwork,
    starts: dict[Any, int],
) -> list[tuple[Any, Any, str, int]]:
    """Every PDM link the leveled starts break, as ``(pred, succ, type, lag)``.

    Mirrors the forward-pass algebra in ``compute_cpm`` as a lower bound on the
    successor start, the same algebra ``_earliest_legal_start`` enforces.
    """
    duration = {a.id: max(0, int(a.duration)) for a in network.activities}
    broken: list[tuple[Any, Any, str, int]] = []
    for activity in network.activities:
        succ = activity.id
        if succ not in starts:
            continue
        s_start = starts[succ]
        for p_id, dep_type, lag in network.predecessors(succ):
            if p_id not in starts:
                continue
            p_start = starts[p_id]
            p_finish = p_start + duration.get(p_id, 0)
            if dep_type == "SS":
                bound = p_start + lag
            elif dep_type == "FF":
                bound = p_finish + lag - duration.get(succ, 0)
            elif dep_type == "SF":
                bound = p_start + lag - duration.get(succ, 0)
            else:  # FS
                bound = p_finish + lag
            if s_start < bound:
                broken.append((p_id, succ, dep_type, lag))
    return broken


# ── The inversion itself ─────────────────────────────────────────────────────


def test_negative_ss_lag_inverts_the_raw_priority_key() -> None:
    """The premise: without the gate the predecessor really does sort second.

    If this ever stops holding the tests below stop testing anything, so the
    inversion is pinned explicitly rather than assumed.
    """
    acts = [
        Activity(id="LONG", duration=8, required_resources={"crew": 2}),
        Activity(
            id="SHORT",
            duration=1,
            required_resources={"crew": 2},
            predecessors=[("LONG", "SS", -4)],
        ),
        Activity(id="FILL", duration=3, required_resources={"crew": 2}),
    ]
    net = TaskNetwork(acts)
    base = compute_cpm(net)
    raw = sorted(base, key=lambda aid: (base[aid].ls, base[aid].total_float, str(aid)))
    assert raw.index("SHORT") < raw.index("LONG")

    gated = _precedence_feasible_order(net, raw)
    assert gated.index("LONG") < gated.index("SHORT")


# ── The plan the user gets ───────────────────────────────────────────────────


def test_negative_ss_lag_plan_honours_the_link() -> None:
    acts = [
        Activity(id="LONG", duration=8, required_resources={"crew": 2}),
        Activity(
            id="SHORT",
            duration=1,
            required_resources={"crew": 2},
            predecessors=[("LONG", "SS", -4)],
        ),
        Activity(id="FILL", duration=3, required_resources={"crew": 2}),
    ]
    net = TaskNetwork(acts)
    base = compute_cpm(net)
    diff, _segments, _unresolvable = level_by_resource_units(net, base, {"crew": 3})
    assert _link_violations(net, _starts(net, base, diff)) == []


def test_negative_fs_lag_plan_honours_the_link() -> None:
    """FS with a lag more negative than the predecessor's duration."""
    acts = [
        Activity(id="P", duration=1, required_resources={"crew": 2}),
        Activity(
            id="S",
            duration=4,
            required_resources={"crew": 2},
            predecessors=[("P", "FS", -3)],
        ),
    ]
    net = TaskNetwork(acts)
    base = compute_cpm(net)
    diff, _segments, _unresolvable = level_by_resource_units(net, base, {"crew": 3})
    assert _link_violations(net, _starts(net, base, diff)) == []


def test_zero_duration_milestone_predecessor_honours_the_link() -> None:
    """A zero-duration predecessor under a negative lag is the other inverting shape."""
    acts = [
        Activity(id="M", duration=0, predecessors=[]),
        Activity(id="A", duration=5, required_resources={"crew": 2}, predecessors=[("M", "FS", 0)]),
        Activity(
            id="B",
            duration=2,
            required_resources={"crew": 2},
            predecessors=[("A", "SS", -3)],
        ),
        Activity(id="C", duration=4, required_resources={"crew": 2}),
    ]
    net = TaskNetwork(acts)
    base = compute_cpm(net)
    diff, _segments, _unresolvable = level_by_resource_units(net, base, {"crew": 3})
    assert _link_violations(net, _starts(net, base, diff)) == []


def test_ff_and_sf_links_with_negative_lag_honour_their_bounds() -> None:
    acts = [
        Activity(id="A", duration=6, required_resources={"crew": 2}),
        Activity(
            id="B",
            duration=2,
            required_resources={"crew": 2},
            predecessors=[("A", "FF", -2)],
        ),
        Activity(
            id="C",
            duration=1,
            required_resources={"crew": 2},
            predecessors=[("A", "SF", -1)],
        ),
        Activity(id="D", duration=3, required_resources={"crew": 2}),
    ]
    net = TaskNetwork(acts)
    base = compute_cpm(net)
    diff, _segments, _unresolvable = level_by_resource_units(net, base, {"crew": 3})
    assert _link_violations(net, _starts(net, base, diff)) == []


def test_level_preview_plan_honours_the_link() -> None:
    """The endpoint surface, not just the inner function."""
    acts = [
        Activity(id="LONG", duration=8, required_resources={"crew": 2}),
        Activity(
            id="SHORT",
            duration=1,
            required_resources={"crew": 2},
            predecessors=[("LONG", "SS", -4)],
        ),
        Activity(id="FILL", duration=3, required_resources={"crew": 2}),
    ]
    net = TaskNetwork(acts)
    base = compute_cpm(net)
    preview = level_preview(net, {"crew": 3})
    starts = _starts(net, base, {s.activity_id: s.new_es for s in preview.shifts})
    assert _link_violations(net, starts) == []


# ── Back-compat: the gate must be a no-op where the old key was already right ──


def test_fs_only_non_negative_lags_keep_the_raw_priority_order() -> None:
    acts = [
        Activity(id="A", duration=2, required_resources={"r": 1}),
        Activity(id="B", duration=2, required_resources={"r": 1}, predecessors=[("A", "FS", 0)]),
        Activity(id="C", duration=2, required_resources={"r": 1}),
        Activity(id="D", duration=3, required_resources={"r": 1}, predecessors=[("B", "FS", 2)]),
        Activity(id="E", duration=1, required_resources={"r": 1}, predecessors=[("C", "FS", 1)]),
    ]
    net = TaskNetwork(acts)
    base = compute_cpm(net)
    raw = sorted(base, key=lambda aid: (base[aid].ls, base[aid].total_float, str(aid)))
    assert _precedence_feasible_order(net, raw) == raw


def test_ss_with_positive_lag_keeps_the_raw_priority_order() -> None:
    acts = [
        Activity(id="A", duration=4, required_resources={"crew": 2}),
        Activity(
            id="B",
            duration=2,
            required_resources={"crew": 2},
            predecessors=[("A", "SS", 1)],
        ),
    ]
    net = TaskNetwork(acts)
    base = compute_cpm(net)
    raw = sorted(base, key=lambda aid: (base[aid].ls, base[aid].total_float, str(aid)))
    assert _precedence_feasible_order(net, raw) == raw


# ── Inputs the gate must not choke on ────────────────────────────────────────


def test_predecessor_outside_the_cpm_result_is_vacuously_satisfied() -> None:
    """A network predecessor absent from ``priority`` must not starve its successors.

    Leveling only ever places what the CPM result names. Waiting for an id it will
    never place would drop the whole subtree into the cycle fallback.
    """
    acts = [
        Activity(id="A", duration=2),
        Activity(id="B", duration=2, predecessors=[("A", "FS", 0)]),
        Activity(id="C", duration=2, predecessors=[("B", "FS", 0)]),
    ]
    net = TaskNetwork(acts)
    ordered = _precedence_feasible_order(net, ["B", "C"])
    assert ordered == ["B", "C"]


def test_cycle_drains_instead_of_deadlocking() -> None:
    """A cyclic network must still return every activity exactly once.

    ``TaskNetwork`` drops self-loops but keeps two-node cycles, so the gate can be
    handed a set it cannot open. It falls back to the plain key rather than
    spinning; a hang here would look like a hung test run, not a bug.
    """
    acts = [
        Activity(id="X", duration=2, predecessors=[("Y", "FS", 0)]),
        Activity(id="Y", duration=2, predecessors=[("X", "FS", 0)]),
        Activity(id="Z", duration=1),
    ]
    net = TaskNetwork(acts)
    ordered = _precedence_feasible_order(net, ["Z", "X", "Y"])
    assert sorted(ordered, key=str) == ["X", "Y", "Z"]
    assert ordered[0] == "Z"  # the acyclic activity still leads on its key


def test_self_loop_predecessor_does_not_block_itself() -> None:
    acts = [Activity(id="A", duration=2, predecessors=[("A", "FS", 0)])]
    net = TaskNetwork(acts)
    assert _precedence_feasible_order(net, ["A"]) == ["A"]


def test_empty_priority_returns_empty_order() -> None:
    net = TaskNetwork([Activity(id="A", duration=1)])
    assert _precedence_feasible_order(net, []) == []


def test_diamond_network_places_both_branches_after_their_source() -> None:
    acts = [
        Activity(id="SRC", duration=1, required_resources={"crew": 1}),
        Activity(
            id="L",
            duration=4,
            required_resources={"crew": 2},
            predecessors=[("SRC", "SS", -1)],
        ),
        Activity(
            id="R",
            duration=1,
            required_resources={"crew": 2},
            predecessors=[("SRC", "SS", -1)],
        ),
        Activity(
            id="SINK",
            duration=2,
            required_resources={"crew": 2},
            predecessors=[("L", "FS", 0), ("R", "FS", 0)],
        ),
    ]
    net = TaskNetwork(acts)
    base = compute_cpm(net)
    raw = sorted(base, key=lambda aid: (base[aid].ls, base[aid].total_float, str(aid)))
    ordered = _precedence_feasible_order(net, raw)
    assert ordered.index("SRC") < ordered.index("L")
    assert ordered.index("SRC") < ordered.index("R")
    assert ordered.index("L") < ordered.index("SINK")
    assert ordered.index("R") < ordered.index("SINK")

    diff, _segments, _unresolvable = level_by_resource_units(net, base, {"crew": 3})
    assert _link_violations(net, _starts(net, base, diff)) == []
