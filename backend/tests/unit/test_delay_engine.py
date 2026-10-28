# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure forensic delay-analysis engine (T2.2).

Covers the engine acceptance criteria: fragnet float-absorption, TIA
regression against a single-duration bump, insert-after / suspend-resume
shifts on a mixed-link fixture, IAP/CAB inverse property, windows
attribution invariant, concurrency under Malmaison + pacing exclusion,
mitigation crediting, and cycle detection. All pure / DB-free.
"""

from __future__ import annotations

import pytest

from app.modules.schedule_advanced.cpm import Activity, CycleError, TaskNetwork, critical_path
from app.modules.schedule_advanced.delay_engine import (
    DelayEvent,
    Fragnet,
    RewireOp,
    apply_fragnets,
    attribute,
    auto_fragnet,
    project_finish,
    run_apvab,
    run_cab,
    run_iap,
    run_tia,
    run_windows,
)


def _act(aid, dur, preds=None):
    return Activity(id=aid, duration=dur, predecessors=preds or [])


def _net(acts):
    return TaskNetwork(list(acts))


def _chain():
    """A(3) -> B(3) -> C(4); finish 10, all critical."""
    return [
        _act("A", 3),
        _act("B", 3, [("A", "FS", 0)]),
        _act("C", 4, [("B", "FS", 0)]),
    ]


def _six_activity_mixed():
    """6 activities, mixed FS/SS/FF + lag. Critical chain A->B->D->F == 14."""
    return [
        _act("A", 3),
        _act("B", 5, [("A", "FS", 0)]),
        _act("C", 2, [("A", "SS", 1)]),
        _act("D", 4, [("B", "FS", 0)]),
        _act("E", 3, [("C", "FS", 0), ("D", "FF", 0)]),
        _act("F", 2, [("D", "FS", 0), ("E", "FS", 0)]),
    ]


# ── 1. Fragnet float-absorption ──────────────────────────────────────────────


def test_lengthen_on_critical_pushes_one_for_one():
    base = _chain()  # finish 10
    net = apply_fragnets(base, [Fragnet("lengthen_activity", "B", added_duration_days=3)])
    assert project_finish(net) == 13  # +3 on the critical path


def test_lengthen_absorbs_float():
    # A(10) and B(2) both feed C(5); B carries 8 days of float.
    base = [
        _act("A", 10),
        _act("B", 2),
        _act("C", 5, [("A", "FS", 0), ("B", "FS", 0)]),
    ]
    assert project_finish(_net(base)) == 15
    # Lengthen B by 3 (< 8 float) -> no completion movement.
    net_small = apply_fragnets(base, [Fragnet("lengthen_activity", "B", added_duration_days=3)])
    assert project_finish(net_small) == 15
    # Lengthen B by 10 (> 8 float) -> max(0, 10 - 8) = 2 days of push.
    net_big = apply_fragnets(base, [Fragnet("lengthen_activity", "B", added_duration_days=10)])
    assert project_finish(net_big) == 17


# ── 2. TIA reproduces the single-duration delta ──────────────────────────────


def test_tia_matches_single_duration_bump():
    base = _chain()  # finish 10, A->B->C all critical
    event = DelayEvent(
        id="E1",
        insert_at="B",
        responsibility="employer",
        fragnets=(Fragnet("lengthen_activity", "B", added_duration_days=4),),
    )
    res = run_tia(base, event)
    assert res.baseline_finish == 10
    assert res.impacted_finish == 14
    assert res.entitlement_days == 4
    assert res.drove_completion is True
    assert res.critical_path_impact is True


def test_tia_entitlement_is_float_absorbed():
    # B has float; a small delay earns no entitlement.
    base = [
        _act("A", 10),
        _act("B", 2),
        _act("C", 5, [("A", "FS", 0), ("B", "FS", 0)]),
    ]
    event = DelayEvent(id="E", insert_at="B", fragnets=(Fragnet("lengthen_activity", "B", added_duration_days=3),))
    res = run_tia(base, event)
    assert res.entitlement_days == 0
    assert res.drove_completion is False


# ── 3. insert_after + suspend_resume on a mixed-link fixture ──────────────────


def test_insert_after_shift_on_mixed_fixture():
    base = _six_activity_mixed()  # finish 14
    net0 = _net(base)
    assert project_finish(net0) == 14
    # Insert 2 days of new work after B (on the critical path).
    frag = auto_fragnet(net0, "B", "insert_after", 2, event_id="ev")
    net1 = apply_fragnets(base, [frag])
    assert project_finish(net1) == 16  # +2, hand-computed


def test_suspend_resume_shift_on_mixed_fixture():
    base = _six_activity_mixed()  # finish 14
    net0 = _net(base)
    frag = auto_fragnet(net0, "D", "suspend_resume", 3, event_id="ev")
    net1 = apply_fragnets(base, [frag])
    assert project_finish(net1) == 17  # suspend 3 days on critical D -> +3


# ── 4. CAB is the inverse of IAP ─────────────────────────────────────────────


def test_cab_is_inverse_of_iap():
    baseline = _chain()  # finish 10
    employer_fragnets = [Fragnet("lengthen_activity", "B", added_duration_days=5)]
    # As-built = baseline with the employer fragnet already realised.
    asbuilt = list(apply_fragnets(baseline, employer_fragnets).activities)

    iap = run_iap(baseline, employer_fragnets)
    cab = run_cab(asbuilt, employer_fragnets)

    # IAP impacts the baseline up to the as-built finish; CAB collapses the
    # as-built back down to the baseline finish.
    assert iap.reference_finish == 10
    assert iap.modelled_finish == 15
    assert cab.reference_finish == 15
    assert cab.modelled_finish == 10
    # The entitlement each method measures is identical (no concurrency).
    assert iap.entitlement_days == cab.entitlement_days == 5


# ── 5. Windows attribution invariant + total entitlement ─────────────────────


def test_windows_attribution_invariant_and_total():
    snap0 = [_act("A", 3), _act("B", 3, [("A", "FS", 0)]), _act("C", 4, [("B", "FS", 0)])]  # 10
    snap1 = [_act("A", 3), _act("B", 6, [("A", "FS", 0)]), _act("C", 4, [("B", "FS", 0)])]  # 13
    snap2 = [_act("A", 3), _act("B", 6, [("A", "FS", 0)]), _act("C", 6, [("B", "FS", 0)])]  # 15
    events = [
        DelayEvent(id="E_emp", insert_at="B", responsibility="employer", event_start=0, event_end=1),
        DelayEvent(id="E_con", insert_at="C", responsibility="contractor", event_start=1, event_end=2),
    ]
    res = run_windows([snap0, snap1, snap2], events, window_bounds=[(0, 1), (1, 2)])

    assert len(res.windows) == 2
    for w in res.windows:
        # No concurrency in these windows -> the parts sum to the gross.
        assert w.gross_slip_days == w.employer_days + w.contractor_days + w.neutral_days
        assert w.concurrent_days == 0
    w1, w2 = res.windows
    assert (w1.gross_slip_days, w1.employer_days, w1.contractor_days) == (3, 3, 0)
    assert (w2.gross_slip_days, w2.employer_days, w2.contractor_days) == (2, 0, 2)
    # Total entitlement == sum of per-window net entitlement (employer time).
    assert res.total_entitlement_days == sum(w.net_entitlement_days for w in res.windows) == 3
    assert res.total_gross_slip_days == 5


# ── 6. Concurrency (Malmaison) + pacing exclusion ────────────────────────────


def test_concurrency_malmaison():
    net = _net([_act("A", 3), _act("B", 6, [("A", "FS", 0)]), _act("C", 6, [("B", "FS", 0)])])
    assert set(critical_path(net)) == {"A", "B", "C"}
    emp = DelayEvent(id="E_emp", insert_at="B", responsibility="employer", event_start=0, event_end=5)
    con = DelayEvent(id="E_con", insert_at="C", responsibility="contractor", event_start=2, event_end=5)
    attr = attribute(5, [emp, con], net, method="malmaison")
    # Employer carries the full EOT; contractor earns nothing; overlap recorded.
    assert attr.employer_days == 5
    assert attr.contractor_days == 0
    assert attr.concurrent_days == 3  # overlap of [0,5] and [2,5]
    assert attr.net_entitlement_days == 5


def test_pacing_event_is_excluded():
    net = _net([_act("A", 3), _act("B", 6, [("A", "FS", 0)]), _act("C", 6, [("B", "FS", 0)])])
    emp = DelayEvent(id="E_emp", insert_at="B", responsibility="employer", event_start=0, event_end=5)
    pace = DelayEvent(
        id="E_pace", insert_at="C", responsibility="contractor", is_pacing=True, event_start=2, event_end=5
    )
    attr = attribute(5, [emp, pace], net, method="malmaison")
    # Pacing contractor event is not in the driving set: no concurrency, and the
    # employer entitlement is undiminished.
    assert attr.employer_days == 5
    assert attr.contractor_days == 0
    assert attr.concurrent_days == 0


def test_dominant_cause_picks_longer_span():
    net = _net([_act("A", 3), _act("B", 6, [("A", "FS", 0)]), _act("C", 6, [("B", "FS", 0)])])
    emp = DelayEvent(id="E_emp", insert_at="B", responsibility="employer", event_start=0, event_end=2)
    con = DelayEvent(id="E_con", insert_at="C", responsibility="contractor", event_start=0, event_end=6)
    attr = attribute(5, [emp, con], net, method="dominant_cause")
    # Contractor span (6) dominates employer span (2).
    assert attr.contractor_days == 5
    assert attr.employer_days == 0


# ── 7. Mitigation / acceleration credited negative ───────────────────────────


def test_mitigation_nets_negative():
    net = _net([_act("A", 3), _act("B", 3, [("A", "FS", 0)]), _act("C", 4, [("B", "FS", 0)])])
    con = DelayEvent(id="E_con", insert_at="B", responsibility="contractor", event_start=0, event_end=2)
    attr = attribute(-2, [con], net, method="malmaison")
    assert attr.contractor_days == -2
    assert attr.employer_days == 0


def test_windows_recovery_window_is_negative():
    snap0 = [_act("A", 3), _act("B", 5, [("A", "FS", 0)]), _act("C", 4, [("B", "FS", 0)])]  # 12
    snap1 = [_act("A", 3), _act("B", 3, [("A", "FS", 0)]), _act("C", 4, [("B", "FS", 0)])]  # 10
    events = [DelayEvent(id="E_con", insert_at="B", responsibility="contractor", event_start=0, event_end=1)]
    res = run_windows([snap0, snap1], events, window_bounds=[(0, 1)])
    w = res.windows[0]
    assert w.gross_slip_days == -2
    assert w.contractor_days == -2
    assert w.net_entitlement_days == 0  # no employer entitlement from recovery


# ── 8. Cycle detection (bad fragnet logic) ───────────────────────────────────


def test_fragnet_introducing_cycle_raises():
    base = [_act("A", 5), _act("B", 5, [("A", "FS", 0)])]
    # New node X depends on B, and A is rewired to depend on X -> A->B->X->A.
    bad = Fragnet(
        insert_mode="insert_parallel",
        host_id="B",
        new_activities=({"id": "X", "duration": 2, "predecessors": [("B", "FS", 0)]},),
        rewires=(RewireOp(successor_id="A", pred_id="X", op="add", dep_type="FS", lag=0),),
    )
    net = apply_fragnets(base, [bad])
    with pytest.raises(CycleError):
        project_finish(net)


# ── APvAB + auto_fragnet shape sanity ────────────────────────────────────────


def test_apvab_net_slip_and_attribution():
    baseline = _chain()  # 10
    asbuilt = [_act("A", 3), _act("B", 6, [("A", "FS", 0)]), _act("C", 4, [("B", "FS", 0)])]  # 13
    events = [DelayEvent(id="E_emp", insert_at="B", responsibility="employer")]
    net_slip, attr = run_apvab(baseline, asbuilt, events)
    assert net_slip == 3
    assert attr.employer_days == 3


def test_auto_fragnet_insert_after_shape():
    net = _net(_chain())
    frag = auto_fragnet(net, "B", "insert_after", 2, event_id="x")
    assert frag.insert_mode == "insert_after"
    assert frag.new_activities[0]["id"] == "B__frag__x"
    # B's single successor C is redirected off the new node.
    assert any(rw.successor_id == "C" and rw.op == "redirect_from_host" for rw in frag.rewires)
