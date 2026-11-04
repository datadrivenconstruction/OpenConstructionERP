"""Window generation and delay rules (pure, no database)."""

from __future__ import annotations

import asyncio
from datetime import date

from app.modules.schedule_advanced.cpm import Activity
from app.modules.schedule_advanced.delay_report import run_analysis
from app.modules.schedule_advanced.delay_windows import (
    SnapshotPoint,
    baseline_durations,
    build_windows,
    pick_snapshot,
    workday_index,
)
from app.modules.schedule_advanced.validators import fragnet_makes_cycle, run_delay_rules

START = date(2026, 1, 5)  # Monday


def _snap(name: str, day: date) -> SnapshotPoint:
    return SnapshotPoint(name=name, data_date=day, durations={})


def test_workday_index_skips_weekends() -> None:
    assert workday_index(START, START) == 0
    assert workday_index(START, date(2026, 1, 10)) == 5  # Mon..Fri counted, Saturday not
    assert workday_index(START, date(2026, 1, 12)) == 5
    assert workday_index(START, date(2026, 1, 13)) == 6
    assert workday_index(START, date(2025, 12, 1)) == 0


def test_month_windows_are_contiguous_and_cover_the_span() -> None:
    wins = build_windows("month", START, date(2026, 4, 20), [])
    assert [w.opens for w in wins] == [START, date(2026, 2, 1), date(2026, 3, 1), date(2026, 4, 1)]
    assert wins[-1].closes == date(2026, 4, 20)
    assert all(a.closes == b.opens for a, b in zip(wins, wins[1:], strict=False))
    assert [w.sequence_order for w in wins] == [1, 2, 3, 4]


def test_quarter_windows_cut_at_quarter_starts() -> None:
    wins = build_windows("quarter", START, date(2026, 11, 1), [])
    assert [w.opens for w in wins] == [START, date(2026, 4, 1), date(2026, 7, 1), date(2026, 10, 1)]


def test_snapshot_windows_cut_at_snapshot_dates() -> None:
    snaps = [_snap("BL1", date(2026, 1, 5)), _snap("BL2", date(2026, 3, 2)), _snap("BL3", date(2026, 5, 4))]
    wins = build_windows("snapshot", START, date(2026, 6, 1), snaps)
    assert [w.opens for w in wins] == [START, date(2026, 3, 2), date(2026, 5, 4)]
    assert wins[0].snapshot_open == "BL1" and wins[0].snapshot_close == "BL2"
    assert wins[-1].snapshot_close is None  # closes on the current schedule
    assert not any(w.no_snapshot for w in wins)


def test_a_month_without_its_own_snapshot_is_flagged() -> None:
    wins = build_windows("month", START, date(2026, 4, 20), [_snap("BL1", date(2026, 1, 5))])
    assert [w.no_snapshot for w in wins] == [True, True, True, False]


def test_no_snapshots_at_all_flags_every_window() -> None:
    assert all(w.no_snapshot for w in build_windows("snapshot", START, date(2026, 3, 1), []))


def test_empty_span_gives_no_windows() -> None:
    assert build_windows("month", START, START, []) == []


def test_many_windows_are_capped() -> None:
    assert len(build_windows("month", date(2000, 1, 3), date(2026, 1, 1), [])) == 60


def test_pick_snapshot_prefers_latest_not_after_the_boundary() -> None:
    a, b = _snap("A", date(2026, 1, 1)), _snap("B", date(2026, 2, 1))
    assert pick_snapshot(date(2026, 1, 20), [b, a]) is a
    assert pick_snapshot(date(2026, 2, 1), [a, b]) is b
    assert pick_snapshot(date(2025, 1, 1), [a, b]) is a
    assert pick_snapshot(date(2025, 1, 1), []) is None


def test_baseline_durations_from_dates_or_explicit_duration() -> None:
    rows = [
        {"task_ref": "t1", "planned_start": "2026-01-05", "planned_finish": "2026-01-09"},
        {"id": "t2", "duration_days": 7},
        {"task_ref": "t3", "planned_start": "2026-01-09", "planned_finish": "2026-01-05"},
        {"planned_start": "2026-01-05"},
    ]
    assert baseline_durations(rows) == {"t1": 5, "t2": 7}
    assert baseline_durations({"tasks": rows[:1]}) == {"t1": 5}


def test_windows_method_reads_finish_movement_between_snapshots() -> None:
    plan = [Activity(id="A", duration=5), Activity(id="B", duration=5, predecessors=[("A", "FS", 0)])]
    slipped = [Activity(id="A", duration=8), Activity(id="B", duration=5, predecessors=[("A", "FS", 0)])]
    out = run_analysis(
        "windows",
        events=[{"id": "e1", "insert_at": "A", "responsibility": "employer", "fragnets": []}],
        snapshots=[plan, slipped],
        window_bounds=[(0, 10)],
    )
    assert out["windows"][0]["gross_slip_days"] == 3
    assert out["windows"][0]["employer_days"] == 3
    assert out["concurrency"] == {"present": False, "days": 0, "apportionment": "malmaison"}


def test_concurrency_is_summed_across_windows() -> None:
    plan = [Activity(id="A", duration=10)]
    slipped = [Activity(id="A", duration=16)]
    events = [
        {"id": "e1", "insert_at": "A", "responsibility": "employer", "event_start": 0, "event_end": 6, "fragnets": []},
        {
            "id": "e2",
            "insert_at": "A",
            "responsibility": "contractor",
            "event_start": 2,
            "event_end": 8,
            "fragnets": [],
        },
    ]
    out = run_analysis("windows", events=events, snapshots=[plan, slipped], window_bounds=[(0, 10)])
    assert out["concurrency"]["present"] is True
    assert out["concurrency"]["days"] == out["windows"][0]["concurrent_days"] > 0


def test_fragnet_cycle_is_detected() -> None:
    base = [Activity(id="A", duration=2), Activity(id="B", duration=2, predecessors=[("A", "FS", 0)])]
    cyc = {
        "id": "e",
        "insert_at": "A",
        "responsibility": "employer",
        "fragnets": [
            {
                "insert_mode": "insert_parallel",
                "host_id": "B",
                "added_duration_days": 0,
                "fragnet_activities": [{"id": "N", "duration": 2, "predecessors": [("B", "FS", 0)]}],
                "rewires": [{"successor_id": "A", "pred_id": "N", "op": "add"}],
            }
        ],
    }
    ok = {**cyc, "fragnets": [{**cyc["fragnets"][0], "rewires": []}]}
    assert fragnet_makes_cycle(base, ok) is False
    assert fragnet_makes_cycle(base, cyc) is True


def test_delay_rules_judge_baseline_dates_and_cycles() -> None:
    payload = {
        "analysis": {"id": "a1", "name": "EOT 1", "has_baseline": False},
        "events": [
            {"id": "e1", "code": "D-1", "outside_project_dates": True, "fragnet_cycle": False},
            {"id": "e2", "code": "D-2", "outside_project_dates": False, "fragnet_cycle": True},
            {"id": "e3", "code": "D-3", "outside_project_dates": None, "fragnet_cycle": None},
        ],
    }
    res = asyncio.run(run_delay_rules(payload))
    by = {(r["rule_id"].split(".")[1], r["element_ref"]): r["passed"] for r in res}
    assert by == {
        ("no_baseline", "a1"): False,
        ("event_outside_project_dates", "e1"): False,
        ("event_outside_project_dates", "e2"): True,
        ("fragnet_cycle", "e1"): True,
        ("fragnet_cycle", "e2"): False,
    }
    assert all(r["details"]["message_key"].startswith("schedule.delay.rules.") for r in res)
