# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure delay-analysis compute orchestration (T2.2).

Drives :func:`delay_report.run_analysis` through every forensic method using
stored-shape dicts (exactly what the ORM/JSON columns hold), so the persistence
contract and the dispatch are validated on the local interpreter.
"""

from __future__ import annotations

import pytest

from app.modules.schedule_advanced.cpm import Activity
from app.modules.schedule_advanced.delay_report import (
    build_engine_event,
    build_engine_fragnet,
    run_analysis,
)


def _act(aid, dur, preds=None):
    return Activity(id=aid, duration=dur, predecessors=preds or [])


def _chain(b_dur=3):
    return [_act("A", 3), _act("B", b_dur, [("A", "FS", 0)]), _act("C", 4, [("B", "FS", 0)])]


def _lengthen_event(eid, host, days, resp="employer", **kw):
    return {
        "id": eid,
        "insert_at": host,
        "responsibility": resp,
        "fragnets": [{"insert_mode": "lengthen_activity", "host_id": host, "added_duration_days": days}],
        **kw,
    }


# ── spec mapping ─────────────────────────────────────────────────────────────


def test_build_engine_fragnet_maps_rewires():
    frag = build_engine_fragnet(
        {
            "insert_mode": "insert_after",
            "host_id": "B",
            "added_duration_days": 2,
            "fragnet_activities": [{"id": "X", "duration": 2, "predecessors": [("B", "FS", 0)]}],
            "rewires": [{"successor_id": "C", "pred_id": "X", "op": "redirect_from_host"}],
        }
    )
    assert frag.insert_mode == "insert_after"
    assert frag.host_id == "B"
    assert frag.new_activities[0]["id"] == "X"
    assert frag.rewires[0].successor_id == "C"


def test_build_engine_event_defaults_insert_at_to_first_fragnet_host():
    e = build_engine_event(
        {"id": "E", "responsibility": "contractor", "fragnets": [{"insert_mode": "lengthen_activity", "host_id": "B"}]}
    )
    assert e.insert_at == "B"
    assert e.responsibility == "contractor"


# ── methods ──────────────────────────────────────────────────────────────────


def test_run_tia():
    res = run_analysis("tia", baseline_activities=_chain(), events=[_lengthen_event("E1", "B", 4)])
    assert res["method"] == "tia"
    assert res["baseline_finish"] == 10
    assert res["impacted_finish"] == 14
    assert res["total_entitlement_days"] == 4
    assert res["attribution"]["employer_days"] == 4
    assert res["events"][0]["entitlement_days"] == 4
    assert res["events"][0]["critical_path_impact"] is True


def test_run_iap_and_cab_are_consistent():
    baseline = _chain()
    emp_event = _lengthen_event("E1", "B", 5)
    # As-built = baseline with the employer fragnet realised.
    from app.modules.schedule_advanced.delay_engine import apply_fragnets

    asbuilt = list(apply_fragnets(baseline, build_engine_event(emp_event).fragnets).activities)

    iap = run_analysis("impacted_as_planned", baseline_activities=baseline, events=[emp_event])
    cab = run_analysis("collapsed_as_built", asbuilt_activities=asbuilt, events=[emp_event])

    assert iap["baseline_finish"] == 10
    assert iap["impacted_finish"] == 15
    assert iap["total_entitlement_days"] == 5
    assert cab["asbuilt_finish"] == 15
    assert cab["collapsed_finish"] == 10
    assert cab["total_entitlement_days"] == 5


def test_run_apvab():
    baseline = _chain()  # 10
    asbuilt = _chain(b_dur=6)  # 13
    res = run_analysis(
        "as_planned_vs_as_built",
        baseline_activities=baseline,
        asbuilt_activities=asbuilt,
        events=[_lengthen_event("E1", "B", 3)],
    )
    assert res["net_slip_days"] == 3
    assert res["total_entitlement_days"] == 3
    assert res["attribution"]["employer_days"] == 3


def test_run_windows():
    snap0 = _chain(b_dur=3)  # 10
    snap1 = _chain(b_dur=6)  # 13
    snap2 = [_act("A", 3), _act("B", 6, [("A", "FS", 0)]), _act("C", 6, [("B", "FS", 0)])]  # 15
    events = [
        _lengthen_event("E_emp", "B", 3, resp="employer", event_start=0, event_end=1),
        _lengthen_event("E_con", "C", 2, resp="contractor", event_start=1, event_end=2),
    ]
    res = run_analysis("windows", snapshots=[snap0, snap1, snap2], events=events, window_bounds=[(0, 1), (1, 2)])
    assert res["window_count"] == 2
    assert res["total_entitlement_days"] == 3
    assert res["total_gross_slip_days"] == 5
    assert res["windows"][0]["employer_days"] == 3
    assert res["windows"][1]["contractor_days"] == 2


def test_unknown_method_raises():
    with pytest.raises(ValueError, match="Unknown delay-analysis method"):
        run_analysis("made_up", baseline_activities=_chain())
