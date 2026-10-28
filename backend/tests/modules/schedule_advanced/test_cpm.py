# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Tests for the CPM Slice 1 engine + resource leveling + PPC roll-up.

Pure-Python, no DB — the engine is fully decoupled from SQLAlchemy.

Coverage
--------
* test_textbook_six_activity_network_critical_path
* test_forward_pass_es_ef
* test_backward_pass_ls_lf
* test_total_float_correct
* test_cycle_detection_raises
* test_disconnected_subnetwork
* test_resource_leveling_respects_ceiling
* test_ppc_calculation
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.schedule_advanced.cpm import (
    Activity,
    CycleError,
    TaskNetwork,
    compute_cpm,
    critical_path,
)
from app.modules.schedule_advanced.leveling import level_by_resource_max

# ── Textbook six-activity AOA network ─────────────────────────────────────
#
# Classic introductory CPM example (e.g. Pinto, "Project Management"):
#
#     A (3d) ─→ C (5d) ─┐
#                       ├─→ F (3d)
#     B (4d) ─→ D (2d) ─┘
#         └──→ E (3d)        (E is a terminal activity)
#
# Paths:
#     A → C → F = 3 + 5 + 3 = 11   ← critical
#     B → D → F = 4 + 2 + 3 = 9
#     B → E     = 4 + 3     = 7
#
# Expected project finish = 11 working days.
# Critical path = [A, C, F].


def _textbook_network() -> TaskNetwork:
    return TaskNetwork(
        [
            Activity(id="A", duration=3, predecessors=[]),
            Activity(id="B", duration=4, predecessors=[]),
            Activity(id="C", duration=5, predecessors=[("A", "FS", 0)]),
            Activity(id="D", duration=2, predecessors=[("B", "FS", 0)]),
            Activity(id="E", duration=3, predecessors=[("B", "FS", 0)]),
            Activity(
                id="F",
                duration=3,
                predecessors=[("C", "FS", 0), ("D", "FS", 0)],
            ),
        ],
    )


def test_textbook_six_activity_network_critical_path() -> None:
    """Classic 6-activity AOA: critical path = A → C → F, duration = 11 days."""
    network = _textbook_network()
    results = compute_cpm(network)

    assert results["A"].is_critical is True
    assert results["C"].is_critical is True
    assert results["F"].is_critical is True
    assert results["B"].is_critical is False
    assert results["D"].is_critical is False
    assert results["E"].is_critical is False

    # Project finish.
    project_finish = max(r.ef for r in results.values())
    assert project_finish == 11

    # Critical path reconstruction.
    cp = critical_path(network, results)
    assert cp == ["A", "C", "F"]


def test_forward_pass_es_ef() -> None:
    """ES + EF values exactly match the textbook expected schedule."""
    network = _textbook_network()
    results = compute_cpm(network)

    expected = {
        "A": (0, 3),
        "B": (0, 4),
        "C": (3, 8),  # waits for A.EF=3
        "D": (4, 6),  # waits for B.EF=4
        "E": (4, 7),  # waits for B.EF=4
        # F waits for max(C.EF=8, D.EF=6) = 8
        "F": (8, 11),
    }
    for aid, (es, ef) in expected.items():
        assert results[aid].es == es, f"{aid}.es expected {es}, got {results[aid].es}"
        assert results[aid].ef == ef, f"{aid}.ef expected {ef}, got {results[aid].ef}"


def test_backward_pass_ls_lf() -> None:
    """LS + LF values exactly match the textbook expected schedule."""
    network = _textbook_network()
    results = compute_cpm(network)

    # Project finish = 11. Backward pass anchors all sinks at 11.
    expected = {
        # F is critical → LS=8, LF=11
        "F": (8, 11),
        # C is critical → LF must equal F.LS=8 → LS=3
        "C": (3, 8),
        # D feeds F → LF=F.LS=8 → LS=6
        "D": (6, 8),
        # A is critical → LF must equal C.LS=3 → LS=0
        "A": (0, 3),
        # B feeds both D (LS=6) and E (LS=8 since E.LF=11) → LF=min(6,8)=6 → LS=2
        "B": (2, 6),
        # E is a sink → LF=11 → LS=8
        "E": (8, 11),
    }
    for aid, (ls, lf) in expected.items():
        assert results[aid].ls == ls, f"{aid}.ls expected {ls}, got {results[aid].ls}"
        assert results[aid].lf == lf, f"{aid}.lf expected {lf}, got {results[aid].lf}"


def test_total_float_correct() -> None:
    """Total float = LS − ES. Critical chain has float = 0."""
    network = _textbook_network()
    results = compute_cpm(network)

    expected_float = {
        "A": 0,  # critical
        "C": 0,  # critical
        "F": 0,  # critical
        "B": 2,  # LS=2 − ES=0
        "D": 2,  # LS=6 − ES=4
        "E": 4,  # LS=8 − ES=4
    }
    for aid, tf in expected_float.items():
        assert results[aid].total_float == tf, f"{aid}.total_float expected {tf}, got {results[aid].total_float}"


def test_cycle_detection_raises() -> None:
    """A directed cycle (A → B → C → A) raises CycleError with the loop path."""
    network = TaskNetwork(
        [
            Activity(id="A", duration=1, predecessors=[("C", "FS", 0)]),
            Activity(id="B", duration=1, predecessors=[("A", "FS", 0)]),
            Activity(id="C", duration=1, predecessors=[("B", "FS", 0)]),
        ],
    )
    with pytest.raises(CycleError) as exc:
        compute_cpm(network)

    # The cycle path is a list of node ids that closes the loop. First and
    # last must be identical (loop closure).
    cycle = exc.value.cycle_path
    assert len(cycle) >= 3
    assert cycle[0] == cycle[-1]
    # Every node in the cycle must be in the original network.
    assert set(cycle).issubset({"A", "B", "C"})


def test_disconnected_subnetwork() -> None:
    """Two unrelated activity islands each get their own ES/EF + own LF."""
    network = TaskNetwork(
        [
            # Island 1: X (5d) → Y (2d)
            Activity(id="X", duration=5, predecessors=[]),
            Activity(id="Y", duration=2, predecessors=[("X", "FS", 0)]),
            # Island 2: standalone P (3d)
            Activity(id="P", duration=3, predecessors=[]),
        ],
    )
    results = compute_cpm(network)

    # Island 1: X.EF=5, Y.EF=7
    assert results["X"].es == 0
    assert results["X"].ef == 5
    assert results["Y"].es == 5
    assert results["Y"].ef == 7

    # Island 2: P.EF=3, anchored to its own island finish — NOT 7
    assert results["P"].es == 0
    assert results["P"].ef == 3
    assert results["P"].lf == 3
    assert results["P"].is_critical is True

    # Island 1 critical chain has total_float == 0.
    assert results["X"].is_critical is True
    assert results["Y"].is_critical is True


def test_resource_leveling_respects_ceiling() -> None:
    """Three parallel 5-day activities each need 1 crew; ceiling=1 ⇒ they serialise."""
    network = TaskNetwork(
        [
            Activity(id="A", duration=5, predecessors=[], required_resources={"crew": 1}),
            Activity(id="B", duration=5, predecessors=[], required_resources={"crew": 1}),
            Activity(id="C", duration=5, predecessors=[], required_resources={"crew": 1}),
        ],
    )
    base = compute_cpm(network)
    assert base["A"].es == 0
    assert base["B"].es == 0
    assert base["C"].es == 0

    shifted = level_by_resource_max(network, base, {"crew": 1})

    # Two of the three must be shifted; the first stays at 0. With our
    # tie-breaks (LS asc, total_float asc, id asc) we expect A=0,
    # B=5, C=10.
    placements = {aid: shifted.get(aid, base[aid].es) for aid in ("A", "B", "C")}
    placement_set = sorted(placements.values())
    assert placement_set == [0, 5, 10], f"got {placement_set}"

    # Verify ceiling never exceeded over any working day.
    by_id = {a.id: a for a in network.activities}
    timeline: dict[int, int] = {}
    for aid, start in placements.items():
        dur = by_id[aid].duration
        for day in range(start, start + dur):
            timeline[day] = timeline.get(day, 0) + by_id[aid].required_resources["crew"]
    assert max(timeline.values()) <= 1


# ── Link-type network (SS / FF / SF + lag) ────────────────────────────────
#
# A mixed network exercising every PDM link type plus lags. Hand-computed
# below; durations in working days, lags in working days.
#
#     A (4d)  ── SS lag 2 ──→ B (3d) ── FS lag 0 ──→ D (3d)
#       │
#       ├────── FF lag 1 ──→ C (2d)
#       │
#       └────── SF lag 8 ──→ E (2d)
#
# Forward pass:
#     A: ES=0, EF=4                       (no predecessors)
#     B: SS → ES >= A.ES+2 = 2            ES=2, EF=5
#     C: FF → EF >= A.EF+1 = 5 → ES=5-2   ES=3, EF=5
#     D: FS → ES >= B.EF+0 = 5            ES=5, EF=8
#     E: SF → EF >= A.ES+8 = 8 → ES=8-2   ES=6, EF=8
#
# Component finish (single weakly-connected island) = max EF = 8.
#
# Backward pass (sinks C, D, E pinned to finish 8):
#     D: sink → LF=8, LS=5
#     E: sink → LF=8, LS=6
#     C: sink → LF=8, LS=6
#     B: FS to D → LF <= D.LS-0 = 5       LF=5, LS=2
#     A: SS to B → LF <= B.LS-2+4 = 4
#        FF to C → LF <= C.LF-1   = 7
#        SF to E → LF <= E.LF-8+4 = 4
#        → LF = min(4,7,4) = 4, LS=0
#
# Total float = LS - ES:
#     A: 0  (critical)   B: 0 (critical)   C: 3   D: 0 (critical)   E: 0 (critical)
#
# Critical path = A → B → D, with E a standalone critical sink: [A, B, D, E].


def _link_type_network() -> TaskNetwork:
    return TaskNetwork(
        [
            Activity(id="A", duration=4, predecessors=[]),
            Activity(id="B", duration=3, predecessors=[("A", "SS", 2)]),
            Activity(id="C", duration=2, predecessors=[("A", "FF", 1)]),
            Activity(id="D", duration=3, predecessors=[("B", "FS", 0)]),
            Activity(id="E", duration=2, predecessors=[("A", "SF", 8)]),
        ],
    )


def test_link_types_forward_pass_es_ef() -> None:
    """SS / FF / SF / FS with lag produce the hand-computed ES/EF."""
    results = compute_cpm(_link_type_network())
    expected = {
        "A": (0, 4),
        "B": (2, 5),  # SS from A, lag 2
        "C": (3, 5),  # FF from A, lag 1
        "D": (5, 8),  # FS from B, lag 0
        "E": (6, 8),  # SF from A, lag 8
    }
    for aid, (es, ef) in expected.items():
        assert results[aid].es == es, f"{aid}.es expected {es}, got {results[aid].es}"
        assert results[aid].ef == ef, f"{aid}.ef expected {ef}, got {results[aid].ef}"


def test_link_types_backward_pass_ls_lf() -> None:
    """Backward pass mirrors each link type to the hand-computed LS/LF."""
    results = compute_cpm(_link_type_network())
    expected = {
        "A": (0, 4),
        "B": (2, 5),
        "C": (6, 8),
        "D": (5, 8),
        "E": (6, 8),
    }
    for aid, (ls, lf) in expected.items():
        assert results[aid].ls == ls, f"{aid}.ls expected {ls}, got {results[aid].ls}"
        assert results[aid].lf == lf, f"{aid}.lf expected {lf}, got {results[aid].lf}"


def test_link_types_total_float_and_critical() -> None:
    """Total float + critical marking across mixed link types."""
    results = compute_cpm(_link_type_network())
    expected_float = {"A": 0, "B": 0, "C": 3, "D": 0, "E": 0}
    for aid, tf in expected_float.items():
        assert results[aid].total_float == tf, f"{aid}.total_float expected {tf}, got {results[aid].total_float}"

    assert results["A"].is_critical is True
    assert results["B"].is_critical is True
    assert results["C"].is_critical is False
    assert results["D"].is_critical is True
    assert results["E"].is_critical is True


def test_link_types_free_float() -> None:
    """Free float respects link type.

    C (FF lag 1 from A) is a terminal sink; its only constraint is the
    component finish (8). C.EF=5 → free float = 8 - 5 = 3. A drives B (SS),
    C (FF) and E (SF) at their earliest; A cannot slip without pushing one
    of them, so A's free float is 0.
    """
    results = compute_cpm(_link_type_network())
    assert results["C"].free_float == 3
    assert results["A"].free_float == 0
    # B feeds D (FS) at D.ES=5 exactly off B.EF=5 → no free float.
    assert results["B"].free_float == 0


def test_link_types_critical_path() -> None:
    """Critical path threads through SS and FS links, plus the SF sink E."""
    network = _link_type_network()
    cp = critical_path(network)
    assert cp == ["A", "B", "D", "E"]


def test_negative_lag_lead_time_ss() -> None:
    """A negative SS lag (lead) lets the successor start before its predecessor.

    A (5d) ── SS lag -2 ──→ B (4d)
        B.ES >= A.ES + (-2) = -2, clamped to 0 by the project-start floor
        (no candidate is negative here because A.ES=0 → -2, but ES is the
        max of candidates and 0 is the implicit floor only when there are
        no predecessors). With a single SS(-2) candidate of -2, B.ES = -2.

    To keep indices non-negative and exercise a meaningful lead, anchor B
    behind a second predecessor. Here we use a clean positive case:

    A (5d) ── SS lag -2 ──→ B (4d) with a parallel FS driver C.
    """
    network = TaskNetwork(
        [
            Activity(id="A", duration=5, predecessors=[]),
            # B can start 2 days before A starts (lead). The only candidate
            # is A.ES + (-2) = -2, so B.ES = -2, B.EF = 2.
            Activity(id="B", duration=4, predecessors=[("A", "SS", -2)]),
        ],
    )
    results = compute_cpm(network)
    assert results["A"].es == 0
    assert results["A"].ef == 5
    assert results["B"].es == -2  # 2-day lead via negative SS lag
    assert results["B"].ef == 2


def test_ff_lag_drives_successor_finish() -> None:
    """FF lag forces the successor to finish ``lag`` days after the predecessor.

    A (6d) ── FF lag 3 ──→ B (2d)
        B.EF >= A.EF + 3 = 9 → B.ES = 9 - 2 = 7, B.EF = 9.
    """
    network = TaskNetwork(
        [
            Activity(id="A", duration=6, predecessors=[]),
            Activity(id="B", duration=2, predecessors=[("A", "FF", 3)]),
        ],
    )
    results = compute_cpm(network)
    assert results["A"].ef == 6
    assert results["B"].es == 7
    assert results["B"].ef == 9


def test_ppc_calculation() -> None:
    """PPC = actual / planned, clamped to [0, 1].

    This mirrors the auto-compute logic in the
    ``POST /schedule-advanced/{schedule_id}/commitments`` endpoint so the
    pure-math invariant is exercised independently of FastAPI.
    """

    def _ppc(planned: str, actual: str) -> Decimal:
        p = Decimal(planned)
        a = Decimal(actual)
        if p <= 0:
            return Decimal("0")
        ratio = a / p
        if ratio > 1:
            return Decimal("1")
        if ratio < 0:
            return Decimal("0")
        return ratio.quantize(Decimal("0.0001"))

    # 100% plan, 100% actual → PPC = 1.0
    assert _ppc("1.0", "1.0") == Decimal("1.0000")
    # 100% plan, 50% actual → PPC = 0.5
    assert _ppc("1.0", "0.5") == Decimal("0.5000")
    # 50% plan, 25% actual → PPC = 0.5
    assert _ppc("0.5", "0.25") == Decimal("0.5000")
    # Zero plan → PPC = 0 (avoid div-by-zero)
    assert _ppc("0", "0.7") == Decimal("0")
    # Over-delivery → clamped to 1.0
    assert _ppc("0.5", "1.0") == Decimal("1")
    # Negative actual (shouldn't happen but guard against it) → 0
    assert _ppc("1.0", "-0.1") == Decimal("0")
